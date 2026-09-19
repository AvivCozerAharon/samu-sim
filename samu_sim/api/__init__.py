"""API de observacao e controle da simulacao."""
import asyncio
import json
import threading
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from samu_sim.api.reaper import Reaper
from samu_sim.core.metricas import calcular
from samu_sim.core.modelos import Base, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio


_STATIC = Path(__file__).parent / "static"
_EVENTOS_MAX = 5000  # buffer em memoria dos ultimos eventos lidos do event log


class _LeitorEventos:
    """Le incrementalmente os JSONL da rodada (todos os servicos escrevem no mesmo
    volume) e mantem um buffer ordenado por ts_sim para o feed do front."""

    def __init__(self, pasta: Path):
        self._pasta = pasta
        self._offsets: dict[Path, int] = {}
        self._buffer: list[dict] = []
        self._lock = threading.Lock()

    def _ler_novos(self) -> None:
        if not self._pasta.exists():
            return
        novos = []
        for arquivo in self._pasta.glob("*.jsonl"):
            pos = self._offsets.get(arquivo, 0)
            with open(arquivo, "rb") as f:
                f.seek(pos)
                dados = f.read()
            if not dados.endswith(b"\n"):  # ultima linha ainda sendo escrita: espera completar
                corte = dados.rfind(b"\n")
                dados = dados[: corte + 1] if corte >= 0 else b""
            self._offsets[arquivo] = pos + len(dados)
            for linha in dados.decode("utf-8").splitlines():
                if linha.strip():
                    try:
                        novos.append(json.loads(linha))
                    except json.JSONDecodeError:
                        continue
        if novos:
            self._buffer.extend(novos)
            self._buffer.sort(key=lambda e: e.get("ts_sim", 0))
            del self._buffer[:-_EVENTOS_MAX]

    def desde(self, ts_sim: float, limite: int) -> list[dict]:
        with self._lock:
            self._ler_novos()
            return [e for e in self._buffer if e.get("ts_sim", 0) > ts_sim][-limite:]


class Controle(BaseModel):
    fator: float | None = Field(default=None, ge=0)
    pausada: bool | None = None
    politica: str | None = None


def criar_app(repo: Repositorio, fila_chamados: Fila, bases: dict[str, Base], relogio: Relogio,
              eventlog: EventLog, agora_real=time.time, reaper_timeout_seg: float = 120.0,
              intervalo_ws_seg: float = 1.0, log_dir=None, rodada_id: str | None = None) -> FastAPI:
    app = FastAPI(title="samu-sim")
    app.state.reaper = Reaper(repo, fila_chamados, bases, eventlog, reaper_timeout_seg, agora_real)
    app.state.relogio = relogio
    rodada_inicial = repo.obter_rodada()
    # ultimo fator > 0 visto; enquanto pausada a rodada guarda fator=0 e este valor restaura no despause
    app.state.fator_ativo = rodada_inicial.fator if rodada_inicial and rodada_inicial.fator > 0 else 1.0
    leitor = _LeitorEventos(Path(log_dir) / rodada_id) if log_dir and rodada_id else None
    lista_bases = [{"id": b.id, "nome": b.nome, "lat": b.lat, "lon": b.lon} for b in bases.values()]

    def snapshot() -> dict:
        rodada = repo.obter_rodada()
        agora = relogio.agora_sim()
        chamados = {c.id: c for c in repo.listar_chamados()}
        abertos = [c for c in chamados.values() if c.status != StatusChamado.ATENDIDO]
        ambulancias = []
        for a in repo.listar_ambulancias():
            item = {"id": a.id, "lat": a.lat, "lon": a.lon, "status": str(a.status),
                    "base_id": a.base_id, "chamado_id": a.chamado_id, "worker_id": a.worker_id,
                    "destino": None, "despachado_em": None, "chegada_prevista_em": None,
                    "chegada_em": None, "liberado_em": None}
            c = chamados.get(a.chamado_id) if a.chamado_id else None
            if c:  # o front interpola a posicao entre a base e o chamado com estes tempos
                item.update({"destino": {"lat": c.lat, "lon": c.lon}, "despachado_em": c.despachado_em,
                             "chegada_prevista_em": c.chegada_prevista_em, "chegada_em": c.chegada_em,
                             "liberado_em": c.liberado_em})
            ambulancias.append(item)
        return {
            "agora_sim": agora,
            "fator": rodada.fator if rodada else relogio.fator,
            "pausada": bool(rodada.pausada) if rodada else relogio.pausado,
            "rodada": asdict(rodada) if rodada else None,
            "bases": lista_bases,
            "ambulancias": ambulancias,
            "chamados_abertos": [{"id": c.id, "lat": c.lat, "lon": c.lon, "zona": c.zona, "bairro": c.bairro,
                                  "status": str(c.status), "criado_em": c.criado_em,
                                  "ambulancia_id": c.ambulancia_id, "despachado_em": c.despachado_em,
                                  "chegada_prevista_em": c.chegada_prevista_em, "chegada_em": c.chegada_em}
                                 for c in abertos],
        }

    app.state.snapshot = snapshot

    @app.get("/", include_in_schema=False)
    def mapa():
        return FileResponse(_STATIC / "mapa.html", media_type="text/html")

    @app.websocket("/ws/estado")
    async def ws_estado(ws: WebSocket):
        """Mesmo snapshot do /estado, empurrado periodicamente (para um front React futuro)."""
        await ws.accept()
        try:
            while True:
                await ws.send_json(await asyncio.to_thread(snapshot))
                await asyncio.sleep(intervalo_ws_seg)
        except WebSocketDisconnect:
            pass

    @app.get("/saude")
    def saude():
        return {"ok": True}

    @app.get("/chamados/{chamado_id}")
    def chamado(chamado_id: str):
        """Chamado completo (inclusive ja atendido) + ambulancia atribuida, para o modo 'seguir'."""
        c = repo.obter_chamado(chamado_id)
        if c is None:
            raise HTTPException(status_code=404, detail="chamado nao encontrado")
        a = repo.obter_ambulancia(c.ambulancia_id) if c.ambulancia_id else None
        dados_c = asdict(c) | {"status": str(c.status)}
        dados_a = (asdict(a) | {"status": str(a.status)}) if a else None
        return {"chamado": dados_c, "ambulancia": dados_a}

    @app.get("/eventos")
    def eventos(desde: float = -1.0, limite: int = 100):
        """Ultimos eventos do event log (todos os servicos) com ts_sim > desde."""
        if leitor is None:
            return []
        return leitor.desde(desde, max(1, min(limite, 500)))

    @app.get("/estado")
    def estado():
        return snapshot()

    @app.get("/metricas")
    def metricas():
        chamados = repo.listar_chamados()
        agora = relogio.agora_sim()
        pendentes = [c for c in chamados if c.status == StatusChamado.PENDENTE]
        idade = max((agora - c.criado_em for c in pendentes), default=0.0)
        return calcular(chamados) | {"agora_sim": agora,
                                     "fila": {"pendentes": len(pendentes), "idade_max_seg": idade}}

    @app.post("/controle")
    def controle(cmd: Controle):
        rodada = repo.obter_rodada()
        if rodada is None:
            raise HTTPException(status_code=409, detail="rodada nao inicializada; rode o bootstrap")
        if cmd.fator is not None and cmd.fator > 0:
            app.state.fator_ativo = cmd.fator
        if cmd.pausada is not None:
            rodada.pausada = cmd.pausada
        if cmd.politica is not None:
            rodada.politica = cmd.politica
        # novo checkpoint: o tempo simulado nao salta ao trocar o fator
        rodada.inicio_sim = relogio.agora_sim()
        rodada.inicio_real = agora_real()
        rodada.fator = 0.0 if rodada.pausada else app.state.fator_ativo
        repo.salvar_rodada(rodada)
        relogio.sincronizar(rodada.inicio_real, rodada.inicio_sim, rodada.fator)
        eventlog.registrar("fator_alterado", fator=rodada.fator, pausada=rodada.pausada,
                           politica=rodada.politica)
        return asdict(rodada)

    return app

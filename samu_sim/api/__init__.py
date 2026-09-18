"""API de observacao e controle da simulacao."""
import time
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from samu_sim.api.reaper import Reaper
from samu_sim.core.metricas import calcular
from samu_sim.core.modelos import Base, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio


class Controle(BaseModel):
    fator: float | None = Field(default=None, ge=0)
    pausada: bool | None = None
    politica: str | None = None


def criar_app(repo: Repositorio, fila_chamados: Fila, bases: dict[str, Base], relogio: Relogio,
              eventlog: EventLog, agora_real=time.time, reaper_timeout_seg: float = 120.0) -> FastAPI:
    app = FastAPI(title="samu-sim")
    app.state.reaper = Reaper(repo, fila_chamados, bases, eventlog, reaper_timeout_seg, agora_real)
    app.state.relogio = relogio
    rodada_inicial = repo.obter_rodada()
    # ultimo fator > 0 visto; enquanto pausada a rodada guarda fator=0 e este valor restaura no despause
    app.state.fator_ativo = rodada_inicial.fator if rodada_inicial and rodada_inicial.fator > 0 else 1.0

    def snapshot() -> dict:
        rodada = repo.obter_rodada()
        agora = relogio.agora_sim()
        abertos = [c for c in repo.listar_chamados() if c.status != StatusChamado.ATENDIDO]
        return {
            "agora_sim": agora,
            "fator": rodada.fator if rodada else relogio.fator,
            "pausada": bool(rodada.pausada) if rodada else relogio.pausado,
            "rodada": asdict(rodada) if rodada else None,
            "ambulancias": [{"id": a.id, "lat": a.lat, "lon": a.lon, "status": str(a.status),
                             "base_id": a.base_id, "chamado_id": a.chamado_id, "worker_id": a.worker_id}
                            for a in repo.listar_ambulancias()],
            "chamados_abertos": [{"id": c.id, "lat": c.lat, "lon": c.lon, "zona": c.zona,
                                  "status": str(c.status), "criado_em": c.criado_em} for c in abertos],
        }

    app.state.snapshot = snapshot

    @app.get("/saude")
    def saude():
        return {"ok": True}

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

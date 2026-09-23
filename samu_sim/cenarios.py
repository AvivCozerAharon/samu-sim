"""Cenarios comparaveis: a mesma pergunta ("e se...?") rodada com N seeds e resumida com IC.

Um cenario descreve a frota, a politica, a alocacao por base, bases extras (candidatas do
experimento D) e as chaves de realismo. `executar` roda uma vez por seed e devolve as
metricas por seed + IC bootstrap; `comparar` faz a diferenca pareada por seed entre dois
cenarios (por isso exige as mesmas seeds). `GerenciadorCenarios` e a fila de jobs da API.
"""
import queue
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass

from samu_sim.core.modelos import ZONAS, Base
from samu_sim.estatistica import diferenca_pareada, ic_bootstrap
from samu_sim.gerador.demanda import CHAMADOS_POR_DIA_RIO

METRICAS = ("p90", "p50", "p90_vermelho", "pendentes") + ZONAS


@dataclass(frozen=True)
class Cenario:
    nome: str
    n_ambulancias: int = 73
    politica: str = "menor_eta"
    alocacao: dict | None = None
    bases_extra: tuple = ()  # tuplas de dicts {id, nome, lat, lon}
    transito: bool = False
    reposicionamento: bool = False

    def para_dict(self) -> dict:
        d = asdict(self)
        d["bases_extra"] = [dict(b) for b in self.bases_extra]
        return d

    @classmethod
    def de_dict(cls, d: dict) -> "Cenario":
        d = dict(d)
        d["bases_extra"] = tuple(dict(b) for b in d.get("bases_extra") or ())
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def objetos_bases_extra(self) -> list[Base]:
        return [Base(b["id"], b["nome"], float(b["lat"]), float(b["lon"]), "candidata") for b in self.bases_extra]


def extrair(r: dict) -> dict:
    """Uma linha de metricas (por seed) a partir do retorno de local.rodar."""
    m = r["metricas"]
    linha = {"p90": m["resposta"]["p90"], "p50": m["resposta"]["p50"], "pendentes": m["pendentes"],
             "p90_vermelho": (m.get("por_prioridade", {}).get("vermelho") or {}).get("p90"),
             "atendidos": m["atendidos"], "total": m["total"]}
    for z in ZONAS:
        linha[z] = (m.get("por_zona", {}).get(z) or {}).get("p90")
    return linha


def executar(cenario: Cenario, seeds: list[int], duracao_sim_seg: float, fator: float, rodar_fn,
             chamados_por_dia: int = CHAMADOS_POR_DIA_RIO, roteador: str = "matriz") -> dict:
    inicio = time.time()
    por_seed = []
    for s in seeds:
        r = rodar_fn(fator=fator, duracao_sim_seg=duracao_sim_seg, n_ambulancias=cenario.n_ambulancias,
                     politica=cenario.politica, roteador=roteador, seed=s, chamados_por_dia=chamados_por_dia,
                     visibilidade_seg=0.2, alocacao=cenario.alocacao, bases_extra=cenario.objetos_bases_extra(),
                     transito=cenario.transito, reposicionamento=cenario.reposicionamento)
        por_seed.append({"seed": s, **extrair(r)})
    resumo = {k: ic_bootstrap([linha[k] for linha in por_seed]) for k in METRICAS}
    return {"cenario": cenario.para_dict(), "seeds": list(seeds), "duracao_sim_seg": duracao_sim_seg,
            "chamados_por_dia": chamados_por_dia, "por_seed": por_seed, "resumo": resumo,
            "tempo_real_seg": round(time.time() - inicio, 1)}


def comparar(base: dict, alt: dict) -> dict:
    """Diferenca (alt - base) pareada por seed, por metrica."""
    if base["seeds"] != alt["seeds"]:
        raise ValueError(f"seeds diferentes: {base['seeds']} vs {alt['seeds']}")
    return {k: diferenca_pareada([linha[k] for linha in base["por_seed"]], [linha[k] for linha in alt["por_seed"]])
            for k in METRICAS}


def criar_gerenciador(fator_max: float = 2000.0) -> "GerenciadorCenarios":
    """Gerenciador ligado ao runner em memoria (local.rodar, roteador matriz). `fator_max` protege
    contra CPU insuficiente: se a maquina nao acompanha o relogio acelerado, os tempos de resposta
    saem inflados (medido: fator 3000 numa t3.micro deu P90 44 min onde o correto era 19)."""
    from samu_sim import local as runner  # import tardio: a API nao precisa do runner para subir
    runner.INTERVALO_OCIOSO_REAL = 0.005  # polling fino: a fator 2000, 20 ms reais = 40 s simulados
    return GerenciadorCenarios(lambda c, seeds, dur, fator: executar(c, seeds, dur, min(fator, fator_max), runner.rodar))


class GerenciadorCenarios:
    """Fila FIFO de cenarios rodando numa unica thread (uma simulacao em memoria por vez)."""

    def __init__(self, executar_fn):
        self._executar = executar_fn  # (cenario, seeds, duracao, fator) -> resultado
        self._jobs: dict[str, dict] = {}
        self._ordem: list[str] = []
        self._fila: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submeter(self, cenario: Cenario, seeds: list[int], duracao_sim_seg: float, fator: float) -> str:
        jid = uuid.uuid4().hex[:8]
        with self._lock:
            self._jobs[jid] = {"id": jid, "status": "na_fila", "cenario": cenario.para_dict(), "seeds": list(seeds),
                               "duracao_sim_seg": duracao_sim_seg, "fator": fator, "criado_em": time.time(),
                               "resultado": None, "erro": None}
            self._ordem.append(jid)
        self._fila.put((jid, cenario, list(seeds), duracao_sim_seg, fator))
        return jid

    def obter(self, jid: str) -> dict | None:
        with self._lock:
            return dict(self._jobs[jid]) if jid in self._jobs else None

    def listar(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in self._jobs[j].items() if k != "resultado"} for j in self._ordem]

    def encerrar(self) -> None:
        self._fila.put(None)

    def _loop(self) -> None:
        while True:
            item = self._fila.get()
            if item is None:
                return
            jid, cenario, seeds, dur, fator = item
            with self._lock:
                self._jobs[jid]["status"] = "rodando"
            try:
                res = self._executar(cenario, seeds, dur, fator)
                with self._lock:
                    self._jobs[jid].update(status="concluido", resultado=res)
            except Exception as e:  # noqa: BLE001 - o job registra qualquer falha
                with self._lock:
                    self._jobs[jid].update(status="erro", erro=f"{e}\n{traceback.format_exc()}")

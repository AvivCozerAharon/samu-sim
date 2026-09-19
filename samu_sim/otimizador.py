"""Otimizador de turnos: roda a simulacao repetidamente e, a cada turno, le o resultado
(event log/chamados), produz um diagnostico legivel e move uma ambulancia entre bases.
Mantem a mudanca se o objetivo melhorou, desfaz se piorou (hill-climbing com memoria).

Isto e otimizacao guiada por dados, nao machine learning: cada decisao tem uma justificativa
que da para narrar ("Zona Oeste tem o pior P90 e a UPA Botafogo esta ociosa 88 % do tempo").
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from samu_sim.core.geo import haversine_km
from samu_sim.core.modelos import Base
from samu_sim.gerador.demanda import Bairro

PESO_PRIORIDADE = {"vermelho": 3.0, "amarelo": 1.0, "verde": 0.5}
RAIO_DEMANDA_KM = 5.0      # demanda "coberta" por uma base: bairros a ate 5 km
ESPERA_RELEVANTE_SEG = 60  # chamado que esperou mais que isso por ambulancia conta como fila


def objetivo(metricas: dict) -> float:
    """J = 3*P90(vermelho) + P90(amarelo) + 0.5*P90(verde), em minutos. Menor e melhor.
    Prioridade sem chegadas usa o P90 global (evita J indefinido no inicio)."""
    geral = metricas["resposta"]["p90"] or 0.0
    j = 0.0
    for p, w in PESO_PRIORIDADE.items():
        v = (metricas.get("por_prioridade", {}).get(p) or {}).get("p90")
        j += w * (v if v is not None else geral)
    # penaliza fila remanescente: cada chamado pendente ao fim do dia custa como 1 min de J
    return j / 60.0 + metricas.get("pendentes", 0)


def diagnosticar(resultado: dict, bases: dict[str, Base], bairros: list[Bairro]) -> dict:
    """Le o resultado de local.rodar (metricas + chamados + ambulancias) e resume:
    P90 por zona/prioridade, utilizacao por base, chamados que esperaram por zona."""
    m = resultado["metricas"]
    duracao = resultado["rodada"]["duracao_sim_seg"]
    ambs_por_base = Counter(a["base_id"] for a in resultado["ambulancias"])
    base_da_amb = {a["id"]: a["base_id"] for a in resultado["ambulancias"]}
    ocupado = defaultdict(float)
    esperaram = Counter()
    for c in resultado["chamados"]:
        if c.get("despachado_em") is not None and c.get("ambulancia_id"):
            fim = c.get("liberado_em") or duracao
            ocupado[base_da_amb.get(c["ambulancia_id"])] += max(0.0, fim - c["despachado_em"])
        if c.get("despachado_em") is not None and c["despachado_em"] - c["criado_em"] > ESPERA_RELEVANTE_SEG:
            esperaram[c["zona"]] += 1
        elif c.get("despachado_em") is None:
            esperaram[c["zona"]] += 1
    utilizacao = {bid: (ocupado[bid] / (n * duracao) if n else 0.0) for bid, n in ambs_por_base.items()}
    zona_da_base = {b.id: _zona_da_base(b, bairros) for b in bases.values()}
    return {
        "J": objetivo(m),
        "p90_global": m["resposta"]["p90"],
        "p90_zona": {z: v["p90"] for z, v in m["por_zona"].items()},
        "p90_prioridade": {p: v["p90"] for p, v in m.get("por_prioridade", {}).items()},
        "pendentes": m["pendentes"],
        "esperaram_por_zona": dict(esperaram),
        "utilizacao_base": utilizacao,
        "ambulancias_base": dict(ambs_por_base),
        "zona_da_base": zona_da_base,
    }


def _zona_da_base(base: Base, bairros: list[Bairro]) -> str:
    mais_proximo = min(bairros, key=lambda b: haversine_km(base.lat, base.lon, b.lat, b.lon))
    return mais_proximo.zona


def demanda_coberta(base: Base, bairros: list[Bairro]) -> float:
    return sum(b.peso for b in bairros if haversine_km(base.lat, base.lon, b.lat, b.lon) <= RAIO_DEMANDA_KM)


def propor(diag: dict, alocacao: dict[str, int], bases: dict[str, Base], bairros: list[Bairro],
           ja_tentadas: set[tuple[str, str]]) -> tuple[dict[str, int] | None, list[str], tuple | None]:
    """Move 1 ambulancia da base mais ociosa (com >= 2) para a base de maior demanda da zona
    com pior P90 ponderado. Devolve (nova alocacao, acoes em texto, (origem, destino)) ou (None, motivo, None)."""
    # zona alvo: pior combinacao de P90 e fila
    pior_zona = None
    pior_score = -1.0
    for zona, p90 in diag["p90_zona"].items():
        score = (p90 or 0) / 60 + 5 * diag["esperaram_por_zona"].get(zona, 0)
        if score > pior_score:
            pior_zona, pior_score = zona, score
    if pior_zona is None:
        return None, ["sem chegadas para diagnosticar"], None
    # origem: menor utilizacao entre bases com >= 2 ambulancias, fora da zona alvo
    candidatas_origem = sorted(
        (bid for bid, n in alocacao.items() if n >= 2 and diag["zona_da_base"].get(bid) != pior_zona),
        key=lambda bid: diag["utilizacao_base"].get(bid, 0.0))
    # destino: bases da zona alvo por demanda coberta, priorizando as com menos ambulancias
    candidatas_destino = sorted(
        (b for b in bases.values() if diag["zona_da_base"].get(b.id) == pior_zona),
        key=lambda b: (-demanda_coberta(b, bairros) / (alocacao.get(b.id, 0) + 1)))
    for origem in candidatas_origem:
        for destino in candidatas_destino:
            if (origem, destino.id) in ja_tentadas or origem == destino.id:
                continue
            nova = dict(alocacao)
            nova[origem] -= 1
            nova[destino.id] = nova.get(destino.id, 0) + 1
            u = diag["utilizacao_base"].get(origem, 0.0)
            acoes = [
                f"Zona {pior_zona} tem o pior resultado: P90 {(diag['p90_zona'][pior_zona] or 0)/60:.0f} min"
                + (f", {diag['esperaram_por_zona'].get(pior_zona, 0)} chamados esperaram por ambulancia" if diag['esperaram_por_zona'].get(pior_zona) else ""),
                f"{bases[origem].nome} esta ociosa {100*(1-u):.0f} % do tempo com {alocacao[origem]} ambulancias",
                f"Mover 1 ambulancia de {bases[origem].nome} para {destino.nome} "
                f"(cobre {demanda_coberta(destino, bairros)/1000:.0f} mil hab. num raio de {RAIO_DEMANDA_KM:.0f} km)",
            ]
            return nova, acoes, (origem, destino.id)
    return None, [f"nenhum movimento novo para a zona {pior_zona} (todos ja tentados)"], None


@dataclass
class Turno:
    numero: int
    alocacao: dict[str, int]
    diagnostico: dict
    acoes: list[str]
    J: float
    J_anterior: float | None
    aceito: bool
    resumo: str = ""


@dataclass
class Otimizador:
    rodar: object                      # callable(alocacao) -> resultado de local.rodar
    bases: dict[str, Base]
    bairros: list[Bairro]
    alocacao: dict[str, int]
    tolerancia: float = 0.01           # aceita se J cair pelo menos 1 %
    historico: list[Turno] = field(default_factory=list)
    ja_tentadas: set = field(default_factory=set)
    _melhor_J: float | None = None
    _proposta: tuple | None = None     # (alocacao proposta, acoes, movimento)

    def turno(self) -> Turno:
        n = len(self.historico) + 1
        if self._proposta is None:  # turno base: mede a alocacao atual
            res = self.rodar(self.alocacao)
            diag = diagnosticar(res, self.bases, self.bairros)
            t = Turno(n, dict(self.alocacao), diag, ["turno base: medindo a alocacao atual"], diag["J"], None, True)
            self._melhor_J = diag["J"]
        else:
            proposta, acoes, movimento = self._proposta
            res = self.rodar(proposta)
            diag = diagnosticar(res, self.bases, self.bairros)
            aceito = diag["J"] <= self._melhor_J * (1 - self.tolerancia)
            self.ja_tentadas.add(movimento)
            if aceito:
                self.alocacao = proposta
                self._melhor_J = diag["J"]
                self.ja_tentadas.clear()
            t = Turno(n, dict(proposta), diag, acoes, diag["J"], self._melhor_J if not aceito else None, aceito)
        t.resumo = (f"turno {n}: J={t.J:.1f}" + (" (base)" if t.J_anterior is None and n == 1 else
                    (" aceito" if t.aceito else f" rejeitado (melhor {self._melhor_J:.1f})")))
        self.historico.append(t)
        # prepara a proxima proposta a partir do melhor estado conhecido
        base_diag = self._diag_do_melhor()
        nova, acoes, movimento = propor(base_diag, self.alocacao, self.bases, self.bairros, self.ja_tentadas)
        if nova is None:
            self._proposta = None
            t.acoes = t.acoes + acoes
        else:
            self._proposta = (nova, acoes, movimento)
        return t

    def _diag_do_melhor(self) -> dict:
        for t in reversed(self.historico):
            if t.aceito:
                return t.diagnostico
        return self.historico[-1].diagnostico

    def executar(self, n_turnos: int) -> list[Turno]:
        for _ in range(n_turnos):
            self.turno()
            if self._proposta is None and len(self.historico) > 1:
                break
        return self.historico

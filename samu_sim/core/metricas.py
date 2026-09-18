"""Metricas de tempo de resposta calculadas a partir dos chamados."""
from collections import defaultdict

from samu_sim.core.modelos import Chamado, StatusChamado


def percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * p / 100.0
    i = int(pos)
    frac = pos - i
    if i + 1 >= len(v):
        return v[-1]
    return v[i] + (v[i + 1] - v[i]) * frac


def _resumo(valores: list[float]) -> dict:
    return {"p50": percentil(valores, 50), "p90": percentil(valores, 90),
            "media": (sum(valores) / len(valores)) if valores else None, "n": len(valores)}


def calcular(chamados: list[Chamado]) -> dict:
    respostas: list[float] = []
    por_zona: dict[str, list[float]] = defaultdict(list)
    esperas: list[float] = []
    for c in chamados:
        if c.despachado_em is not None:
            esperas.append(c.despachado_em - c.criado_em)
        if c.chegada_em is not None:
            r = c.chegada_em - c.criado_em
            respostas.append(r)
            por_zona[c.zona].append(r)
    return {
        "total": len(chamados),
        "atendidos": sum(1 for c in chamados if c.status == StatusChamado.ATENDIDO),
        "despachados": sum(1 for c in chamados if c.status == StatusChamado.DESPACHADO),
        "pendentes": sum(1 for c in chamados if c.status == StatusChamado.PENDENTE),
        "resposta": _resumo(respostas),
        "por_zona": {z: {k: v for k, v in _resumo(vs).items() if k != "media"}
                     for z, vs in sorted(por_zona.items())},
        "espera_despacho": {"p50": percentil(esperas, 50), "p90": percentil(esperas, 90)},
    }

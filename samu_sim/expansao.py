"""Experimento D: onde abrir a proxima base.

Heuristica barata primeiro (demanda populacional descoberta a > raio_km de qualquer base) para
escolher poucas candidatas; a simulacao cara (cenarios com IC) confirma qual delas reduz mais
o P90. Cada candidata vira um Cenario: alocacao atual + `extra` ambulancias na base nova.
"""
import unicodedata

from samu_sim.cenarios import Cenario
from samu_sim.core.geo import haversine_km
from samu_sim.core.modelos import Base
from samu_sim.gerador.demanda import Bairro

RAIO_COBERTURA_KM = 5.0


def _slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return "-".join(p for p in s.replace("'", " ").split() if p)


def _dist_mais_proxima(bairro: Bairro, bases: list[Base]) -> float:
    return min(haversine_km(bairro.lat, bairro.lon, b.lat, b.lon) for b in bases)


def demanda_descoberta(bairro: Bairro, bases: list[Base], raio_km: float = RAIO_COBERTURA_KM) -> float:
    """Peso de demanda do bairro se nenhuma base o alcanca em raio_km; senao 0."""
    return bairro.peso if _dist_mais_proxima(bairro, bases) > raio_km else 0.0


def candidatas(bairros: list[Bairro], bases: list[Base], raio_km: float = RAIO_COBERTURA_KM,
               max_n: int = 12) -> list[dict]:
    """Centroides de bairros descobertos, ordenados por demanda descoberta (maior primeiro)."""
    lista = []
    for b in bairros:
        d = demanda_descoberta(b, bases, raio_km)
        if d <= 0:
            continue
        lista.append({"id": f"cand-{_slug(b.nome)}", "nome": f"Nova base — {b.nome}", "lat": b.lat, "lon": b.lon,
                      "zona": b.zona, "bairro": b.nome,
                      "dist_base_mais_proxima_km": round(_dist_mais_proxima(b, bases), 1),
                      "demanda_descoberta": round(d, 1)})
    lista.sort(key=lambda c: -c["demanda_descoberta"])
    return lista[:max_n]


def cenario_candidata(cand: dict, alocacao_base: dict, extra: int = 2, **flags) -> Cenario:
    """Alocacao atual + `extra` ambulancias na candidata (frota cresce em `extra`)."""
    aloc = dict(alocacao_base)
    aloc[cand["id"]] = aloc.get(cand["id"], 0) + extra
    base = {k: cand[k] for k in ("id", "nome", "lat", "lon")}
    return Cenario(cand["nome"], n_ambulancias=sum(aloc.values()), alocacao=aloc, bases_extra=(base,), **flags)

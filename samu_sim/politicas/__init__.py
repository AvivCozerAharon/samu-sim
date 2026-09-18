"""Politicas de despacho: dado um chamado e as ambulancias disponiveis,
devolvem as candidatas em ordem de preferencia. O despachante tenta reservar
na ordem; se perder a corrida para outro despachante, passa para a proxima."""
from typing import Protocol

from samu_sim.core.geo import haversine_km
from samu_sim.core.modelos import Ambulancia, Chamado
from samu_sim.roteador import Roteador


class Politica(Protocol):
    nome: str

    def escolher(self, chamado: Chamado, disponiveis: list[Ambulancia],
                 roteador: Roteador) -> list[Ambulancia]: ...


class MaisProxima:
    nome = "mais_proxima"

    def escolher(self, chamado, disponiveis, roteador):
        return sorted(disponiveis,
                      key=lambda a: haversine_km(a.lat, a.lon, chamado.lat, chamado.lon))


class MenorEta:
    nome = "menor_eta"

    def escolher(self, chamado, disponiveis, roteador):
        destino = (chamado.lat, chamado.lon)
        return sorted(disponiveis, key=lambda a: roteador.eta((a.lat, a.lon), destino))


_POLITICAS = {"mais_proxima": MaisProxima, "menor_eta": MenorEta}


def criar_politica(nome: str) -> Politica:
    try:
        return _POLITICAS[nome]()
    except KeyError:
        raise ValueError(f"politica desconhecida: {nome}") from None

"""Politicas de despacho: dado um chamado e as ambulancias disponiveis,
devolvem as candidatas em ordem de preferencia. O despachante tenta reservar
na ordem; se perder a corrida para outro despachante, passa para a proxima."""
from collections import Counter
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


class MenorEtaCobertura:
    """Menor ETA, mas penaliza despachar a ultima ambulancia disponivel de uma base
    (deixaria a regiao descoberta). Penalidade em segundos de ETA equivalente."""
    nome = "menor_eta_cobertura"

    def __init__(self, penalidade_seg: float = 600.0):
        self._penalidade = penalidade_seg

    def escolher(self, chamado, disponiveis, roteador):
        por_base = Counter(a.base_id for a in disponiveis)
        destino = (chamado.lat, chamado.lon)

        def chave(a):
            eta = roteador.eta((a.lat, a.lon), destino)
            penal = self._penalidade if por_base[a.base_id] == 1 else 0.0
            return (eta + penal, eta)

        return sorted(disponiveis, key=chave)


_POLITICAS = {"mais_proxima": MaisProxima, "menor_eta": MenorEta,
              "menor_eta_cobertura": MenorEtaCobertura}


def criar_politica(nome: str) -> Politica:
    try:
        return _POLITICAS[nome]()
    except KeyError:
        raise ValueError(f"politica desconhecida: {nome}") from None

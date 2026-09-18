"""Roteador: tempo estimado de viagem (segundos simulados) entre dois pontos."""
from typing import Protocol

from samu_sim.core.geo import haversine_km

Ponto = tuple[float, float]  # (lat, lon)


class Roteador(Protocol):
    nome: str

    def eta(self, origem: Ponto, destino: Ponto) -> float: ...


class RoteadorHaversine:
    nome = "haversine"

    def __init__(self, vel_kmh: float = 30.0):
        self._vel_kmh = vel_kmh

    def eta(self, origem: Ponto, destino: Ponto) -> float:
        km = haversine_km(origem[0], origem[1], destino[0], destino[1])
        return km / self._vel_kmh * 3600.0


def criar_roteador(nome: str) -> Roteador:
    if nome == "haversine":
        return RoteadorHaversine()
    raise ValueError(f"roteador desconhecido: {nome}")

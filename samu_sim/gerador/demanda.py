"""Geracao sintetica de demanda: bairro proporcional a populacao, hora com picos."""
import csv
import random
from dataclasses import dataclass
from pathlib import Path

from samu_sim.core.geo import deslocar
from samu_sim.core.modelos import Base, Chamado

SEGUNDOS_DIA = 86400

# Peso relativo de cada hora do dia (picos 8-11h e 18-21h, vale de madrugada).
PESOS_HORA: list[float] = [
    0.4, 0.3, 0.3, 0.3, 0.4, 0.6,   # 0-5h
    0.8, 1.2, 2.0, 2.0, 2.0, 2.0,   # 6-11h
    1.4, 1.2, 1.2, 1.2, 1.3, 1.6,   # 12-17h
    2.0, 2.0, 2.0, 2.0, 1.2, 0.7,   # 18-23h
]


@dataclass
class Bairro:
    nome: str
    zona: str
    lat: float
    lon: float
    populacao: int
    fator_demanda: float = 1.0  # multiplicador sobre a populacao (ex.: Centro, populacao flutuante)

    @property
    def peso(self) -> float:
        return self.populacao * self.fator_demanda


def carregar_bairros(caminho: str | Path) -> list[Bairro]:
    with open(caminho, encoding="utf-8", newline="") as f:
        return [Bairro(r["bairro"], r["zona"], float(r["lat"]), float(r["lon"]), int(r["populacao"]),
                       float(r.get("fator_demanda") or 1.0))
                for r in csv.DictReader(f)]


def carregar_bases(caminho: str | Path) -> list[Base]:
    with open(caminho, encoding="utf-8", newline="") as f:
        return [Base(r["id"], r["nome"], float(r["lat"]), float(r["lon"]))
                for r in csv.DictReader(f)]


class GeradorChamados:
    def __init__(self, bairros: list[Bairro], seed: int,
                 chamados_por_dia: int = 300, raio_km: float = 1.5):
        self._bairros = bairros
        self._pesos_bairro = [b.peso for b in bairros]
        self._seed = seed
        self._n = chamados_por_dia
        self._raio = raio_km

    def gerar_dia(self, dia: int = 0) -> list[Chamado]:
        rng = random.Random(f"{self._seed}-{dia}")
        chamados: list[Chamado] = []
        for _ in range(self._n):
            b = rng.choices(self._bairros, weights=self._pesos_bairro, k=1)[0]
            hora = rng.choices(range(24), weights=PESOS_HORA, k=1)[0]
            ts = dia * SEGUNDOS_DIA + hora * 3600 + rng.uniform(0, 3600)
            lat, lon = deslocar(b.lat, b.lon, rng.uniform(0, self._raio), rng.uniform(0, 360))
            chamados.append(Chamado(id="", lat=lat, lon=lon, bairro=b.nome, zona=b.zona, criado_em=ts))
        chamados.sort(key=lambda c: c.criado_em)
        for n, c in enumerate(chamados):
            c.id = f"ch-{dia:02d}-{n:05d}"
        return chamados

"""Geracao sintetica de demanda: bairro proporcional a populacao, hora com picos."""
import csv
import random
from dataclasses import dataclass
from pathlib import Path

from samu_sim.core.geo import deslocar
from samu_sim.core.modelos import Base, Chamado

SEGUNDOS_DIA = 86400

# Volume real de emergencia do SAMU-RJ (capital): 216 mil atendimentos em 2024, dos quais ~34-40 mil
# sao transferencias entre hospitais, feitas por outra frota (44 ambulancias de transporte). Sem elas,
# ~176-182 mil/ano = ~490/dia para as 73 ambulancias de emergencia. Fontes em docs/calibracao.md.
CHAMADOS_POR_DIA_RIO = 490

# Peso relativo de cada hora do dia. Calibrado pela literatura de SAMU (analise de configuracao
# do SAMU de Ribeirao Preto, SciELO): dois picos, por volta de 12 h e de 20 h, e vale de madrugada.
PESOS_HORA: list[float] = [
    0.55, 0.40, 0.35, 0.30, 0.30, 0.40,   # 0-5h   vale
    0.60, 0.90, 1.20, 1.45, 1.65, 1.85,   # 6-11h  subida da manha
    2.00, 1.85, 1.70, 1.65, 1.70, 1.85,   # 12-17h pico do meio-dia e tarde
    1.95, 2.00, 2.05, 1.85, 1.45, 0.95,   # 18-23h pico da noite
]

# Gravidade (classificacao do medico regulador) e tipo do chamado. Literatura SAMU: envios de
# suporte avancado (vermelho) sao minoria; ~48-60 % clinicos e ~33 % trauma; trauma sobe a noite.
PROB_PRIORIDADE = {"vermelho": 0.10, "amarelo": 0.30, "verde": 0.60}
PROB_TRAUMA_DIA = 0.30
PROB_TRAUMA_NOITE = 0.48  # 22h-4h: acidentes de transito, violencia
HORAS_NOITE = {22, 23, 0, 1, 2, 3, 4}


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
        return [Base(r["id"], r["nome"], float(r["lat"]), float(r["lon"]), r.get("tipo") or "base")
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
            prioridade = rng.choices(list(PROB_PRIORIDADE), weights=list(PROB_PRIORIDADE.values()), k=1)[0]
            p_trauma = PROB_TRAUMA_NOITE if hora in HORAS_NOITE else PROB_TRAUMA_DIA
            tipo = "trauma" if rng.random() < p_trauma else "clinico"
            chamados.append(Chamado(id="", lat=lat, lon=lon, bairro=b.nome, zona=b.zona, criado_em=ts,
                                    prioridade=prioridade, tipo=tipo))
        chamados.sort(key=lambda c: c.criado_em)
        for n, c in enumerate(chamados):
            c.id = f"ch-{dia:02d}-{n:05d}"
        return chamados

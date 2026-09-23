"""Previsao de demanda por zona x hora e reposicionamento de ambulancias livres.

ModeloDemanda e treinado apenas com eventos `chamado_criado` (o que um sistema real teria no
seu log): conta chamados por (zona, hora), suaviza pelas horas vizinhas e normaliza por dia.
Com dados sinteticos ele aprende a curva do proprio gerador - o valor demonstravel e o
pipeline (event log -> modelo -> decisao -> medicao), que com a serie real do SAMU
aprenderia os padroes reais.

Reposicionador: ao liberar, a ambulancia vai para a base onde a demanda prevista das
proximas horas e maior em relacao a cobertura atual, em vez de voltar a base de origem.
"""
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from samu_sim.core.geo import haversine_km
from samu_sim.core.modelos import ZONAS, Base, StatusAmbulancia
from samu_sim.gerador.demanda import Bairro

RAIO_REPOSICIONAMENTO_KM = 8.0
GANHO_MINIMO = 1.5  # so muda de base se a pressao la for >= 1.5x a da base atual
HORAS_PREVISAO = 2


@dataclass
class ModeloDemanda:
    """taxa[zona][hora] = chamados esperados por hora (media por dia observado)."""
    taxa: dict[str, list[float]] = field(default_factory=dict)
    dias: float = 0.0

    @classmethod
    def treinar(cls, eventos: list[dict], suavizacao: float = 0.5) -> "ModeloDemanda":
        contagem: dict[str, Counter] = defaultdict(Counter)
        ts = [e["ts_sim"] for e in eventos if e.get("tipo") == "chamado_criado"]
        if not ts:
            return cls({z: [0.0] * 24 for z in ZONAS}, 0.0)
        dias = max(1.0, (max(ts) - min(ts)) / 86400)
        for e in eventos:
            if e.get("tipo") != "chamado_criado":
                continue
            hora = int((e["ts_sim"] % 86400) // 3600)
            contagem[e.get("zona", "?")][hora] += 1
        taxa = {}
        for z in ZONAS:
            bruto = [contagem[z][h] / dias for h in range(24)]
            # suavizacao: media ponderada com as horas vizinhas + Laplace
            taxa[z] = [(bruto[h] + suavizacao * (bruto[(h - 1) % 24] + bruto[(h + 1) % 24]) + 0.05)
                       / (1 + 2 * suavizacao) for h in range(24)]
        return cls(taxa, dias)

    def prever(self, zona: str, agora_sim: float, horas: int = HORAS_PREVISAO) -> float:
        """Chamados esperados na zona nas proximas `horas` a partir de agora_sim."""
        h0 = int((agora_sim % 86400) // 3600)
        return sum(self.taxa.get(zona, [0.0] * 24)[(h0 + k) % 24] for k in range(horas))

    def salvar(self, caminho) -> None:
        Path(caminho).write_text(json.dumps({"dias": self.dias, "taxa": self.taxa}, indent=1), encoding="utf-8")

    @classmethod
    def carregar(cls, caminho) -> "ModeloDemanda":
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
        return cls(d["taxa"], d["dias"])


def zona_da_base(base: Base, bairros: list[Bairro]) -> str:
    return min(bairros, key=lambda b: haversine_km(base.lat, base.lon, b.lat, b.lon)).zona


class Reposicionador:
    def __init__(self, modelo: ModeloDemanda, bases: dict[str, Base], bairros: list[Bairro], repo,
                 raio_km: float = RAIO_REPOSICIONAMENTO_KM):
        self._modelo = modelo
        self._bases = bases
        self._repo = repo
        self._raio = raio_km
        self._zona = {b.id: zona_da_base(b, bairros) for b in bases.values()}

    def escolher_base(self, posicao: tuple[float, float], agora_sim: float, base_atual: str) -> tuple[Base, dict]:
        """Base alvo = maior (demanda prevista da zona) / (livres na zona + 1), entre as bases a ate
        raio_km; empate pela distancia. Devolve (base, explicacao)."""
        livres = Counter(self._zona[a.base_id] for a in self._repo.listar_ambulancias(StatusAmbulancia.DISPONIVEL)
                         if a.base_id in self._zona)
        candidatas = []
        for b in self._bases.values():
            d = haversine_km(posicao[0], posicao[1], b.lat, b.lon)
            if d > self._raio and b.id != base_atual:
                continue
            z = self._zona[b.id]
            pressao = self._modelo.prever(z, agora_sim) / (livres.get(z, 0) + 1)
            candidatas.append((-pressao, d, b))
        candidatas.sort(key=lambda x: (x[0], x[1]))
        melhor = candidatas[0][2]
        # so vale a viagem se a pressao no alvo for claramente maior que na base de origem
        za = self._zona.get(base_atual)
        pressao_atual = self._modelo.prever(za, agora_sim) / (livres.get(za, 0) + 1) if za else 0.0
        if base_atual in self._bases and -candidatas[0][0] < GANHO_MINIMO * pressao_atual:
            melhor = self._bases[base_atual]
        return melhor, {"zona": self._zona[melhor.id], "pressao": -candidatas[0][0],
                        "prevista_2h": self._modelo.prever(self._zona[melhor.id], agora_sim),
                        "livres_na_zona": livres.get(self._zona[melhor.id], 0)}

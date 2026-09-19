"""Roteador: tempo estimado de viagem (segundos simulados) entre dois pontos.

Tres implementacoes, mesma interface:
- haversine: linha reta a velocidade media (sem dependencias; subestima no Rio)
- osrm:      malha viaria real via HTTP, com timeout e fallback para haversine
- matriz:    lookup base x bairro pre-computado pelo OSRM (roda sem OSRM, ex.: AWS)
"""
import json
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

from samu_sim.core.geo import haversine_km

Ponto = tuple[float, float]  # (lat, lon)


class Roteador(Protocol):
    nome: str

    def eta(self, origem: Ponto, destino: Ponto) -> float: ...

    def etas_de(self, origens: list[Ponto], destino: Ponto) -> list[float]:
        """ETA de varias origens ao mesmo destino (o despachante avalia N candidatas)."""
        ...


def _etas_em_loop(r: Roteador, origens: list[Ponto], destino: Ponto) -> list[float]:
    return [r.eta(o, destino) for o in origens]


class RoteadorHaversine:
    nome = "haversine"

    def __init__(self, vel_kmh: float = 30.0):
        self._vel_kmh = vel_kmh

    def eta(self, origem: Ponto, destino: Ponto) -> float:
        km = haversine_km(origem[0], origem[1], destino[0], destino[1])
        return km / self._vel_kmh * 3600.0

    def etas_de(self, origens: list[Ponto], destino: Ponto) -> list[float]:
        return _etas_em_loop(self, origens, destino)


def _http_get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


class RoteadorOSRM:
    """GET /route/v1/driving/lon,lat;lon,lat. Nunca levanta: falha -> fallback."""
    nome = "osrm"

    def __init__(self, url: str, fallback: Roteador, timeout_seg: float = 2.0,
                 http_get: Callable[[str, float], dict] | None = None,
                 ao_falhar: Callable[[str], None] | None = None):
        self._url = url.rstrip("/")
        self._fallback = fallback
        self._timeout = timeout_seg
        self._http_get = http_get or _http_get_json
        self._ao_falhar = ao_falhar
        self.fallbacks = 0

    def eta(self, origem: Ponto, destino: Ponto) -> float:
        url = (f"{self._url}/route/v1/driving/{origem[1]},{origem[0]};{destino[1]},{destino[0]}"
               f"?overview=false")
        try:
            r = self._http_get(url, self._timeout)
            if r.get("code") != "Ok":
                raise RuntimeError(f"osrm code={r.get('code')}")
            return float(r["routes"][0]["duration"])
        except Exception as e:  # noqa: BLE001 - qualquer falha vira fallback
            self.fallbacks += 1
            if self._ao_falhar:
                self._ao_falhar(repr(e))
            return self._fallback.eta(origem, destino)

    def etas_de(self, origens: list[Ponto], destino: Ponto) -> list[float]:
        """Uma unica requisicao /table (N origens x 1 destino): ~6x mais rapido que N /route.
        Sem isso, a fator alto a latencia HTTP domina o tempo simulado (medido: 40 routes =
        210 ms = 17 min sim a fator 5000; 1 table = 34 ms)."""
        if not origens:
            return []
        coords = ";".join(f"{o[1]},{o[0]}" for o in origens) + f";{destino[1]},{destino[0]}"
        n = len(origens)
        url = (f"{self._url}/table/v1/driving/{coords}?sources={';'.join(map(str, range(n)))}"
               f"&destinations={n}&annotations=duration")
        try:
            r = self._http_get(url, self._timeout)
            if r.get("code") != "Ok":
                raise RuntimeError(f"osrm code={r.get('code')}")
            linhas = r["durations"]
        except Exception as e:  # noqa: BLE001
            self.fallbacks += 1
            if self._ao_falhar:
                self._ao_falhar(repr(e))
            return self._fallback.etas_de(origens, destino)
        etas = []
        for o, linha in zip(origens, linhas):
            d = linha[0] if linha else None
            if d is None:  # ponto sem rota (ilha, fora do mapa): fallback so para ele
                self.fallbacks += 1
                etas.append(self._fallback.eta(o, destino))
            else:
                etas.append(float(d))
        return etas


class RoteadorMatriz:
    """Lookup em matriz pre-computada (bases x centroides de bairro). Pontos fora do
    raio conhecido caem no fallback. Soma o trecho de aproximacao ate o ponto conhecido."""
    nome = "matriz"

    def __init__(self, caminho, fallback: Roteador, raio_km: float | None = None,
                 ao_falhar: Callable[[str], None] | None = None):
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        self._pontos: dict[str, tuple[float, float]] = {k: (v[0], v[1]) for k, v in dados["pontos"].items()}
        self._eta: dict[str, dict[str, float]] = dados["eta"]
        self._raio = raio_km if raio_km is not None else float(dados.get("raio_km", 1.5))
        self._fallback = fallback
        self._ao_falhar = ao_falhar
        self.fallbacks = 0

    def _mais_proximo(self, p: Ponto) -> tuple[str, float]:
        return min(((n, haversine_km(p[0], p[1], q[0], q[1])) for n, q in self._pontos.items()),
                   key=lambda x: x[1])

    def eta(self, origem: Ponto, destino: Ponto) -> float:
        po, do_ = self._mais_proximo(origem)
        pd, dd = self._mais_proximo(destino)
        valor = self._eta.get(po, {}).get(pd)
        if valor is None or do_ > self._raio or dd > self._raio:
            self.fallbacks += 1
            if self._ao_falhar:
                self._ao_falhar(f"fora da matriz: {po}@{do_:.1f}km -> {pd}@{dd:.1f}km")
            return self._fallback.eta(origem, destino)
        aproximacao = 0.0
        if do_ > 0:
            aproximacao += self._fallback.eta(origem, self._pontos[po])
        if dd > 0:
            aproximacao += self._fallback.eta(self._pontos[pd], destino)
        return float(valor) + aproximacao

    def etas_de(self, origens: list[Ponto], destino: Ponto) -> list[float]:
        return _etas_em_loop(self, origens, destino)


def criar_roteador(nome: str, cfg=None, ao_falhar: Callable[[str], None] | None = None) -> Roteador:
    from samu_sim.core.config import Config  # import tardio: config nao depende de roteador
    cfg = cfg or Config()
    if nome == "haversine":
        return RoteadorHaversine()
    if nome == "osrm":
        return RoteadorOSRM(cfg.osrm_url, RoteadorHaversine(), cfg.osrm_timeout_seg, ao_falhar=ao_falhar)
    if nome == "matriz":
        return RoteadorMatriz(cfg.matriz_path, RoteadorHaversine(), ao_falhar=ao_falhar)
    raise ValueError(f"roteador desconhecido: {nome}")

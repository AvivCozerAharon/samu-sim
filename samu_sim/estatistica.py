"""Intervalos de confianca por bootstrap (Python puro, deterministico por seed).

Bootstrap percentil sobre a media: reamostra os valores com reposicao n_reamostras vezes e
toma os percentis (1-nivel)/2 e 1-(1-nivel)/2 das medias. Com poucos valores (seeds) o IC e
largo - e isso e informacao, nao defeito.

`diferenca_pareada` compara dois cenarios rodados com AS MESMAS seeds (common random numbers):
a diferenca por seed cancela a variancia comum ao gerador de chamados, entao o IC fica bem mais
estreito do que comparar duas medias independentes.
"""
import random
import statistics


def _limpar(valores) -> list[float]:
    return [float(v) for v in valores if v is not None]


def ic_bootstrap(valores, nivel: float = 0.95, n_reamostras: int = 2000, seed: int = 0) -> dict:
    v = _limpar(valores)
    if not v:
        return {"media": None, "baixo": None, "alto": None, "n": 0}
    if len(v) == 1:
        return {"media": v[0], "baixo": v[0], "alto": v[0], "n": 1}
    rng = random.Random(seed)
    n = len(v)
    medias = sorted(statistics.fmean(rng.choices(v, k=n)) for _ in range(n_reamostras))
    alfa = (1 - nivel) / 2
    return {"media": statistics.fmean(v), "baixo": medias[int(alfa * n_reamostras)],
            "alto": medias[min(n_reamostras - 1, int((1 - alfa) * n_reamostras))], "n": n}


def diferenca_pareada(a, b, nivel: float = 0.95, n_reamostras: int = 2000, seed: int = 0) -> dict:
    """IC de (b - a) pareado por posicao (mesma seed). Pares com None sao descartados."""
    if len(a) != len(b):
        raise ValueError(f"listas de tamanhos diferentes: {len(a)} e {len(b)}")
    difs = [float(y) - float(x) for x, y in zip(a, b) if x is not None and y is not None]
    r = ic_bootstrap(difs, nivel, n_reamostras, seed)
    r["significativo"] = bool(r["n"] >= 2 and (r["alto"] < 0 or r["baixo"] > 0))
    return r

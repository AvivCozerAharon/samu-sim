"""Roda a mesma rodada (mesma seed) com cada roteador e imprime P50/P90 lado a lado.
Uso: python scripts/comparar_roteadores.py --fator 5000 --duracao-sim 21600 --roteadores haversine,osrm,matriz"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.core.config import Config  # noqa: E402
from samu_sim.local import rodar  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--roteadores", default="haversine,osrm,matriz")
    p.add_argument("--fator", type=float, default=5000)
    p.add_argument("--duracao-sim", type=float, default=6 * 3600)
    p.add_argument("--ambulancias", type=int, default=40)
    p.add_argument("--chamados-por-dia", type=int, default=600)
    p.add_argument("--politica", default="menor_eta")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--osrm-url", default="http://localhost:5000")
    p.add_argument("--matriz", default="dados/matriz_eta.json")
    a = p.parse_args()
    cfg = Config(osrm_url=a.osrm_url, matriz_path=a.matriz)
    linhas = []
    for nome in a.roteadores.split(","):
        r = rodar(a.fator, a.duracao_sim, a.ambulancias, a.politica, nome, a.seed,
                  a.chamados_por_dia, visibilidade_seg=0.2, cfg=cfg)
        m = r["metricas"]
        linhas.append((nome, m["total"], m["atendidos"], m["resposta"]["p50"], m["resposta"]["p90"],
                       {z: v["p90"] for z, v in m["por_zona"].items()}, r.get("roteador_fallbacks", 0)))
    print(f"{'roteador':10s} {'total':>5s} {'atend':>5s} {'P50':>8s} {'P90':>8s}  P90 por zona (min)")
    for nome, t, at, p50, p90, zonas, fb in linhas:
        z = "  ".join(f"{k}={v / 60:.0f}" for k, v in sorted(zonas.items()) if v is not None)
        print(f"{nome:10s} {t:5d} {at:5d} {p50 / 60:7.1f}m {p90 / 60:7.1f}m  {z}  fallbacks={fb}")


if __name__ == "__main__":
    main()

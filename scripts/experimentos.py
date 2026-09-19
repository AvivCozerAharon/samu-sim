"""Experimentos A (politicas de despacho) e B (tamanho da frota), em memoria, roteador matriz.
Uso: python scripts/experimentos.py [--rapido] [--saida docs/experimentos/resultados.json]"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim import local as runner  # noqa: E402
from samu_sim.core.config import Config  # noqa: E402

SEEDS = [42, 7, 2024]
ZONAS = ["Centro", "Sul", "Norte", "Barra", "Oeste"]
POLITICAS = ["mais_proxima", "menor_eta", "menor_eta_cobertura"]
FROTAS = [20, 30, 40, 50, 65, 80]


def rodar(politica, n_amb, seed, duracao, fator, chamados_por_dia):
    r = runner.rodar(fator=fator, duracao_sim_seg=duracao, n_ambulancias=n_amb, politica=politica,
                     roteador="matriz", seed=seed, chamados_por_dia=chamados_por_dia,
                     visibilidade_seg=0.2, cfg=Config())
    m = r["metricas"]
    return {
        "total": m["total"], "atendidos": m["atendidos"], "pendentes": m["pendentes"],
        "p50": m["resposta"]["p50"], "p90": m["resposta"]["p90"], "media": m["resposta"]["media"],
        "por_zona": {z: (m["por_zona"].get(z) or {}).get("p90") for z in ZONAS},
        "espera_p90": m["espera_despacho"]["p90"],
        "reserva_falhou": r["eventos"].get("reserva_falhou", 0),
        "fallbacks": r.get("roteador_fallbacks", 0),
    }


def resumo(rodadas: list[dict]) -> dict:
    def agg(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return {"media": None, "dp": None}
        return {"media": statistics.fmean(vals), "dp": statistics.pstdev(vals) if len(vals) > 1 else 0.0}
    return {
        "p50": agg([r["p50"] for r in rodadas]), "p90": agg([r["p90"] for r in rodadas]),
        "por_zona": {z: agg([r["por_zona"][z] for r in rodadas]) for z in ZONAS},
        "atendidos": sum(r["atendidos"] for r in rodadas), "total": sum(r["total"] for r in rodadas),
        "pendentes": sum(r["pendentes"] for r in rodadas),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rapido", action="store_true", help="1 seed, 12 h")
    p.add_argument("--fator", type=float, default=2000)
    p.add_argument("--chamados-por-dia", type=int, default=600)
    p.add_argument("--saida", default="docs/experimentos/resultados.json")
    a = p.parse_args()
    seeds = SEEDS[:1] if a.rapido else SEEDS
    duracao = 12 * 3600 if a.rapido else 24 * 3600
    # sem o sleep ocioso de 20 ms o polling em memoria fica mais fino (a fator 2000, 20 ms = 40 s sim)
    runner.INTERVALO_OCIOSO_REAL = 0.005

    resultados = {"config": {"seeds": seeds, "duracao_sim_seg": duracao, "fator": a.fator,
                             "chamados_por_dia": a.chamados_por_dia, "roteador": "matriz"},
                  "A": {}, "B": {}}
    inicio = time.time()
    for pol in POLITICAS:
        rodadas = [rodar(pol, 50, s, duracao, a.fator, a.chamados_por_dia) for s in seeds]
        resultados["A"][pol] = {"rodadas": rodadas, "resumo": resumo(rodadas)}
        print(f"A {pol:22s} P50 {resultados['A'][pol]['resumo']['p50']['media']/60:5.1f}  "
              f"P90 {resultados['A'][pol]['resumo']['p90']['media']/60:5.1f}  "
              + "  ".join(f"{z}={resultados['A'][pol]['resumo']['por_zona'][z]['media']/60:.0f}" for z in ZONAS
                          if resultados['A'][pol]['resumo']['por_zona'][z]['media'] is not None), flush=True)
    for n in FROTAS:
        rodadas = [rodar("menor_eta", n, s, duracao, a.fator, a.chamados_por_dia) for s in seeds]
        resultados["B"][str(n)] = {"rodadas": rodadas, "resumo": resumo(rodadas)}
        rs = resultados["B"][str(n)]["resumo"]
        print(f"B frota {n:3d}            P50 {rs['p50']['media']/60:5.1f}  P90 {rs['p90']['media']/60:5.1f}  "
              f"atendidos {rs['atendidos']}/{rs['total']}  pendentes {rs['pendentes']}", flush=True)
    resultados["config"]["tempo_real_seg"] = round(time.time() - inicio)
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.saida).write_text(json.dumps(resultados, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"gravado em {a.saida} ({resultados['config']['tempo_real_seg']} s)")


if __name__ == "__main__":
    main()

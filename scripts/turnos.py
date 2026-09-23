"""Turnos que aprendem: roda o otimizador de alocacao por base e grava a trajetoria.
Uso: python scripts/turnos.py --turnos 10 --ambulancias 73
Saida: docs/experimentos/turnos.json (trajetoria) e dados/alocacao.json (melhor alocacao)."""
import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim import local as runner  # noqa: E402
from samu_sim.core.config import Config  # noqa: E402
from samu_sim.gerador.demanda import CHAMADOS_POR_DIA_RIO, carregar_bairros, carregar_bases  # noqa: E402
from samu_sim.local import montar_frota  # noqa: E402
from samu_sim.otimizador import Otimizador  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--turnos", type=int, default=10)
    p.add_argument("--ambulancias", type=int, default=73)
    p.add_argument("--chamados-por-dia", type=int, default=CHAMADOS_POR_DIA_RIO)
    p.add_argument("--politica", default="menor_eta")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--duracao-sim", type=float, default=24 * 3600)
    p.add_argument("--fator", type=float, default=500)  # acima disso o simulador atrasa o relogio (README)
    p.add_argument("--saida", default="docs/experimentos/turnos.json")
    p.add_argument("--alocacao-saida", default="dados/alocacao.json")
    a = p.parse_args()
    runner.INTERVALO_OCIOSO_REAL = 0.005

    bases = carregar_bases("dados/bases.csv")
    bairros = carregar_bairros("dados/bairros.csv")
    bases_por_id = {b.id: b for b in bases}
    inicial = {}
    for amb in montar_frota(bases, a.ambulancias, 2):
        inicial[amb.base_id] = inicial.get(amb.base_id, 0) + 1

    def rodar(alocacao):
        return runner.rodar(fator=a.fator, duracao_sim_seg=a.duracao_sim, n_ambulancias=a.ambulancias,
                            politica=a.politica, roteador="matriz", seed=a.seed,
                            chamados_por_dia=a.chamados_por_dia, visibilidade_seg=0.2, cfg=Config(),
                            alocacao=alocacao)

    inicio = time.time()
    otimizador = Otimizador(rodar, bases_por_id, bairros, inicial)
    for _ in range(a.turnos):
        t = otimizador.turno()
        d = t.diagnostico
        print(f"\n== {t.resumo}")
        print(f"   P90 global {(d['p90_global'] or 0)/60:.1f} min | " +
              " ".join(f"{z}={(v or 0)/60:.0f}" for z, v in d["p90_zona"].items()) +
              f" | vermelhos {(d['p90_prioridade'].get('vermelho') or 0)/60:.1f} min | pendentes {d['pendentes']}")
        for acao in t.acoes:
            print(f"   - {acao}")
        if otimizador._proposta is None and len(otimizador.historico) > 1:
            break

    hist = [asdict(t) for t in otimizador.historico]
    saida = {"config": {"turnos": len(hist), "ambulancias": a.ambulancias, "chamados_por_dia": a.chamados_por_dia,
                        "politica": a.politica, "seed": a.seed, "duracao_sim_seg": a.duracao_sim,
                        "tempo_real_seg": round(time.time() - inicio)},
             "alocacao_inicial": inicial, "alocacao_final": otimizador.alocacao,
             "J_inicial": hist[0]["J"], "J_final": otimizador._melhor_J, "turnos": hist}
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.saida).write_text(json.dumps(saida, indent=1, ensure_ascii=False), encoding="utf-8")
    Path(a.alocacao_saida).write_text(json.dumps(otimizador.alocacao, indent=1), encoding="utf-8")
    print(f"\nJ: {hist[0]['J']:.1f} -> {otimizador._melhor_J:.1f} em {len(hist)} turnos; "
          f"gravado em {a.saida} e {a.alocacao_saida} ({saida['config']['tempo_real_seg']} s)")


if __name__ == "__main__":
    main()

"""Compara dois cenarios com as mesmas seeds e imprime a diferenca pareada com IC 95 %.

Uso:
  python scripts/cenarios.py --base '{"nome":"73"}' --alt '{"nome":"80","n_ambulancias":80}'
  python scripts/cenarios.py --base '{"nome":"73"}' --alt '{"nome":"73+transito","transito":true}' --seeds 42 7 2024
Campos do cenario: nome, n_ambulancias, politica, alocacao, bases_extra, transito, reposicionamento."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim import local as runner  # noqa: E402
from samu_sim.cenarios import METRICAS, Cenario, comparar, executar  # noqa: E402
from samu_sim.core.modelos import ZONAS  # noqa: E402
from samu_sim.gerador.demanda import CHAMADOS_POR_DIA_RIO  # noqa: E402

MINUTOS = {"p90", "p50", "p90_vermelho", *ZONAS}


def fmt(ic: dict, chave: str) -> str:
    if ic.get("media") is None:
        return "   —"
    esc = 60 if chave in MINUTOS else 1
    return f"{ic['media'] / esc:6.1f} [{ic['baixo'] / esc:5.1f}, {ic['alto'] / esc:5.1f}]"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True, help="JSON do cenario base")
    p.add_argument("--alt", required=True, help="JSON do cenario alternativo")
    p.add_argument("--seeds", type=int, nargs="+", default=[42, 7, 2024])
    p.add_argument("--duracao-sim", type=float, default=86400)
    p.add_argument("--fator", type=float, default=500)  # acima disso o simulador atrasa o relogio (README)
    p.add_argument("--chamados-por-dia", type=int, default=CHAMADOS_POR_DIA_RIO)
    p.add_argument("--saida", default=None, help="grava os dois resultados + comparacao em JSON")
    a = p.parse_args()
    runner.INTERVALO_OCIOSO_REAL = 0.005
    base, alt = Cenario.de_dict(json.loads(a.base)), Cenario.de_dict(json.loads(a.alt))
    print(f"rodando {len(a.seeds)} seeds x {a.duracao_sim / 3600:.0f} h para cada cenario...", flush=True)
    rb = executar(base, a.seeds, a.duracao_sim, a.fator, runner.rodar, a.chamados_por_dia)
    ra = executar(alt, a.seeds, a.duracao_sim, a.fator, runner.rodar, a.chamados_por_dia)
    dif = comparar(rb, ra)
    print(f"\n{'métrica':13s} {base.nome[:22]:>22s} {alt.nome[:22]:>22s} {'diferença (alt − base)':>24s}")
    for k in METRICAS:
        d = dif[k]
        marca = " ✓" if d["significativo"] else "  "
        print(f"{k:13s} {fmt(rb['resumo'][k], k):>22s} {fmt(ra['resumo'][k], k):>22s} {fmt(d, k):>22s}{marca}")
    print("\nminutos (pendentes em chamados); IC 95 % por bootstrap; ✓ = IC da diferença pareada não contém 0")
    if a.saida:
        Path(a.saida).write_text(json.dumps({"base": rb, "alt": ra, "diferenca": dif}, indent=1, ensure_ascii=False),
                                 encoding="utf-8")
        print(f"gravado em {a.saida}")


if __name__ == "__main__":
    main()

"""Treina o modelo de demanda zona x hora a partir de eventos `chamado_criado`.
Uso: python scripts/treinar_demanda.py --logs logs/<rodada>     (event log real de rodadas)
     python scripts/treinar_demanda.py --dias 30                  (gera 30 dias com o gerador e treina)
Saida: dados/demanda_prevista.json"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.gerador.demanda import GeradorChamados, carregar_bairros  # noqa: E402
from samu_sim.previsao import ModeloDemanda  # noqa: E402
from scripts.analisar_rodada import carregar_eventos  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--logs", nargs="*", default=[], help="pastas com JSONL de rodadas")
    p.add_argument("--dias", type=int, default=0, help="alternativa: gerar N dias sinteticos")
    p.add_argument("--chamados-por-dia", type=int, default=600)
    p.add_argument("--seed", type=int, default=99)
    p.add_argument("--saida", default="dados/demanda_prevista.json")
    a = p.parse_args()
    eventos = []
    for pasta in a.logs:
        eventos += carregar_eventos(Path(pasta))
    if a.dias:
        g = GeradorChamados(carregar_bairros("dados/bairros.csv"), a.seed, a.chamados_por_dia)
        for d in range(a.dias):
            eventos += [{"tipo": "chamado_criado", "ts_sim": c.criado_em, "zona": c.zona} for c in g.gerar_dia(d)]
    if not eventos:
        raise SystemExit("nada para treinar: passe --logs ou --dias")
    m = ModeloDemanda.treinar(eventos)
    m.salvar(a.saida)
    n = sum(1 for e in eventos if e.get("tipo") == "chamado_criado")
    print(f"treinado com {n} chamados ({m.dias:.1f} dias); gravado em {a.saida}")
    for z, t in m.taxa.items():
        pico = max(range(24), key=lambda h: t[h])
        print(f"  {z:7s} {sum(t):6.1f}/dia  pico {pico:02d}h ({t[pico]:.1f}/h)  madrugada {t[3]:.1f}/h")


if __name__ == "__main__":
    main()

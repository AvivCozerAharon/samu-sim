"""Gera os graficos dos experimentos a partir de docs/experimentos/resultados.json.
Uso: python scripts/graficos.py [--entrada ...] [--saida docs/img]"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ZONAS = ["Centro", "Sul", "Norte", "Barra", "Oeste"]
CORES = {"mais_proxima": "#8A9BAE", "menor_eta": "#4FC3F7", "menor_eta_cobertura": "#3DDC97"}
ROTULOS = {"mais_proxima": "mais próxima (linha reta)", "menor_eta": "menor ETA (malha viária)",
           "menor_eta_cobertura": "menor ETA + cobertura"}
META_MIN = 15


def estilo():
    plt.rcParams.update({
        "figure.facecolor": "#0F1923", "axes.facecolor": "#0F1923", "savefig.facecolor": "#0F1923",
        "axes.edgecolor": "#3A4B5C", "axes.labelcolor": "#E8EEF4", "xtick.color": "#8A9BAE",
        "ytick.color": "#8A9BAE", "text.color": "#E8EEF4", "font.family": "sans-serif",
        "font.size": 11, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "grid.color": "#23313F", "grid.linewidth": .6, "legend.frameon": False,
    })


def grafico_a(res: dict, saida: Path) -> None:
    pols = list(res["A"])
    fig, ax = plt.subplots(figsize=(9, 4.6))
    larg = 0.8 / len(pols)
    for i, pol in enumerate(pols):
        r = res["A"][pol]["resumo"]["por_zona"]
        xs = [j + i * larg - 0.4 + larg / 2 for j in range(len(ZONAS))]
        ys = [(r[z]["media"] or 0) / 60 for z in ZONAS]
        dps = [(r[z]["dp"] or 0) / 60 for z in ZONAS]
        ax.bar(xs, ys, larg * .92, yerr=dps, capsize=2, color=CORES[pol], label=ROTULOS[pol],
               error_kw={"ecolor": "#E8EEF4", "elinewidth": .8})
    ax.axhline(META_MIN, color="#FFC857", lw=1.2, ls="--")
    ax.text(len(ZONAS) - 0.55, META_MIN + 0.6, "meta 15 min", color="#FFC857", ha="right", fontsize=9)
    ax.set_xticks(range(len(ZONAS)), ZONAS)
    ax.set_ylabel("P90 do tempo de resposta (min)")
    c = res["config"]
    ax.set_title(f"A · política de despacho × zona — {c.get('frota_a', 50)} ambulâncias (frota real), {c['chamados_por_dia']} chamados/dia, "
                 f"{len(c['seeds'])} seed(s)", loc="left", fontsize=11)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(saida / "a_politicas_p90_zona.png", dpi=150)


def grafico_b(res: dict, saida: Path) -> None:
    frotas = sorted(int(k) for k in res["B"])
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for chave, cor, rot in (("p90", "#FF5A5F", "P90"), ("p50", "#4FC3F7", "P50")):
        med = [res["B"][str(n)]["resumo"][chave]["media"] / 60 for n in frotas]
        dp = [(res["B"][str(n)]["resumo"][chave]["dp"] or 0) / 60 for n in frotas]
        ax.plot(frotas, med, marker="o", color=cor, lw=2, label=rot)
        ax.fill_between(frotas, [max(5, m - d) for m, d in zip(med, dp)], [m + d for m, d in zip(med, dp)],
                        color=cor, alpha=.15, lw=0)
    ax.axhline(META_MIN, color="#FFC857", lw=1.2, ls="--")
    ax.text(frotas[-1], META_MIN + 1, "meta 15 min", color="#FFC857", ha="right", fontsize=9)
    for n in frotas:
        rs = res["B"][str(n)]["resumo"]
        if rs["pendentes"]:
            ax.annotate(f"{rs['pendentes']} na fila\nao fim do dia", (n, rs["p90"]["media"] / 60),
                        textcoords="offset points", xytext=(10, 4), fontsize=8, color="#FF8A3D")
    ax.set_xlabel("ambulâncias na frota")
    ax.set_ylabel("tempo de resposta (min, escala log)")
    ax.set_xticks(frotas)
    ax.set_yscale("log")
    ticks = [5, 10, 15, 20, 30, 50, 100, 200, 400]
    ax.set_yticks(ticks, [str(t) for t in ticks])
    ax.set_ylim(5, 600)
    c = res["config"]
    ax.set_title(f"B · tamanho da frota — menor ETA, {c['chamados_por_dia']} chamados/dia, "
                 f"{len(c['seeds'])} seed(s)", loc="left", fontsize=11)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(saida / "b_frota_p90.png", dpi=150)


def grafico_c(turnos: dict, saida: Path) -> None:
    ts = turnos["turnos"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    xs = [t["numero"] for t in ts]
    js = [t["J"] for t in ts]
    cores = ["#4FC3F7" if t["numero"] == 1 else ("#3DDC97" if t["aceito"] else "#4A5A6A") for t in ts]
    ax.bar(xs, js, color=cores, width=.7)
    melhor = []
    m = js[0]
    for t in ts:
        if t["aceito"]:
            m = t["J"]
        melhor.append(m)
    ax.plot(xs, melhor, color="#FFC857", lw=2, marker="o", ms=4, label="melhor J até o turno")
    for t in ts:
        if t["aceito"] and t["numero"] > 1:
            ax.annotate("aceito", (t["numero"], t["J"]), textcoords="offset points", xytext=(0, 4),
                        ha="center", fontsize=8, color="#3DDC97")
    ax.set_xticks(xs)
    ax.set_xlabel("turno")
    ax.set_ylabel("J = 3·P90 vermelho + P90 amarelo + ½·P90 verde (min)")
    ax.set_ylim(min(js) * 0.9, max(js) * 1.05)
    c = turnos["config"]
    ax.set_title(f"C · turnos que aprendem — {c['ambulancias']} ambulâncias, {c['chamados_por_dia']} chamados/dia, "
                 f"1 movimento por turno", loc="left", fontsize=11)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(saida / "c_turnos.png", dpi=150)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--entrada", default="docs/experimentos/resultados.json")
    p.add_argument("--saida", default="docs/img")
    a = p.parse_args()
    res = json.loads(Path(a.entrada).read_text(encoding="utf-8"))
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    estilo()
    grafico_a(res, saida)
    grafico_b(res, saida)
    turnos = Path(a.entrada).parent / "turnos.json"
    if turnos.exists():
        grafico_c(json.loads(turnos.read_text(encoding="utf-8")), saida)
    print(f"graficos em {saida}/")


if __name__ == "__main__":
    main()

"""Experimento D: onde abrir a proxima base do SAMU.

Dois estagios: triagem barata (1 seed, 12 h) de todas as candidatas para escolher as finalistas,
e comparacao pareada por seed com IC (N seeds, 24 h) das finalistas contra o baseline (frota
atual) e contra um controle (as mesmas `extra` ambulancias numa base que ja existe).

Uso: python scripts/experimento_d.py [--rapido] [--extra 2] [--seeds-final 5] [--transito] [--reposicionamento]
Saida: docs/experimentos/expansao.json"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim import local as runner  # noqa: E402
from samu_sim.cenarios import Cenario, comparar  # noqa: E402
from samu_sim.core.modelos import ZONAS  # noqa: E402
from samu_sim.cenarios import executar as executar_cenario  # noqa: E402
from samu_sim.expansao import candidatas, cenario_candidata  # noqa: E402
from samu_sim.gerador.demanda import carregar_bairros, carregar_bases  # noqa: E402
from samu_sim.otimizador import demanda_coberta  # noqa: E402

SEEDS = [42, 7, 2024, 11, 99, 5, 23, 77, 31, 8]


def _pior_zona(resumo: dict) -> float:
    return max((resumo[z]["media"] or 0) for z in ZONAS)


def executar(rodar_fn, bairros, bases, alocacao_base, seeds_triagem, seeds_final, duracao_triagem,
             duracao_final, fator, extra=2, max_candidatas=12, n_finalistas=4, flags=None, log=print) -> dict:
    flags = flags or {}
    n_base = sum(alocacao_base.values())
    baseline = Cenario(f"atual ({n_base})", n_ambulancias=n_base, alocacao=alocacao_base, **flags)
    # controle: as mesmas `extra` ambulancias na base existente mais pressionada (demanda / ambulancias)
    mais_carregada = max(bases, key=lambda b: demanda_coberta(b, bairros) / (alocacao_base.get(b.id, 0) + 1))
    aloc_ctrl = dict(alocacao_base)
    aloc_ctrl[mais_carregada.id] = aloc_ctrl.get(mais_carregada.id, 0) + extra
    controle = Cenario(f"+{extra} em {mais_carregada.nome}", n_ambulancias=n_base + extra, alocacao=aloc_ctrl, **flags)
    cands = candidatas(bairros, bases, max_n=max_candidatas)

    def rodar(c, seeds, dur):
        return executar_cenario(c, seeds, dur, fator, rodar_fn)

    log(f"triagem: {len(cands)} candidatas, {len(seeds_triagem)} seed(s), {duracao_triagem / 3600:.0f} h")
    base_tri = rodar(baseline, seeds_triagem, duracao_triagem)
    triagem = []
    for c in cands:
        r = rodar(cenario_candidata(c, alocacao_base, extra, **flags), seeds_triagem, duracao_triagem)
        ganho = r["resumo"]["p90"]["media"] - base_tri["resumo"]["p90"]["media"]
        triagem.append({"cand": c, "p90": r["resumo"]["p90"]["media"], "ganho_seg": ganho,
                        "pior_zona": _pior_zona(r["resumo"]), "por_zona": {z: r["resumo"][z]["media"] for z in ZONAS}})
        log(f"  {c['bairro']:25s} P90 {r['resumo']['p90']['media'] / 60:5.1f} min  ganho {ganho / 60:+5.1f} min")
    triagem.sort(key=lambda t: (t["p90"], t["pior_zona"]))
    finalistas_c = [t["cand"] for t in triagem[:n_finalistas]]

    log(f"final: baseline, controle e {len(finalistas_c)} finalistas, {len(seeds_final)} seeds, {duracao_final / 3600:.0f} h")
    base_fin = rodar(baseline, seeds_final, duracao_final)
    ctrl_fin = rodar(controle, seeds_final, duracao_final)
    d = comparar(base_fin, ctrl_fin)["p90"]
    log(f"  {controle.nome:25s} P90 {ctrl_fin['resumo']['p90']['media'] / 60:5.1f}  vs atual {d['media'] / 60:+5.1f} "
        f"[{d['baixo'] / 60:+.1f}, {d['alto'] / 60:+.1f}] {'sig' if d['significativo'] else 'n.s.'}")
    finalistas = []
    for c in finalistas_c:
        r = rodar(cenario_candidata(c, alocacao_base, extra, **flags), seeds_final, duracao_final)
        finalistas.append({"cand": c, "resultado": r, "vs_baseline": comparar(base_fin, r),
                           "vs_controle": comparar(ctrl_fin, r)})
        d = finalistas[-1]["vs_baseline"]["p90"]
        log(f"  {c['bairro']:25s} P90 {r['resumo']['p90']['media'] / 60:5.1f}  vs atual {d['media'] / 60:+5.1f} "
            f"[{d['baixo'] / 60:+.1f}, {d['alto'] / 60:+.1f}] {'sig' if d['significativo'] else 'n.s.'}")
    finalistas.sort(key=lambda f: f["vs_baseline"]["p90"]["media"])
    return {"config": {"extra": extra, "seeds_triagem": seeds_triagem, "seeds_final": seeds_final,
                       "duracao_triagem": duracao_triagem, "duracao_final": duracao_final, "fator": fator,
                       "flags": flags, "n_base": n_base, "controle_base": mais_carregada.nome},
            "baseline": base_fin, "controle": ctrl_fin, "vs_controle": comparar(base_fin, ctrl_fin),
            "triagem": triagem, "finalistas": finalistas}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rapido", action="store_true", help="triagem 6 h, final 2 seeds x 12 h")
    p.add_argument("--extra", type=int, default=2, help="ambulancias na base nova")
    p.add_argument("--seeds-final", type=int, default=None)
    p.add_argument("--fator", type=float, default=500)  # acima disso o simulador atrasa o relogio (README)
    p.add_argument("--transito", action="store_true")
    p.add_argument("--reposicionamento", action="store_true")
    p.add_argument("--alocacao", default="dados/alocacao.json")
    p.add_argument("--saida", default="docs/experimentos/expansao.json")
    a = p.parse_args()
    runner.INTERVALO_OCIOSO_REAL = 0.005
    if a.rapido:
        cfg = dict(seeds_triagem=[42], seeds_final=[42, 7], duracao_triagem=6 * 3600, duracao_final=12 * 3600,
                   max_candidatas=6, n_finalistas=2)
    else:
        cfg = dict(seeds_triagem=[42], seeds_final=SEEDS[:a.seeds_final or 5], duracao_triagem=12 * 3600,
                   duracao_final=24 * 3600, max_candidatas=12, n_finalistas=4)
    alocacao = {k: int(v) for k, v in json.loads(Path(a.alocacao).read_text(encoding="utf-8")).items()}
    inicio = time.time()
    res = executar(runner.rodar, carregar_bairros("dados/bairros.csv"), carregar_bases("dados/bases.csv"), alocacao,
                   fator=a.fator, extra=a.extra,
                   flags={"transito": a.transito, "reposicionamento": a.reposicionamento}, **cfg)
    res["config"]["tempo_real_seg"] = round(time.time() - inicio)
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.saida).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"gravado em {a.saida} ({res['config']['tempo_real_seg']} s)")


if __name__ == "__main__":
    main()

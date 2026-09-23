"""Roda N rodadas sob caos e verifica as invariantes de cada uma.
Uso: python scripts/caos.py --rodadas 20 [--saida docs/experimentos/caos.json]"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.caos import rodar  # noqa: E402
from samu_sim.infra.fila_caotica import Caos  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rodadas", type=int, default=20)
    p.add_argument("--seed-inicial", type=int, default=1)
    p.add_argument("--duracao-sim", type=float, default=12 * 3600)
    p.add_argument("--fator", type=float, default=2000)
    p.add_argument("--despachantes", type=int, default=2)
    p.add_argument("--saida", default=None)
    a = p.parse_args()
    rodadas, falhas, recup, viol = [], Counter(), Counter(), Counter()
    for s in range(a.seed_inicial, a.seed_inicial + a.rodadas):
        r = rodar(seed=s, caos=Caos(), fator=a.fator, duracao_sim_seg=a.duracao_sim, n_despachantes=a.despachantes)
        rodadas.append(r)
        falhas.update(r["falhas_injetadas"])
        recup.update({k: v for k, v in r["recuperacoes"].items() if v})
        viol.update(r["por_invariante"])
        marca = "ok" if r["ok"] else f"{len(r['violacoes'])} violacao(oes) {r['por_invariante']}"
        print(f"seed {s:3d}  {r['chamados']:4d} chamados  {r['tempo_real_seg']:5.0f}s  {marca}", flush=True)
        for v in r["violacoes"][:3]:
            print(f"          {v['invariante']}: {v['detalhe']}", flush=True)
    ok = sum(r["ok"] for r in rodadas)
    print(f"\n{ok}/{len(rodadas)} rodadas sem violacao")
    print("falhas injetadas:", dict(falhas))
    print("recuperacoes:", dict(recup))
    if viol:
        print("violacoes por invariante:", dict(viol))
    if a.saida:
        Path(a.saida).write_text(json.dumps({"config": vars(a), "rodadas": rodadas, "falhas": dict(falhas),
                                             "recuperacoes": dict(recup), "violacoes": dict(viol)},
                                            ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

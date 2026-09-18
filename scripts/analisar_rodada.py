"""Metricas de uma rodada a partir do event log JSONL.
Uso: python scripts/analisar_rodada.py logs/local [--json]"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.core.metricas import percentil  # noqa: E402


def carregar_eventos(pasta: Path) -> list[dict]:
    eventos = []
    for arquivo in sorted(Path(pasta).glob("*.jsonl")):
        with open(arquivo, encoding="utf-8") as f:
            eventos.extend(json.loads(linha) for linha in f if linha.strip())
    eventos.sort(key=lambda e: e["ts_sim"])
    return eventos


def _resumo(v):
    return {"p50": percentil(v, 50), "p90": percentil(v, 90),
            "media": sum(v) / len(v) if v else None, "n": len(v)}


def analisar(eventos: list[dict]) -> dict:
    contagens = Counter(e["tipo"] for e in eventos)
    respostas, esperas = [], []
    por_zona = defaultdict(list)
    despachos = Counter()
    redespachados = set()  # chamados devolvidos a fila pelo reaper: 2o despacho e legitimo
    for e in eventos:
        t = e["tipo"]
        if t == "reaper_liberou" and e.get("chamado_id"):
            redespachados.add(e["chamado_id"])
        if t == "chegou":
            respostas.append(e["resposta_seg"])
            por_zona[e.get("zona", "?")].append(e["resposta_seg"])
        elif t == "despachada":
            esperas.append(e["espera_seg"])
            despachos[e["chamado_id"]] += 1
    return {
        "resposta": _resumo(respostas),
        "por_zona": {z: {k: v for k, v in _resumo(vs).items() if k != "media"}
                     for z, vs in sorted(por_zona.items())},
        "espera_despacho": {"p50": percentil(esperas, 50), "p90": percentil(esperas, 90)},
        "contagens": dict(contagens),
        "despachos_duplicados": sorted(c for c, n in despachos.items()
                                       if n > 1 and c not in redespachados),
        "redespachados_pelo_reaper": sorted(redespachados),
        "chamados_criados": contagens.get("chamado_criado", 0),
        "chamados_atendidos": contagens.get("chegou", 0),
    }


def _min(s):
    return "     -    " if s is None else f"{s / 60:6.1f} min"


def imprimir(r: dict) -> None:
    print(f"chamados criados: {r['chamados_criados']}   atendidos: {r['chamados_atendidos']}")
    print(f"resposta         P50 {_min(r['resposta']['p50'])}   P90 {_min(r['resposta']['p90'])}   n={r['resposta']['n']}")
    print(f"espera despacho  P50 {_min(r['espera_despacho']['p50'])}   P90 {_min(r['espera_despacho']['p90'])}")
    print("por zona:")
    for z, m in r["por_zona"].items():
        print(f"  {z:8s} P50 {_min(m['p50'])}  P90 {_min(m['p90'])}  n={m['n']}")
    print("eventos:", ", ".join(f"{k}={v}" for k, v in sorted(r["contagens"].items())))
    if r["redespachados_pelo_reaper"]:
        print("redespachados pelo reaper:", len(r["redespachados_pelo_reaper"]))
    if r["despachos_duplicados"]:
        print("ATENCAO despachos duplicados:", r["despachos_duplicados"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("pasta", help="pasta com os JSONL da rodada, ex.: logs/local")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    r = analisar(carregar_eventos(Path(a.pasta)))
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        imprimir(r)


if __name__ == "__main__":
    main()

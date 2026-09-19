"""Gera dados/matriz_eta.json (bases x centroides de bairro) com o servico table do OSRM.
Uso: python scripts/gerar_matriz_osrm.py --url http://localhost:5000"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.gerador.demanda import carregar_bairros, carregar_bases  # noqa: E402
from samu_sim.roteador import _http_get_json  # noqa: E402


def montar_pontos(bases, bairros) -> dict[str, tuple[float, float]]:
    pontos = {b.id: (b.lat, b.lon) for b in bases}
    pontos.update({b.nome: (b.lat, b.lon) for b in bairros})
    return pontos


def consultar_tabela(url: str, pontos: dict, http_get=None, timeout: float = 60.0) -> dict:
    http_get = http_get or _http_get_json
    nomes = list(pontos)
    coords = ";".join(f"{pontos[n][1]},{pontos[n][0]}" for n in nomes)
    r = http_get(f"{url.rstrip('/')}/table/v1/driving/{coords}?annotations=duration", timeout)
    if r.get("code") != "Ok":
        raise RuntimeError(f"osrm table falhou: {r}")
    matriz: dict[str, dict[str, float]] = {}
    for i, a in enumerate(nomes):
        matriz[a] = {}
        for j, b in enumerate(nomes):
            d = r["durations"][i][j]
            if d is not None:
                matriz[a][b] = float(d)
    return matriz


def gerar(url: str, bases_csv, bairros_csv, saida, raio_km: float = 1.5, http_get=None) -> dict:
    pontos = montar_pontos(carregar_bases(bases_csv), carregar_bairros(bairros_csv))
    dados = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "osrm", "raio_km": raio_km,
        "pontos": {k: [v[0], v[1]] for k, v in pontos.items()},
        "eta": consultar_tabela(url, pontos, http_get),
    }
    Path(saida).write_text(json.dumps(dados, indent=1, ensure_ascii=False), encoding="utf-8")
    return dados


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:5000")
    p.add_argument("--bases", default="dados/bases.csv")
    p.add_argument("--bairros", default="dados/bairros.csv")
    p.add_argument("--saida", default="dados/matriz_eta.json")
    p.add_argument("--raio-km", type=float, default=1.5)
    a = p.parse_args()
    d = gerar(a.url, a.bases, a.bairros, a.saida, a.raio_km)
    n = len(d["pontos"])
    print(f"matriz {n}x{n} gravada em {a.saida}")


if __name__ == "__main__":
    main()

"""Gera dados/bairros.csv a partir do Censo 2022 por bairro (Data.Rio / IPP, servico ArcGIS
da prefeitura). Fonte bruta em dados/fontes/censo2022_bairros_geo.json (baixada uma vez de
https://pgeo3.rio.rj.gov.br/arcgis/rest/services/Censo/Limites_administrativos_Censo_2022/MapServer/2).
Uso: python scripts/preparar_dados.py"""
import csv
import json
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Regiao administrativa (RA) -> zona usada pelo simulador (agrupamento por Area de Planejamento;
# os rotulos com a AP ficam em samu_sim.core.modelos.ROTULO_ZONA)
ZONA_POR_RA = {
    "CENTRO": "Centro", "PORTUARIA": "Centro", "RIO COMPRIDO": "Centro", "SANTA TEREZA": "Centro",
    "SAO CRISTOVAO": "Centro", "PAQUETA": "Centro",
    "BOTAFOGO": "Sul", "COPACABANA": "Sul", "LAGOA": "Sul", "ROCINHA": "Sul",
    "TIJUCA": "Norte", "VILA ISABEL": "Norte", "RAMOS": "Norte", "PENHA": "Norte", "INHAUMA": "Norte",
    "MEIER": "Norte", "IRAJA": "Norte", "MADUREIRA": "Norte", "ILHA DO GOVERNADOR": "Norte",
    "ANCHIETA": "Norte", "PAVUNA": "Norte", "JACAREZINHO": "Norte", "COMPLEXO DO ALEMAO": "Norte",
    "COMPLEXO DA MARE": "Norte", "VIGARIO GERAL": "Norte",
    "BARRA DA TIJUCA": "Barra", "JACAREPAGUA": "Barra", "CIDADE DE DEUS": "Barra",
    "BANGU": "Oeste", "CAMPO GRANDE": "Oeste", "SANTA CRUZ": "Oeste", "GUARATIBA": "Oeste", "REALENGO": "Oeste",
}

# Fator multiplicativo sobre a populacao residente para a demanda de chamados.
# Centro: populacao flutuante (trabalho, comercio, populacao de rua) - calibrado para o Centro
# entrar no top 3 de chamados (~3,5 % dos envios), como no dado real do SAMU-RJ 2024 (Campo Grande, Santa Cruz, Centro).
# Paqueta: ilha sem acesso rodoviario - fora do modelo.
FATOR_DEMANDA = {"Centro": 9.5, "Paqueta": 0.0}


def sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def centroide(rings: list[list[list[float]]]) -> tuple[float, float]:
    """Centroide (lat, lon) do maior anel do poligono (shoelace)."""
    melhor = None
    for r in rings:
        a = cx = cy = 0.0
        for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
            cr = x1 * y2 - x2 * y1
            a += cr
            cx += (x1 + x2) * cr
            cy += (y1 + y2) * cr
        if a == 0:
            continue
        area = abs(a) / 2
        if melhor is None or area > melhor[0]:
            melhor = (area, cy / (3 * a), cx / (3 * a))
    return melhor[1], melhor[2]


def preparar(entrada: Path, saida: Path) -> list[dict]:
    dados = json.loads(entrada.read_text(encoding="utf-8"))
    linhas = []
    for f in dados["features"]:
        a = f["attributes"]
        nome = sem_acento(a["nome"]).strip()
        ra = sem_acento(a["regiao_adm"]).strip().upper()
        if ra not in ZONA_POR_RA:
            raise SystemExit(f"RA sem zona mapeada: {ra}")
        lat, lon = centroide(f["geometry"]["rings"])
        linhas.append({
            "bairro": nome, "zona": ZONA_POR_RA[ra], "regiao_adm": ra.title(),
            "lat": round(lat, 5), "lon": round(lon, 5),
            "populacao": int(a["Total_de_pessoas_2022"] or 0),
            "populacao_2010": int(a["Total_de_pessoas_2010"] or 0),
            "fator_demanda": FATOR_DEMANDA.get(nome, 1.0),
        })
    linhas.sort(key=lambda r: r["bairro"])
    with open(saida, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)
    return linhas


def main() -> None:
    linhas = preparar(RAIZ / "dados/fontes/censo2022_bairros_geo.json", RAIZ / "dados/bairros.csv")
    pop = sum(r["populacao"] for r in linhas)
    peso = sorted(linhas, key=lambda r: -r["populacao"] * r["fator_demanda"])
    print(f"{len(linhas)} bairros, populacao 2022 = {pop:,}".replace(",", "."))
    print("top 5 demanda:", ", ".join(f"{r['bairro']} ({100*r['populacao']*r['fator_demanda']/sum(x['populacao']*x['fator_demanda'] for x in linhas):.1f}%)" for r in peso[:5]))


if __name__ == "__main__":
    sys.exit(main())

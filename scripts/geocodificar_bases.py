"""Gera dados/bases.csv com os hospitais municipais de emergencia e as UPAs do municipio do Rio.
Fontes: SMS-Rio (saude.prefeitura.rio/urgencia-e-emergencia/{hospitais,upas}). Geocodificacao
pelo Nominatim (OpenStreetMap), 1 req/s, cache em dados/fontes/geocode.json; fallback para o
centroide do bairro (dados/bairros.csv). Uso: python scripts/geocodificar_bases.py"""
import csv
import json
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / "dados/fontes/geocode.json"
BBOX = (-23.10, -22.74, -43.80, -43.09)  # lat_min, lat_max, lon_min, lon_max (municipio)
UA = "samu-sim/1.0 (simulador academico; github.com/AvivCozerAharon/samu-sim)"

# (nome, endereco ou None, bairro, tipo)
UNIDADES = [
    ("Hospital Municipal Souza Aguiar", "Praca da Republica, 111", "Centro", "hospital"),
    ("Hospital Municipal Salgado Filho", "Rua Arquias Cordeiro, 370", "Meier", "hospital"),
    ("Hospital Municipal Miguel Couto", "Rua Mario Ribeiro, 117", "Leblon", "hospital"),
    ("Hospital Municipal Lourenco Jorge", "Avenida Ayrton Senna, 2000", "Barra da Tijuca", "hospital"),
    ("Hospital Municipal Pedro II", "Rua do Prado, 325", "Santa Cruz", "hospital"),
    ("Hospital Municipal Evandro Freire", "Estrada do Galeao, 2920", "Galeao", "hospital"),
    ("Hospital Municipal Albert Schweitzer", "Rua Nilopolis, 239", "Realengo", "hospital"),
    ("Hospital Municipal Rocha Faria", "Avenida Cesario de Melo, 3215", "Campo Grande", "hospital"),
    ("Hospital Municipal Rocha Maia", "Rua General Severiano, 91", "Botafogo", "hospital"),
    ("Hospital Municipal Francisco da Silva Telles", "Avenida Ubirajara, 25", "Iraja", "hospital"),
    ("Hospital Cardoso Fontes", "Avenida Menezes Cortes, 3245", "Jacarepagua", "hospital"),
    ("Hospital do Andarai", "Rua Leopoldo, 280", "Andarai", "hospital"),
    ("UPA Rocinha", "Estrada da Gavea, 520", "Rocinha", "upa"),
    ("UPA Alemao", "Estrada Itarare, 951", "Ramos", "upa"),
    ("UPA Manguinhos", "Avenida Dom Helder Camara, 1390", "Manguinhos", "upa"),
    ("UPA Del Castilho", "Rua Lago Verde", "Inhauma", "upa"),
    ("UPA Engenho de Dentro", "Rua Bernardo", "Engenho de Dentro", "upa"),
    ("UPA Madureira", "Praca dos Lavradores", "Campinho", "upa"),
    ("UPA Costa Barros", "Estrada Botafogo", "Costa Barros", "upa"),
    ("UPA Rocha Miranda", "Estrada do Barro Vermelho", "Rocha Miranda", "upa"),
    ("UPA Cidade de Deus", "Rua Edgar Werneck", "Cidade de Deus", "upa"),
    ("UPA Vila Kennedy", "Praca Dolomitas", "Vila Kennedy", "upa"),
    ("UPA Senador Camara", "Avenida Santa Cruz, 6486", "Senador Camara", "upa"),
    ("UPA Magalhaes Bastos", "Estrada Manoel Nogueira de Sa", "Magalhaes Bastos", "upa"),
    ("UPA Sepetiba", "Rua Jose Fernandes", "Sepetiba", "upa"),
    ("UPA Joao XXIII", "Avenida Joao XXIII", "Santa Cruz", "upa"),
    ("UPA Paciencia", "Estrada Santa Eugenia", "Paciencia", "upa"),
    ("UPA Bangu", None, "Bangu", "upa"),
    ("UPA Botafogo", None, "Botafogo", "upa"),
    ("UPA Campo Grande I", None, "Campo Grande", "upa"),
    ("UPA Campo Grande II", None, "Cosmos", "upa"),
    ("UPA Copacabana", None, "Copacabana", "upa"),
    ("UPA Engenho Novo", None, "Engenho Novo", "upa"),
    ("UPA Ilha do Governador", None, "Portuguesa", "upa"),
    ("UPA Iraja", None, "Iraja", "upa"),
    ("UPA Jacarepagua", None, "Taquara", "upa"),
    ("UPA Mare", None, "Mare", "upa"),
    ("UPA Marechal Hermes", None, "Marechal Hermes", "upa"),
    ("UPA Penha", None, "Penha", "upa"),
    ("UPA Realengo", None, "Realengo", "upa"),
    ("UPA Ricardo de Albuquerque", None, "Ricardo de Albuquerque", "upa"),
    ("UPA Santa Cruz", None, "Santa Cruz", "upa"),
    ("UPA Tijuca", None, "Tijuca", "upa"),
]


def sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def dentro(lat: float, lon: float) -> bool:
    return BBOX[0] < lat < BBOX[1] and BBOX[2] < lon < BBOX[3]


def nominatim(consulta: str) -> tuple[float, float] | None:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": consulta, "format": "json", "limit": 1, "countrycodes": "br"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR"})
    with urllib.request.urlopen(req, timeout=20) as r:
        dados = json.load(r)
    if not dados:
        return None
    return float(dados[0]["lat"]), float(dados[0]["lon"])


def geocodificar(cache: dict, consulta: str) -> tuple[float, float] | None:
    if consulta in cache:
        v = cache[consulta]
        return tuple(v) if v else None
    time.sleep(1.1)  # politica de uso do Nominatim: 1 req/s
    try:
        r = nominatim(consulta)
    except Exception as e:  # noqa: BLE001
        print(f"  falha: {consulta}: {e!r}")
        r = None
    cache[consulta] = list(r) if r else None
    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return r


def main() -> None:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    centroides = {}
    with open(RAIZ / "dados/bairros.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            centroides[sem_acento(r["bairro"]).lower()] = (float(r["lat"]), float(r["lon"]), r["zona"])
    linhas = []
    for i, (nome, endereco, bairro, tipo) in enumerate(UNIDADES, 1):
        # sem endereco, o Nominatim "chuta" pelo nome (colisoes vistas: Bangu=Vila Kennedy,
        # Mare=Manguinhos): nesse caso vai direto para o centroide do bairro
        consultas = [f"{endereco}, {bairro}, Rio de Janeiro, RJ"] if endereco else []
        ponto, origem = None, "centroide"
        for c in consultas:
            p = geocodificar(cache, c)
            if p and dentro(*p):
                ponto, origem = p, "nominatim"
                break
        if ponto is None:
            cb = centroides.get(sem_acento(bairro).lower())
            if cb is None:
                print(f"  sem centroide para {bairro}; pulando {nome}")
                continue
            ponto = (cb[0], cb[1])
        linhas.append({"id": f"base-{i:02d}", "nome": nome, "lat": round(ponto[0], 5), "lon": round(ponto[1], 5),
                       "tipo": tipo, "bairro": bairro, "origem": origem})
        print(f"{linhas[-1]['id']} {nome:45s} {origem:10s} {ponto[0]:.4f},{ponto[1]:.4f}")
    with open(RAIZ / "dados/bases.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)
    print(f"{len(linhas)} bases gravadas ({sum(1 for r in linhas if r['origem']=='nominatim')} geocodificadas)")


if __name__ == "__main__":
    sys.exit(main())

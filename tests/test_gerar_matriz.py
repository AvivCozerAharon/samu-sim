import json
from scripts.gerar_matriz_osrm import consultar_tabela, gerar


def test_consultar_tabela_mapeia_durations():
    pontos = {"b1": (-22.9, -43.2), "X": (-22.95, -43.25)}
    chamadas = []

    def http_get(url, timeout):
        chamadas.append(url)
        return {"code": "Ok", "durations": [[0, 500.0], [520.0, 0]]}

    m = consultar_tabela("http://osrm", pontos, http_get)
    assert m["b1"]["X"] == 500.0 and m["X"]["b1"] == 520.0 and m["b1"]["b1"] == 0
    assert chamadas[0].startswith("http://osrm/table/v1/driving/-43.2,-22.9;-43.25,-22.95?")


def test_gerar_escreve_json_no_formato_do_roteador(tmp_path):
    bases = tmp_path / "bases.csv"
    bases.write_text("id,nome,lat,lon\nb1,B,-22.9,-43.2\n", encoding="utf-8")
    bairros = tmp_path / "bairros.csv"
    bairros.write_text("bairro,zona,lat,lon,populacao\nX,Sul,-22.95,-43.25,10\n", encoding="utf-8")
    saida = tmp_path / "m.json"
    gerar("http://osrm", bases, bairros, saida,
          http_get=lambda u, t: {"code": "Ok", "durations": [[0, 500.0], [520.0, 0]]})
    m = json.loads(saida.read_text(encoding="utf-8"))
    assert m["pontos"]["b1"] == [-22.9, -43.2] and m["eta"]["b1"]["X"] == 500.0 and m["fonte"] == "osrm"
    from samu_sim.roteador import RoteadorHaversine, RoteadorMatriz
    assert RoteadorMatriz(saida, RoteadorHaversine()).eta((-22.9, -43.2), (-22.95, -43.25)) == 500.0

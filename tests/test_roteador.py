import pytest
from samu_sim.roteador import RoteadorHaversine, criar_roteador

COPACABANA = (-22.9711, -43.1822)
CENTRO = (-22.9068, -43.1829)


def test_eta_a_30kmh():
    r = RoteadorHaversine(vel_kmh=30)
    # ~7.15 km a 30 km/h = ~858 s
    assert r.eta(COPACABANA, CENTRO) == pytest.approx(858, abs=30)


def test_eta_mesmo_ponto_zero():
    assert RoteadorHaversine().eta(CENTRO, CENTRO) == 0.0


def test_criar_roteador():
    assert criar_roteador("haversine").nome == "haversine"
    with pytest.raises(ValueError):
        criar_roteador("teletransporte")


# ---------- OSRM ----------
from samu_sim.core.config import Config  # noqa: E402
from samu_sim.roteador import RoteadorOSRM  # noqa: E402


def test_osrm_usa_duration_da_resposta():
    urls = []

    def http_get(url, timeout):
        urls.append(url)
        return {"code": "Ok", "routes": [{"duration": 1234.5, "distance": 9000}]}

    r = RoteadorOSRM("http://osrm:5000", RoteadorHaversine(), http_get=http_get)
    assert r.eta(COPACABANA, CENTRO) == 1234.5
    assert urls[0] == "http://osrm:5000/route/v1/driving/-43.1822,-22.9711;-43.1829,-22.9068?overview=false"
    assert r.fallbacks == 0


def test_osrm_cai_para_fallback_em_erro_e_conta():
    motivos = []

    def http_get(url, timeout):
        raise TimeoutError("lento")

    r = RoteadorOSRM("http://osrm:5000", RoteadorHaversine(vel_kmh=30), timeout_seg=0.1,
                     http_get=http_get, ao_falhar=motivos.append)
    assert r.eta(COPACABANA, CENTRO) == pytest.approx(858, abs=30)
    assert r.fallbacks == 1 and "lento" in motivos[0]


def test_osrm_code_nao_ok_tambem_e_fallback():
    r = RoteadorOSRM("http://x", RoteadorHaversine(), http_get=lambda u, t: {"code": "NoRoute"})
    assert r.eta(CENTRO, CENTRO) == 0.0 and r.fallbacks == 1


def test_criar_roteador_osrm_com_config():
    r = criar_roteador("osrm", Config(osrm_url="http://osrm:5000"))
    assert r.nome == "osrm"


# ---------- matriz ----------
import json  # noqa: E402
from samu_sim.roteador import RoteadorMatriz  # noqa: E402


def matriz_tmp(tmp_path):
    m = {"gerado_em": "x", "fonte": "teste", "raio_km": 1.5,
         "pontos": {"base-01": list(CENTRO), "Copacabana": list(COPACABANA)},
         "eta": {"base-01": {"Copacabana": 1000.0}, "Copacabana": {"base-01": 1100.0}}}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def test_matriz_usa_lookup_quando_perto_dos_pontos(tmp_path):
    r = RoteadorMatriz(matriz_tmp(tmp_path), RoteadorHaversine())
    assert r.eta(CENTRO, COPACABANA) == 1000.0
    assert r.eta(COPACABANA, CENTRO) == 1100.0
    perto = (COPACABANA[0] + 0.004, COPACABANA[1])  # ~450 m do centroide
    e = r.eta(CENTRO, perto)
    assert 1000.0 < e < 1000.0 + 120
    assert r.fallbacks == 0


def test_matriz_cai_para_fallback_longe_dos_pontos(tmp_path):
    motivos = []
    r = RoteadorMatriz(matriz_tmp(tmp_path), RoteadorHaversine(vel_kmh=30), ao_falhar=motivos.append)
    longe = (-23.0, -43.6)
    assert r.eta(CENTRO, longe) == pytest.approx(RoteadorHaversine(30).eta(CENTRO, longe))
    assert r.fallbacks == 1 and "fora da matriz" in motivos[0]


def test_criar_roteador_matriz(tmp_path):
    r = criar_roteador("matriz", Config(matriz_path=str(matriz_tmp(tmp_path))))
    assert r.nome == "matriz"


# ---------- lote ----------
def test_etas_de_em_lote_no_osrm_usa_table():
    urls = []

    def http_get(url, timeout):
        urls.append(url)
        return {"code": "Ok", "durations": [[100.0], [200.0], [None]]}

    r = RoteadorOSRM("http://osrm:5000", RoteadorHaversine(vel_kmh=30), http_get=http_get)
    origens = [CENTRO, COPACABANA, (-23.0, -43.6)]
    etas = r.etas_de(origens, CENTRO)
    assert etas[0] == 100.0 and etas[1] == 200.0
    assert etas[2] == pytest.approx(RoteadorHaversine(30).eta(origens[2], CENTRO))  # null -> fallback
    assert len(urls) == 1 and "/table/v1/driving/" in urls[0] and "destinations=3" in urls[0]


def test_etas_de_padrao_faz_loop():
    r = RoteadorHaversine()
    assert r.etas_de([CENTRO, COPACABANA], CENTRO) == [0.0, r.eta(COPACABANA, CENTRO)]
    assert r.etas_de([], CENTRO) == []


# ---------- transito (D8) ----------
from samu_sim.roteador import FATORES_TRANSITO, RoteadorComTransito  # noqa: E402


def test_transito_multiplica_pelo_fator_da_hora():
    hora = {"t": 3 * 3600}
    r = RoteadorComTransito(RoteadorHaversine(vel_kmh=30), lambda: hora["t"])
    livre = RoteadorHaversine(30).eta(COPACABANA, CENTRO)
    assert r.eta(COPACABANA, CENTRO) == pytest.approx(livre * FATORES_TRANSITO[3])
    hora["t"] = 18 * 3600 + 120
    assert r.eta(COPACABANA, CENTRO) == pytest.approx(livre * 1.55)
    assert r.etas_de([COPACABANA, CENTRO], CENTRO) == pytest.approx([livre * 1.55, 0.0])
    assert r.nome == "haversine+transito" and r.fallbacks == 0


def test_criar_roteador_liga_transito_pela_config():
    from samu_sim.core.relogio import Relogio
    rel = Relogio(fator=1, inicio_sim=18 * 3600)
    assert criar_roteador("haversine", Config(transito=True), relogio=rel).nome == "haversine+transito"
    assert criar_roteador("haversine", Config(transito=False), relogio=rel).nome == "haversine"
    assert criar_roteador("haversine", Config(transito=True)).nome == "haversine"  # sem relogio, nao envolve

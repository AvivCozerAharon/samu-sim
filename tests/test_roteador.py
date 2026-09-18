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

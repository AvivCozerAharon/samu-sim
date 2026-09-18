import pytest
from samu_sim.core.geo import haversine_km, deslocar

COPACABANA = (-22.9711, -43.1822)
CENTRO = (-22.9068, -43.1829)


def test_haversine_copacabana_centro_aprox_7km():
    d = haversine_km(*COPACABANA, *CENTRO)
    assert d == pytest.approx(7.15, abs=0.2)


def test_haversine_mesmo_ponto_zero():
    assert haversine_km(*CENTRO, *CENTRO) == 0.0


def test_deslocar_volta_distancia_pedida():
    lat, lon = deslocar(*CENTRO, dist_km=2.0, rumo_graus=90)
    assert haversine_km(*CENTRO, lat, lon) == pytest.approx(2.0, abs=0.01)
    assert lon > CENTRO[1]  # rumo 90 = leste

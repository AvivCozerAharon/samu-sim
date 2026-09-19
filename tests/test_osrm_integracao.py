"""Exige OSRM: bash scripts/preparar_osrm.sh && docker compose --profile osrm up -d osrm"""
import os
import urllib.request

import pytest

from samu_sim.roteador import RoteadorHaversine, RoteadorOSRM

pytestmark = pytest.mark.integration
CENTRO = (-22.9083, -43.1868)
SANTA_CRUZ = (-22.9186, -43.6845)


@pytest.fixture(scope="module")
def url():
    u = os.environ.get("OSRM_URL", "http://localhost:5000")
    try:
        urllib.request.urlopen(f"{u}/route/v1/driving/-43.18,-22.90;-43.19,-22.91", timeout=3)
    except Exception:
        pytest.skip("OSRM nao esta acessivel")
    return u


def test_osrm_real_responde_sem_fallback(url):
    r = RoteadorOSRM(url, RoteadorHaversine())
    osrm = r.eta(CENTRO, SANTA_CRUZ)
    reta = RoteadorHaversine().eta(CENTRO, SANTA_CRUZ)
    assert r.fallbacks == 0 and osrm > 0
    assert 0.3 * reta < osrm < 3 * reta  # mesma ordem de grandeza da reta a 30 km/h

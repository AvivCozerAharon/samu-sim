import math

RAIO_TERRA_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAIO_TERRA_KM * math.asin(math.sqrt(a))


def deslocar(lat: float, lon: float, dist_km: float, rumo_graus: float) -> tuple[float, float]:
    """Ponto a dist_km de (lat, lon) na direcao rumo_graus (0 = norte, 90 = leste)."""
    d = dist_km / RAIO_TERRA_KM
    rumo = math.radians(rumo_graus)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(rumo))
    l2 = l1 + math.atan2(
        math.sin(rumo) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), math.degrees(l2)

import pytest
from samu_sim.core.modelos import Ambulancia, Chamado
from samu_sim.politicas import MaisProxima, MenorEta, criar_politica
from samu_sim.roteador import RoteadorHaversine


def amb(id, lat, lon):
    return Ambulancia(id=id, base_id="b", lat=lat, lon=lon, worker_id="w1")


CHAMADO = Chamado(id="ch", lat=-22.90, lon=-43.20, bairro="X", zona="Centro", criado_em=0)
LONGE = amb("longe", -23.00, -43.50)
PERTO = amb("perto", -22.91, -43.21)
MEDIA = amb("media", -22.95, -43.25)


def test_mais_proxima_ordena_por_distancia():
    ordem = MaisProxima().escolher(CHAMADO, [LONGE, PERTO, MEDIA], RoteadorHaversine())
    assert [a.id for a in ordem] == ["perto", "media", "longe"]


def test_menor_eta_usa_roteador():
    class RoteadorInvertido:
        nome = "invertido"

        def eta(self, o, d):
            # quanto mais longe, menor o "eta" -> inverte a ordem de proposito
            return -RoteadorHaversine().eta(o, d)

    ordem = MenorEta().escolher(CHAMADO, [LONGE, PERTO, MEDIA], RoteadorInvertido())
    assert [a.id for a in ordem] == ["longe", "media", "perto"]


def test_lista_vazia():
    assert MaisProxima().escolher(CHAMADO, [], RoteadorHaversine()) == []


def test_criar_politica():
    assert criar_politica("mais_proxima").nome == "mais_proxima"
    assert criar_politica("menor_eta").nome == "menor_eta"
    with pytest.raises(ValueError):
        criar_politica("aleatoria")

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


# ---------- cobertura ----------
from samu_sim.politicas import MenorEtaCobertura  # noqa: E402


def test_cobertura_penaliza_ultima_da_base():
    a1 = amb("a1", -22.905, -43.205)
    a1.base_id = "A"
    a2 = amb("a2", -22.905, -43.205)
    a2.base_id = "A"
    b1 = amb("b1", -22.92, -43.22)
    b1.base_id = "B"  # unica da base B
    ordem = MenorEtaCobertura(penalidade_seg=600).escolher(CHAMADO, [b1, a1, a2], RoteadorHaversine())
    assert [a.id for a in ordem][:2] == ["a1", "a2"]
    assert ordem[-1].id == "b1"


def test_cobertura_sem_penalidade_quando_todas_sao_ultimas():
    a1 = amb("a1", -22.905, -43.205)
    a1.base_id = "A"
    b1 = amb("b1", -22.95, -43.25)
    b1.base_id = "B"
    ordem = MenorEtaCobertura().escolher(CHAMADO, [b1, a1], RoteadorHaversine())
    assert [a.id for a in ordem] == ["a1", "b1"]


def test_criar_politica_cobertura():
    assert criar_politica("menor_eta_cobertura").nome == "menor_eta_cobertura"

import pytest
from samu_sim.core.metricas import calcular, percentil
from samu_sim.core.modelos import Chamado, StatusChamado as SC


def ch(i, zona, criado, chegada=None, despachado=None):
    c = Chamado(id=f"ch-{i}", lat=0, lon=0, bairro="B", zona=zona, criado_em=criado)
    if despachado is not None:
        c.despachado_em = despachado
        c.status = SC.DESPACHADO
    if chegada is not None:
        c.chegada_em = chegada
        c.status = SC.ATENDIDO
    return c


def test_percentil():
    assert percentil([], 50) is None
    assert percentil([10], 90) == 10
    assert percentil([1, 2, 3, 4, 5], 50) == 3
    assert percentil([1, 2, 3, 4, 5], 90) == pytest.approx(4.6)


def test_calcular():
    chamados = [
        ch(1, "Sul", 0, chegada=300, despachado=10),
        ch(2, "Sul", 0, chegada=600, despachado=20),
        ch(3, "Oeste", 0, chegada=1500, despachado=30),
        ch(4, "Oeste", 0, despachado=40),   # despachado, ainda nao chegou
        ch(5, "Norte", 0),                  # pendente
    ]
    m = calcular(chamados)
    assert m["total"] == 5 and m["atendidos"] == 3 and m["despachados"] == 1 and m["pendentes"] == 1
    assert m["resposta"]["n"] == 3 and m["resposta"]["p50"] == 600
    assert m["resposta"]["media"] == pytest.approx(800)
    assert m["por_zona"]["Sul"]["p50"] == 450 and m["por_zona"]["Oeste"]["n"] == 1
    assert m["espera_despacho"]["p50"] == 25


def test_metricas_por_prioridade():
    c1 = ch(1, "Sul", 0, chegada=300, despachado=10)
    c1.prioridade = "vermelho"
    c2 = ch(2, "Sul", 0, chegada=900, despachado=20)
    c2.prioridade = "verde"
    m = calcular([c1, c2])
    assert m["por_prioridade"]["vermelho"]["p90"] == 300 and m["por_prioridade"]["verde"]["n"] == 1

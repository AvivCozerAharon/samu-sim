from samu_sim.core.modelos import (
    Ambulancia, Chamado, StatusAmbulancia as SA, StatusChamado as SC, transicao_valida,
)


def test_ambulancia_nasce_disponivel_versao_zero():
    a = Ambulancia(id="amb-1", base_id="base-1", lat=-22.9, lon=-43.2, worker_id="w1")
    assert a.status == SA.DISPONIVEL
    assert a.versao == 0
    assert a.chamado_id is None


def test_chamado_nasce_pendente():
    c = Chamado(id="ch-1", lat=-22.9, lon=-43.2, bairro="Centro", zona="Centro", criado_em=0.0)
    assert c.status == SC.PENDENTE
    assert c.tentativas == 0


def test_transicoes_validas():
    assert transicao_valida(SA.DISPONIVEL, SA.RESERVADA)
    assert transicao_valida(SA.RESERVADA, SA.A_CAMINHO)
    assert transicao_valida(SA.A_CAMINHO, SA.NO_LOCAL)
    assert transicao_valida(SA.NO_LOCAL, SA.RETORNANDO)
    assert transicao_valida(SA.NO_LOCAL, SA.DISPONIVEL)
    assert transicao_valida(SA.RETORNANDO, SA.DISPONIVEL)


def test_transicoes_invalidas():
    assert not transicao_valida(SA.DISPONIVEL, SA.A_CAMINHO)
    assert not transicao_valida(SA.A_CAMINHO, SA.RESERVADA)
    assert not transicao_valida(SA.A_CAMINHO, SA.A_CAMINHO)


def test_status_serializa_como_string():
    assert SA.A_CAMINHO == "a_caminho"
    assert str(SC.ATENDIDO) == "atendido"

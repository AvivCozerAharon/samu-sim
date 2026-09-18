import threading
import pytest
from samu_sim.core.modelos import Ambulancia, Chamado, Rodada, StatusAmbulancia as SA
from samu_sim.infra.repositorio import RepositorioMemoria, ConflitoVersao


def amb(id="amb-1"):
    return Ambulancia(id=id, base_id="b1", lat=-22.9, lon=-43.2, worker_id="w1")


def test_salvar_e_obter_devolve_copia():
    r = RepositorioMemoria()
    a = amb()
    r.salvar_ambulancia(a)
    a.lat = 0.0
    assert r.obter_ambulancia("amb-1").lat == -22.9


def test_listar_por_status():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb("a"))
    b = amb("b")
    b.status = SA.A_CAMINHO
    r.salvar_ambulancia(b)
    assert [x.id for x in r.listar_ambulancias(SA.DISPONIVEL)] == ["a"]
    assert len(r.listar_ambulancias()) == 2


def test_reservar_incrementa_versao_e_marca_chamado():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    a = r.reservar_ambulancia("amb-1", versao=0, chamado_id="ch-1")
    assert a.status == SA.RESERVADA and a.versao == 1 and a.chamado_id == "ch-1"


def test_reservar_com_versao_errada_conflita():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    r.reservar_ambulancia("amb-1", versao=0, chamado_id="ch-1")
    with pytest.raises(ConflitoVersao):
        r.reservar_ambulancia("amb-1", versao=0, chamado_id="ch-2")


def test_transicionar_valida_e_aplica_campos():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    a = r.reservar_ambulancia("amb-1", 0, "ch-1")
    a = r.transicionar("amb-1", SA.RESERVADA, SA.A_CAMINHO, a.versao)
    a = r.transicionar("amb-1", SA.A_CAMINHO, SA.NO_LOCAL, a.versao, lat=-23.0, lon=-43.3)
    assert a.status == SA.NO_LOCAL and a.lat == -23.0 and a.versao == 3


def test_transicionar_estado_errado_conflita():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    with pytest.raises(ConflitoVersao):
        r.transicionar("amb-1", SA.A_CAMINHO, SA.NO_LOCAL, 0)


def test_transicao_invalida_e_rejeitada_mesmo_com_versao_certa():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    with pytest.raises(ConflitoVersao):
        r.transicionar("amb-1", SA.DISPONIVEL, SA.A_CAMINHO, 0)


def test_dois_despachantes_so_um_reserva():
    """Lock otimista: 20 threads disputam a mesma ambulancia com a mesma versao."""
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    sucessos, conflitos = [], []
    barreira = threading.Barrier(20)

    def tenta(i):
        barreira.wait()
        try:
            r.reservar_ambulancia("amb-1", versao=0, chamado_id=f"ch-{i}")
            sucessos.append(i)
        except ConflitoVersao:
            conflitos.append(i)

    ts = [threading.Thread(target=tenta, args=(i,)) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(sucessos) == 1 and len(conflitos) == 19


def test_chamado_e_rodada():
    r = RepositorioMemoria()
    r.salvar_chamado(Chamado(id="ch-1", lat=0, lon=0, bairro="X", zona="Sul", criado_em=0))
    assert r.obter_chamado("ch-1").bairro == "X"
    assert r.obter_chamado("nao-existe") is None
    assert r.obter_rodada() is None
    r.salvar_rodada(Rodada("r1", 1, "mais_proxima", 10, 5, "haversine", 0, 0))
    assert r.obter_rodada().fator == 10

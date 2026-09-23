from samu_sim.api.reaper import Reaper
from samu_sim.core.modelos import Ambulancia, Base, Chamado, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria

BASE = Base("b1", "Base", -22.9, -43.2)


def montar():
    repo, fila = RepositorioMemoria(), FilaMemoria()
    log = EventLogMemoria(Relogio(), "api")
    reaper = Reaper(repo, fila, {"b1": BASE}, log, timeout_seg=120, agora_real=lambda: 1000.0)
    return repo, fila, log, reaper


def amb(id, status, heartbeat, chamado_id=None):
    return Ambulancia(id=id, base_id="b1", lat=0, lon=0, worker_id="w0", status=status,
                      heartbeat_em=heartbeat, chamado_id=chamado_id, versao=3)


def test_libera_travada_e_devolve_chamado_para_fila():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("amb-1", SA.A_CAMINHO, heartbeat=800.0, chamado_id="ch-1"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50,
                                status=SC.DESPACHADO, ambulancia_id="amb-1", despachado_em=60))
    assert reaper.executar_uma_vez() == 1
    a = repo.obter_ambulancia("amb-1")
    # libera onde ela esta (nao teletransporta para a base)
    assert a.status == SA.DISPONIVEL and a.chamado_id is None and (a.lat, a.lon) == (0, 0)
    c = repo.obter_chamado("ch-1")
    assert c.status == SC.PENDENTE and c.ambulancia_id is None and c.tentativas == 1
    msg = fila.receber()[0].corpo
    assert msg["chamado_id"] == "ch-1" and msg["zona"] == "Sul"
    assert log.contar("reaper_liberou") == 1


def test_ignora_saudaveis_e_disponiveis():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("ok", SA.A_CAMINHO, heartbeat=950.0, chamado_id="ch-1"))  # 50 s atras
    repo.salvar_ambulancia(amb("livre", SA.DISPONIVEL, heartbeat=0.0))
    assert reaper.executar_uma_vez() == 0
    assert fila.tamanho() == 0


def test_chamado_ja_atendido_nao_volta_para_fila():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("amb-1", SA.RETORNANDO, heartbeat=100.0, chamado_id="ch-1"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50,
                                status=SC.ATENDIDO, ambulancia_id="amb-1"))
    assert reaper.executar_uma_vez() == 1
    assert fila.tamanho() == 0
    assert repo.obter_chamado("ch-1").status == SC.ATENDIDO


def test_nao_devolve_chamado_ja_redespachado_para_outra_ambulancia():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("amb-1", SA.A_CAMINHO, heartbeat=800.0, chamado_id="ch-1"))
    # o chamado ja foi devolvido antes e redespachado para a amb-2
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50,
                                status=SC.DESPACHADO, ambulancia_id="amb-2", publicado=True))
    assert reaper.executar_uma_vez() == 1  # a amb-1 travada e liberada mesmo assim
    c = repo.obter_chamado("ch-1")
    assert c.status == SC.DESPACHADO and c.ambulancia_id == "amb-2" and c.tentativas == 0
    assert fila.tamanho() == 0


def test_republica_pendente_que_nunca_foi_publicado_na_segunda_passada():
    repo, fila, log, reaper = montar()
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50))
    assert reaper.republicar_nao_publicados() == 0  # 1a passada: so suspeito (gerador pode estar no meio)
    assert fila.tamanho() == 0
    assert reaper.republicar_nao_publicados() == 1  # 2a passada: morreu entre salvar e publicar
    assert fila.receber()[0].corpo["chamado_id"] == "ch-1"
    assert repo.obter_chamado("ch-1").publicado is True
    assert log.contar("chamado_republicado") == 1
    assert reaper.republicar_nao_publicados() == 0


def test_nao_republica_o_que_foi_publicado_entre_as_passadas():
    repo, fila, log, reaper = montar()
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50))
    reaper.republicar_nao_publicados()
    repo.marcar_publicado("ch-1")  # o gerador terminou de publicar
    assert reaper.republicar_nao_publicados() == 0



def test_ambulancia_de_worker_morto_passa_para_um_vivo():
    repo, fila, log, reaper = montar()  # agora_real = 1000, timeout 120
    repo.registrar_worker("w0", 500.0)   # w0 sem sinal ha 500 s: morto
    repo.registrar_worker("w1", 990.0)   # w1 vivo
    repo.salvar_ambulancia(amb("ociosa", SA.DISPONIVEL, heartbeat=0.0))                  # do w0
    repo.salvar_ambulancia(amb("presa", SA.A_CAMINHO, heartbeat=800.0, chamado_id="ch-1"))  # do w0
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50,
                                status=SC.DESPACHADO, ambulancia_id="presa", publicado=True))
    reaper.executar_uma_vez()
    assert repo.obter_ambulancia("ociosa").worker_id == "w1"
    presa = repo.obter_ambulancia("presa")
    assert presa.worker_id == "w1" and presa.status == SA.DISPONIVEL
    assert log.contar("ambulancia_reatribuida") == 1


def test_worker_que_volta_recebe_parte_da_frota_de_volta():
    repo, fila, log, reaper = montar()
    repo.registrar_worker("w0", 995.0)
    repo.registrar_worker("w1", 995.0)
    for i in range(6):  # todas com o w1 depois de o w0 ter caido
        a = amb(f"a{i}", SA.DISPONIVEL, heartbeat=0.0)
        a.worker_id = "w1"
        repo.salvar_ambulancia(a)
    reaper.executar_uma_vez()
    donos = [repo.obter_ambulancia(f"a{i}").worker_id for i in range(6)]
    assert donos.count("w0") == 3 and donos.count("w1") == 3


def test_sem_registro_de_workers_nao_reatribui_nada():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("ociosa", SA.DISPONIVEL, heartbeat=0.0))
    reaper.executar_uma_vez()
    assert repo.obter_ambulancia("ociosa").worker_id == "w0"



def test_ambulancia_a_caminho_e_liberada_onde_estaria_e_nao_no_ponto_de_partida():
    repo, fila = RepositorioMemoria(), FilaMemoria()
    log = EventLogMemoria(Relogio(), "api")
    reaper = Reaper(repo, fila, {"b1": BASE}, log, timeout_seg=120, agora_real=lambda: 1000.0,
                    agora_sim=lambda: 150.0)  # na metade do trajeto (100 -> 200)
    repo.salvar_ambulancia(Ambulancia(id="amb-1", base_id="b1", lat=0.0, lon=0.0, worker_id="w0",
                                      status=SA.A_CAMINHO, heartbeat_em=800.0, chamado_id="ch-1", versao=3))
    repo.salvar_chamado(Chamado(id="ch-1", lat=2.0, lon=4.0, bairro="B", zona="Sul", criado_em=90,
                                status=SC.DESPACHADO, ambulancia_id="amb-1", despachado_em=100.0,
                                chegada_prevista_em=200.0, publicado=True))
    reaper.executar_uma_vez()
    a = repo.obter_ambulancia("amb-1")
    assert (a.lat, a.lon) == (1.0, 2.0)

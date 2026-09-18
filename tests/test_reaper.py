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
    assert a.status == SA.DISPONIVEL and a.chamado_id is None and (a.lat, a.lon) == (BASE.lat, BASE.lon)
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

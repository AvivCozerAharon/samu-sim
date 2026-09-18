from samu_sim.ambulancia.servico import WorkerAmbulancia
from samu_sim.core.modelos import Ambulancia, Base, Chamado, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria
from samu_sim.roteador import RoteadorHaversine

BASE = Base("b1", "Base 1", -22.90, -43.20)


def montar():
    relogio = Relogio(fator=100000)
    repo = RepositorioMemoria()
    repo.salvar_ambulancia(Ambulancia(id="amb-1", base_id="b1", lat=BASE.lat, lon=BASE.lon, worker_id="w1"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=-22.95, lon=-43.25, bairro="X", zona="Sul", criado_em=0))
    fila = FilaMemoria()
    log = EventLogMemoria(relogio, "ambulancia")
    w = WorkerAmbulancia("w1", fila, repo, relogio, RoteadorHaversine(), {"b1": BASE}, log,
                         atendimento_seg=(600, 600))
    return relogio, repo, fila, log, w


def despachar(repo, fila, eta=300.0):
    a = repo.reservar_ambulancia("amb-1", 0, "ch-1")
    c = repo.obter_chamado("ch-1")
    c.status = SC.DESPACHADO
    c.ambulancia_id = "amb-1"
    c.despachado_em = 5.0
    repo.salvar_chamado(c)
    fila.publicar({"tipo": "despachada", "chamado_id": "ch-1", "ambulancia_id": "amb-1", "eta_seg": eta, "ts_sim": 5.0})
    return a


def test_ciclo_completo_volta_disponivel_na_base():
    relogio, repo, fila, log, w = montar()
    despachar(repo, fila)
    assert w.processar_lote() == 1
    w.aguardar_ciclos(timeout=5)
    a = repo.obter_ambulancia("amb-1")
    assert a.status == SA.DISPONIVEL and a.chamado_id is None
    assert (a.lat, a.lon) == (BASE.lat, BASE.lon)
    c = repo.obter_chamado("ch-1")
    assert c.status == SC.ATENDIDO
    assert c.chegada_em is not None and c.liberado_em is not None and c.liberado_em > c.chegada_em
    assert log.contar("chegou") == 1 and log.contar("liberada") == 1
    assert fila.tamanho() == 0


def test_mensagem_duplicada_e_rejeitada_pela_maquina_de_estados():
    relogio, repo, fila, log, w = montar()
    despachar(repo, fila)
    fila.publicar({"tipo": "despachada", "chamado_id": "ch-1", "ambulancia_id": "amb-1", "eta_seg": 300.0, "ts_sim": 5.0})
    assert w.processar_lote() == 2
    w.aguardar_ciclos(timeout=5)
    assert log.contar("transicao_rejeitada") == 1
    assert log.contar("chegou") == 1
    assert fila.tamanho() == 0


def test_tempo_de_resposta_registrado():
    relogio, repo, fila, log, w = montar()
    despachar(repo, fila, eta=300.0)
    w.processar_lote()
    w.aguardar_ciclos(timeout=5)
    chegou = next(e for e in log.eventos if e["tipo"] == "chegou")
    assert chegou["resposta_seg"] >= 300.0

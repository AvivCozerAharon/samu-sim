"""Exige LocalStack: AWS_ENDPOINT_URL=http://localhost:4566 e docker compose up localstack."""
import os
import urllib.request
import uuid

import pytest

from samu_sim.core.config import Config
from samu_sim.core.modelos import Ambulancia, Chamado, Rodada, StatusAmbulancia as SA
from samu_sim.infra.aws import FilaSQS, RepositorioDynamo, cliente_sqs, recurso_dynamo
from samu_sim.infra.bootstrap import apagar_recursos, criar_recursos
from samu_sim.infra.repositorio import ConflitoVersao

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cfg():
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    try:
        urllib.request.urlopen(endpoint + "/_localstack/health", timeout=2)
    except Exception:
        pytest.skip("LocalStack nao esta acessivel")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    c = Config(aws_endpoint_url=endpoint, prefixo_tabela=f"t{uuid.uuid4().hex[:6]}-",
               prefixo_fila_eventos=f"q{uuid.uuid4().hex[:6]}-", fila_chamados=f"c{uuid.uuid4().hex[:6]}",
               n_workers=1)
    criar_recursos(c)
    yield c
    apagar_recursos(c)


def test_fila_sqs_publica_recebe_ack(cfg):
    sqs = cliente_sqs(cfg)
    url = sqs.get_queue_url(QueueName=cfg.filas_chamados()["vermelho"])["QueueUrl"]
    f = FilaSQS(sqs, url)
    f.publicar({"chamado_id": "ch-1", "x": 1.5})
    msgs = f.receber()
    assert len(msgs) == 1 and msgs[0].corpo == {"chamado_id": "ch-1", "x": 1.5}
    f.ack(msgs[0])
    assert f.receber() == []


def test_dynamo_reserva_condicional(cfg):
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)
    repo.salvar_ambulancia(Ambulancia(id="amb-1", base_id="b", lat=-22.9, lon=-43.2, worker_id="w0"))
    a = repo.reservar_ambulancia("amb-1", 0, "ch-1")
    assert a.status == SA.RESERVADA and a.versao == 1
    with pytest.raises(ConflitoVersao):
        repo.reservar_ambulancia("amb-1", 0, "ch-2")
    a = repo.transicionar("amb-1", SA.RESERVADA, SA.A_CAMINHO, 1, heartbeat_em=5.0)
    assert a.versao == 2 and a.heartbeat_em == 5.0
    repo.atualizar_heartbeat("amb-1", 9.0)
    assert repo.obter_ambulancia("amb-1").versao == 2
    assert [x.id for x in repo.listar_ambulancias(SA.A_CAMINHO, worker_id="w0")] == ["amb-1"]
    b = repo.liberar_ambulancia("amb-1", 2, lat=0.0, lon=0.0)
    assert b.status == SA.DISPONIVEL and b.chamado_id is None


def test_dynamo_chamado_e_rodada(cfg):
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)
    repo.salvar_chamado(Chamado(id="ch-1", lat=1.0, lon=2.0, bairro="B", zona="Sul", criado_em=3.0))
    c = repo.obter_chamado("ch-1")
    assert c.zona == "Sul" and c.chegada_em is None
    assert repo.obter_chamado("nao") is None
    assert any(x.id == "ch-1" for x in repo.listar_chamados())
    repo.salvar_rodada(Rodada("atual", 1, "mais_proxima", 20.0, 5, "haversine", 100.0, 0.0))
    assert repo.obter_rodada().fator == 20.0


def test_dynamo_atualizar_posicao_condicional(cfg):
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)
    repo.salvar_ambulancia(Ambulancia(id="amb-7", base_id="b", lat=-22.9, lon=-43.2, worker_id="w0"))
    assert repo.atualizar_posicao_se_disponivel("amb-7", -22.8, -43.3) is True
    repo.reservar_ambulancia("amb-7", 0, "ch-x")
    assert repo.atualizar_posicao_se_disponivel("amb-7", 0.0, 0.0) is False
    assert repo.obter_ambulancia("amb-7").lat == -22.8


def test_dynamo_chamado_condicional_e_outbox(cfg):
    from samu_sim.core.modelos import StatusChamado as SC
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)
    repo.salvar_chamado(Chamado(id="ch-9", lat=1.0, lon=2.0, bairro="B", zona="Sul", criado_em=3.0))
    assert repo.obter_chamado("ch-9").publicado is False
    repo.marcar_publicado("ch-9")
    c = repo.obter_chamado("ch-9")
    c.status, c.ambulancia_id, c.despachado_em = SC.DESPACHADO, "amb-1", 10.0
    repo.salvar_chamado_se(c, SC.PENDENTE, None)  # ambulancia_id gravado como NULL: condicao "sem dono"
    lido = repo.obter_chamado("ch-9")
    assert lido.status == SC.DESPACHADO and lido.ambulancia_id == "amb-1" and lido.publicado is True
    with pytest.raises(ConflitoVersao):
        repo.salvar_chamado_se(c, SC.PENDENTE, None)       # ja nao esta pendente
    with pytest.raises(ConflitoVersao):
        repo.salvar_chamado_se(c, SC.DESPACHADO, "amb-2")  # e de outra ambulancia
    c.chegada_em = 50.0
    repo.salvar_chamado_se(c, SC.DESPACHADO, "amb-1")
    assert repo.obter_chamado("ch-9").chegada_em == 50.0
    c.status, c.ambulancia_id = SC.PENDENTE, None
    repo.salvar_chamado_se(c, SC.DESPACHADO, "amb-1", publicado=False)  # como o reaper devolve
    assert repo.obter_chamado("ch-9").publicado is False


def test_fila_sqs_adiar(cfg):
    import time
    sqs = cliente_sqs(cfg)
    url = sqs.get_queue_url(QueueName=cfg.filas_chamados()["amarelo"])["QueueUrl"]
    f = FilaSQS(sqs, url)
    f.publicar({"chamado_id": "ch-a"})
    m = f.receber()[0]
    f.adiar(m, 1)
    time.sleep(1.5)
    msgs = f.receber()
    assert [x.corpo["chamado_id"] for x in msgs] == ["ch-a"]
    f.ack(msgs[0])



def test_dynamo_registro_de_workers_e_reatribuicao(cfg):
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)
    repo.registrar_worker("w0", 10.0)
    repo.registrar_worker("w1", 20.0)
    assert repo.listar_workers() == {"w0": 10.0, "w1": 20.0}
    assert repo.obter_rodada() is None or repo.obter_rodada().id  # o item "atual" continua separado
    repo.salvar_ambulancia(Ambulancia(id="amb-r", base_id="b", lat=-22.9, lon=-43.2, worker_id="w0"))
    a = repo.reatribuir_worker("amb-r", 0, "w1")
    assert a.worker_id == "w1" and a.versao == 1
    repo.reservar_ambulancia("amb-r", 1, "ch-r")
    with pytest.raises(ConflitoVersao):
        repo.reatribuir_worker("amb-r", 2, "w0")  # ocupada: nao troca de dono
    b = repo.liberar_ambulancia("amb-r", 2, lat=1.0, lon=2.0, worker_id="w0")
    assert b.worker_id == "w0" and (b.lat, b.lon) == (1.0, 2.0)

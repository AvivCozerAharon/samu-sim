from decimal import Decimal
from samu_sim.core.modelos import Ambulancia, Chamado, Rodada, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.infra.aws import para_item, de_item


def test_ambulancia_ida_e_volta():
    a = Ambulancia(id="amb-1", base_id="b", lat=-22.9, lon=-43.2, worker_id="w0",
                   status=SA.A_CAMINHO, versao=4, chamado_id="ch-1", heartbeat_em=1.5)
    item = para_item(a)
    assert item["lat"] == Decimal("-22.9") and item["status"] == "a_caminho" and item["versao"] == 4
    b = de_item(Ambulancia, item)
    assert b == a and isinstance(b.lat, float) and isinstance(b.versao, int) and b.status is SA.A_CAMINHO


def test_chamado_com_nones():
    c = Chamado(id="ch-1", lat=1.0, lon=2.0, bairro="B", zona="Sul", criado_em=10.0)
    item = para_item(c)
    assert item["chegada_em"] is None and item["status"] == "pendente"
    d = de_item(Chamado, item)
    assert d == c and d.status is SC.PENDENTE


def test_rodada():
    r = Rodada("atual", 42, "mais_proxima", 20.0, 50, "haversine", 1700000000.5, 0.0, False)
    assert de_item(Rodada, para_item(r)) == r

from samu_sim.core.config import Config


def test_defaults():
    c = Config.do_ambiente({})
    assert c.aws_endpoint_url is None and c.n_workers == 2 and c.fator == 20.0
    assert c.fila_eventos("w1") == "samu-eventos-w1"
    assert c.tabela("ambulancias") == "samu-ambulancias"


def test_le_do_ambiente_com_tipos():
    c = Config.do_ambiente({"AWS_ENDPOINT_URL": "http://localstack:4566", "N_WORKERS": "3",
                            "FATOR": "5", "WORKER_ID": "w2", "SEED": "9"})
    assert c.aws_endpoint_url == "http://localstack:4566"
    assert c.n_workers == 3 and c.fator == 5.0 and c.worker_id == "w2" and c.seed == 9


def test_reset_bool():
    assert Config.do_ambiente({}).reset is False
    assert Config.do_ambiente({"RESET": "1"}).reset is True
    assert Config.do_ambiente({"RESET": "false"}).reset is False

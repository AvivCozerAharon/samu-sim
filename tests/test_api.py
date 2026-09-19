from fastapi.testclient import TestClient
from samu_sim.api import criar_app
from samu_sim.core.modelos import Ambulancia, Base, Chamado, Rodada
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria


def montar():
    repo = RepositorioMemoria()
    t = {"v": 1000.0}
    relogio = Relogio(fator=10, agora_real=lambda: t["v"])
    repo.salvar_rodada(Rodada("atual", 1, "mais_proxima", 10, 2, "haversine", 1000.0, 0.0))
    repo.salvar_ambulancia(Ambulancia(id="amb-1", base_id="b1", lat=-22.9, lon=-43.2, worker_id="w0"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=0.0))
    app = criar_app(repo, FilaMemoria(), {"b1": Base("b1", "B", -22.9, -43.2)}, relogio,
                    EventLogMemoria(relogio, "api"), agora_real=lambda: t["v"], intervalo_ws_seg=0.01)
    return TestClient(app), repo, relogio, t


def test_estado():
    c, repo, relogio, t = montar()
    t["v"] = 1003.0
    r = c.get("/estado").json()
    assert r["agora_sim"] == 30.0 and r["fator"] == 10 and r["pausada"] is False
    assert r["ambulancias"][0]["id"] == "amb-1" and r["chamados_abertos"][0]["id"] == "ch-1"


def test_metricas_inclui_fila():
    c, repo, relogio, t = montar()
    t["v"] = 1006.0  # sim = 60
    r = c.get("/metricas").json()
    assert r["total"] == 1 and r["fila"]["pendentes"] == 1 and r["fila"]["idade_max_seg"] == 60.0


def test_controle_muda_fator_sem_saltar_o_tempo():
    c, repo, relogio, t = montar()
    t["v"] = 1003.0  # sim = 30
    r = c.post("/controle", json={"fator": 2}).json()
    assert r["fator"] == 2 and r["inicio_sim"] == 30.0 and r["inicio_real"] == 1003.0
    t["v"] = 1008.0
    assert c.get("/estado").json()["agora_sim"] == 40.0
    assert repo.obter_rodada().fator == 2


def test_controle_pausa_e_despausa():
    c, repo, relogio, t = montar()
    c.post("/controle", json={"pausada": True})
    t["v"] = 1100.0
    assert c.get("/estado").json()["agora_sim"] == 0.0
    assert c.get("/estado").json()["pausada"] is True
    r = c.post("/controle", json={"pausada": False}).json()
    assert r["fator"] == 10 and r["pausada"] is False


def test_controle_rejeita_fator_negativo():
    c, *_ = montar()
    assert c.post("/controle", json={"fator": -1}).status_code == 422


def test_mapa_na_raiz():
    c, *_ = montar()
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "leaflet" in r.text.lower() and "/estado" in r.text


def test_ws_estado_envia_snapshot():
    c, repo, relogio, t = montar()
    with c.websocket_connect("/ws/estado") as ws:
        dados = ws.receive_json()
    assert "ambulancias" in dados and dados["ambulancias"][0]["id"] == "amb-1"

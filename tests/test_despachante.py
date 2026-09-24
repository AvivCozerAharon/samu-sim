import threading
from samu_sim.core.modelos import Ambulancia, Chamado, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.core.relogio import Relogio
from samu_sim.despachante.servico import Despachante
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria
from samu_sim.politicas import MaisProxima
from samu_sim.roteador import RoteadorHaversine


def montar(n_amb=2):
    relogio = Relogio(fator=1)
    repo = RepositorioMemoria()
    for i in range(n_amb):
        repo.salvar_ambulancia(Ambulancia(id=f"amb-{i}", base_id="b", lat=-22.90 - i * 0.05,
                                          lon=-43.20, worker_id=f"w{i % 2}"))
    fila = FilaMemoria(visibilidade_seg=0.01)
    filas_ev = {"w0": FilaMemoria(), "w1": FilaMemoria()}
    log = EventLogMemoria(relogio, "despachante")
    d = Despachante(fila, filas_ev, repo, MaisProxima(), RoteadorHaversine(), relogio, log, cache_seg=0)
    return relogio, repo, fila, filas_ev, log, d


def mensagem(id="ch-1", lat=-22.90, lon=-43.20):
    return {"chamado_id": id, "lat": lat, "lon": lon, "bairro": "Centro", "zona": "Centro", "criado_em": 0}


def publicar_chamado(fila, repo, id="ch-1", lat=-22.90, lon=-43.20):
    repo.salvar_chamado(Chamado(id=id, lat=lat, lon=lon, bairro="Centro", zona="Centro", criado_em=0))
    fila.publicar(mensagem(id, lat, lon))


def test_despacha_a_mais_proxima_e_publica_no_worker_dono():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    assert d.processar_lote() == 1
    a = repo.obter_ambulancia("amb-0")           # a mais proxima
    assert a.status == SA.RESERVADA and a.chamado_id == "ch-1"
    c = repo.obter_chamado("ch-1")
    assert c.status == SC.DESPACHADO and c.ambulancia_id == "amb-0" and c.despachado_em is not None
    ev = filas_ev["w0"].receber()[0].corpo
    assert ev["tipo"] == "despachada" and ev["ambulancia_id"] == "amb-0" and ev["eta_seg"] >= 0
    assert filas_ev["w1"].tamanho() == 0
    assert fila.tamanho() == 0                   # ack dado
    assert log.contar("despachada") == 1


def test_sem_ambulancia_nao_da_ack():
    relogio, repo, fila, filas_ev, log, d = montar(n_amb=0)
    publicar_chamado(fila, repo)
    assert d.processar_lote() == 0
    assert fila.tamanho() == 1
    assert log.contar("sem_ambulancia") == 1


def test_mensagem_duplicada_e_idempotente():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    d.processar_lote()
    fila.publicar(mensagem())  # duplicata: mesma mensagem entregue de novo
    assert d.processar_lote() == 1
    assert repo.obter_ambulancia("amb-1").status == SA.DISPONIVEL  # nao despachou de novo
    assert filas_ev["w0"].tamanho() == 1                          # so 1 evento despachada
    assert log.contar("chamado_ja_despachado") == 1


def test_perde_a_corrida_e_tenta_a_proxima():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    # outro despachante reservou a amb-0 depois que este ja tinha lido a lista de disponiveis:
    original = repo.listar_ambulancias

    def listar_desatualizado(status=None):
        lista = original(status)
        a0 = repo.obter_ambulancia("amb-0")
        a0.status = SA.DISPONIVEL
        a0.versao = 0
        return [a0] + [a for a in lista if a.id != "amb-0"]

    repo.listar_ambulancias = listar_desatualizado
    repo.reservar_ambulancia("amb-0", 0, "ch-outro")
    assert d.processar_lote() == 1
    assert repo.obter_chamado("ch-1").ambulancia_id == "amb-1"
    assert log.contar("reserva_falhou") == 1


def test_dois_despachantes_concorrentes_nunca_duplicam():
    relogio, repo, fila, filas_ev, log, d1 = montar(n_amb=1)
    d2 = Despachante(fila, filas_ev, repo, MaisProxima(), RoteadorHaversine(), relogio, log, cache_seg=0)
    for i in range(10):
        publicar_chamado(fila, repo, id=f"ch-{i}")
    b = threading.Barrier(2)

    def roda(d):
        b.wait()
        for _ in range(20):
            d.processar_lote()

    ts = [threading.Thread(target=roda, args=(d,)) for d in (d1, d2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    despachados = [c for c in repo.listar_chamados() if c.status == SC.DESPACHADO]
    assert len(despachados) == 1                       # so 1 ambulancia
    assert filas_ev["w0"].tamanho() == 1               # 1 evento despachada, nao 2


def test_reserva_grava_heartbeat_para_o_reaper_nao_liberar_cedo():
    relogio, repo, fila, filas_ev, log, d = montar()
    d._agora_real = lambda: 4242.0
    publicar_chamado(fila, repo)
    d.processar_lote()
    assert repo.obter_ambulancia("amb-0").heartbeat_em == 4242.0


def test_despacho_grava_chegada_prevista():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    d.processar_lote()
    c = repo.obter_chamado("ch-1")
    ev = filas_ev["w0"].receber()[0].corpo
    assert c.chegada_prevista_em == c.despachado_em + ev["eta_seg"]


# ---------- filas por prioridade (D7) ----------
def test_vermelho_publicado_depois_e_despachado_antes_dos_verdes():
    from samu_sim.core.modelos import PRIORIDADES
    relogio = Relogio(fator=1)
    repo = RepositorioMemoria()
    repo.salvar_ambulancia(Ambulancia(id="amb-0", base_id="b", lat=-22.90, lon=-43.20, worker_id="w0"))
    filas = {p: FilaMemoria(visibilidade_seg=0.01) for p in PRIORIDADES}
    filas_ev = {"w0": FilaMemoria()}
    log = EventLogMemoria(relogio, "despachante")
    d = Despachante(filas, filas_ev, repo, MaisProxima(), RoteadorHaversine(), relogio, log, cache_seg=0)
    for i in range(3):
        c = Chamado(id=f"verde-{i}", lat=-22.9, lon=-43.2, bairro="B", zona="Sul", criado_em=0, prioridade="verde")
        repo.salvar_chamado(c)
        filas["verde"].publicar({"chamado_id": c.id, "prioridade": "verde"})
    c = Chamado(id="vermelho-0", lat=-22.9, lon=-43.2, bairro="B", zona="Sul", criado_em=5, prioridade="vermelho")
    repo.salvar_chamado(c)
    filas["vermelho"].publicar({"chamado_id": c.id, "prioridade": "vermelho"})
    assert d.processar_lote() == 1
    assert repo.obter_chamado("vermelho-0").ambulancia_id == "amb-0"
    assert all(repo.obter_chamado(f"verde-{i}").ambulancia_id is None for i in range(3))
    assert d.processar_lote() == 0  # sem ambulancia: verdes ficam na fila (sem ack)
    assert filas["verde"].tamanho() == 3


# ---------- corrida com mensagem duplicada e inversao de prioridade ----------
def test_mensagem_duplicada_em_corrida_desfaz_a_segunda_reserva():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    velho = repo.obter_chamado("ch-1")  # o que o 2o despachante leu, ainda PENDENTE
    c = repo.obter_chamado("ch-1")      # enquanto isso o 1o despachou para a amb-9
    c.status, c.ambulancia_id = SC.DESPACHADO, "amb-9"
    repo.salvar_chamado(c)
    repo.obter_chamado = lambda _id: velho
    assert d.processar_lote() == 1
    assert repo.obter_ambulancia("amb-0").status == SA.DISPONIVEL  # reserva desfeita
    assert log.contar("despacho_duplicado_evitado") == 1
    assert filas_ev["w0"].tamanho() == 0 and filas_ev["w1"].tamanho() == 0
    assert fila.tamanho() == 0  # deu ack


def test_sem_ambulancia_para_vermelho_segura_os_verdes_e_volta_rapido():
    import time
    from samu_sim.core.modelos import PRIORIDADES
    relogio = Relogio(fator=1)
    repo = RepositorioMemoria()
    filas = {p: FilaMemoria(visibilidade_seg=30) for p in PRIORIDADES}
    filas_ev = {"w0": FilaMemoria()}
    log = EventLogMemoria(relogio, "despachante")
    d = Despachante(filas, filas_ev, repo, MaisProxima(), RoteadorHaversine(), relogio, log,
                    cache_seg=0, reentrega_seg=0.1)
    for id_, pri in (("verde-0", "verde"), ("vermelho-0", "vermelho")):
        repo.salvar_chamado(Chamado(id=id_, lat=-22.9, lon=-43.2, bairro="B", zona="Sul", criado_em=0, prioridade=pri))
        filas[pri].publicar({"chamado_id": id_, "prioridade": pri})
    assert d.processar_lote() == 0  # vermelho sem ambulancia
    repo.salvar_ambulancia(Ambulancia(id="amb-0", base_id="b", lat=-22.90, lon=-43.20, worker_id="w0"))
    assert d.processar_lote() == 0  # a ambulancia livrou, mas o verde nao passa na frente
    assert repo.obter_chamado("verde-0").ambulancia_id is None
    time.sleep(0.12)                 # o vermelho volta em reentrega_seg, nao em 30 s
    assert d.processar_lote() == 1
    assert repo.obter_chamado("vermelho-0").ambulancia_id == "amb-0"

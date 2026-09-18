import threading
from samu_sim.core.modelos import Chamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.gerador.servico import ServicoGerador
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria


def ch(n, ts):
    return Chamado(id=f"ch-{n}", lat=-22.9, lon=-43.2, bairro="Centro", zona="Centro", criado_em=ts)


def test_publica_na_ordem_e_salva_no_repo():
    relogio = Relogio(fator=100000)  # 1 s real = ~28 h sim
    fila, repo = FilaMemoria(), RepositorioMemoria()
    log = EventLogMemoria(relogio, "gerador")
    svc = ServicoGerador([ch(1, 10), ch(2, 20), ch(3, 30)], fila, repo, relogio, log)
    n = svc.executar(threading.Event())
    assert n == 3
    msgs = fila.receber()
    assert [m.corpo["chamado_id"] for m in msgs] == ["ch-1", "ch-2", "ch-3"]
    assert msgs[0].corpo["criado_em"] == 10
    assert repo.obter_chamado("ch-2") is not None
    assert log.contar("chamado_criado") == 3


def test_para_quando_evento_setado():
    relogio = Relogio(fator=1)
    fila, repo = FilaMemoria(), RepositorioMemoria()
    parar = threading.Event()
    svc = ServicoGerador([ch(1, 0), ch(2, 3600)], fila, repo, relogio, EventLogMemoria(relogio, "g"))
    t = threading.Thread(target=lambda: svc.executar(parar))
    t.start()
    parar.set()
    t.join(timeout=2)
    assert not t.is_alive()
    assert fila.tamanho() == 1  # so o primeiro (criado_em=0) saiu

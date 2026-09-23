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


def test_pula_chamados_ja_no_passado_ao_iniciar():
    """Gerador que sobe atrasado nao publica chamados com criado_em no passado
    (inflaria o tempo de resposta com uma espera ficticia)."""
    relogio = Relogio(fator=100000, inicio_sim=5000)
    fila, repo = FilaMemoria(), RepositorioMemoria()
    log = EventLogMemoria(relogio, "gerador")
    svc = ServicoGerador([ch(1, 100), ch(2, 4900), ch(3, 5010), ch(4, 5020)], fila, repo, relogio, log)
    n = svc.executar(threading.Event())
    assert n == 2
    assert [m.corpo["chamado_id"] for m in fila.receber()] == ["ch-3", "ch-4"]
    assert log.contar("chamados_pulados") == 1
    assert log.eventos[0]["quantidade"] == 2


def test_marca_publicado_depois_de_publicar():
    relogio = Relogio(fator=100000)
    fila, repo = FilaMemoria(), RepositorioMemoria()
    svc = ServicoGerador([ch(1, 10)], fila, repo, relogio, EventLogMemoria(relogio, "gerador"))
    svc.executar(threading.Event())
    assert repo.obter_chamado("ch-1").publicado is True


def test_reinicio_no_meio_da_rodada_nao_sobrescreve_nem_perde_chamado():
    from samu_sim.core.modelos import StatusChamado as SC
    relogio = Relogio(fator=1)
    relogio.sincronizar(relogio.checkpoint()[0], 1000.0, 1)  # agora_sim ~ 1000
    fila, repo = FilaMemoria(), RepositorioMemoria()
    log = EventLogMemoria(relogio, "gerador")
    # antes de cair, o gerador ja tinha publicado ch-1, que foi despachado
    repo.salvar_chamado(Chamado(id="ch-1", lat=0, lon=0, bairro="B", zona="Sul", criado_em=10,
                                status=SC.DESPACHADO, ambulancia_id="amb-1", publicado=True))
    svc = ServicoGerador([ch(1, 10), ch(2, 20)], fila, repo, relogio, log)  # ch-2: 980 s atrasado
    assert svc.executar(threading.Event()) == 1
    assert repo.obter_chamado("ch-1").status == SC.DESPACHADO  # nao sobrescreveu
    assert repo.obter_chamado("ch-2") is not None               # nao pulou o atrasado
    assert [m.corpo["chamado_id"] for m in fila.receber()] == ["ch-2"]


def test_primeira_subida_atrasada_ainda_pula_o_passado():
    relogio = Relogio(fator=1)
    relogio.sincronizar(relogio.checkpoint()[0], 1000.0, 1)
    fila, repo = FilaMemoria(), RepositorioMemoria()
    log = EventLogMemoria(relogio, "gerador")
    svc = ServicoGerador([ch(1, 10), ch(2, 999)], fila, repo, relogio, log)
    assert svc.executar(threading.Event()) == 1
    assert repo.obter_chamado("ch-1") is None and log.contar("chamados_pulados") == 1

from samu_sim.infra.fila import FilaMemoria


class Tempo:
    t = 0.0

    def agora(self):
        return self.t


def test_publicar_receber_ack():
    f = FilaMemoria()
    f.publicar({"x": 1})
    msgs = f.receber()
    assert len(msgs) == 1 and msgs[0].corpo == {"x": 1}
    f.ack(msgs[0])
    assert f.receber() == []
    assert f.tamanho() == 0


def test_sem_ack_reentrega_apos_visibilidade():
    tempo = Tempo()
    f = FilaMemoria(visibilidade_seg=30, agora=tempo.agora)
    f.publicar({"x": 1})
    m1 = f.receber()[0]
    assert f.receber() == []          # invisivel
    tempo.t = 31
    m2 = f.receber()[0]               # reentregue
    assert m2.corpo == m1.corpo
    assert f.tamanho() == 1


def test_receber_respeita_max_e_ordem_fifo():
    f = FilaMemoria()
    for i in range(5):
        f.publicar({"i": i})
    lote = f.receber(max_msgs=3)
    assert [m.corpo["i"] for m in lote] == [0, 1, 2]


def test_ack_de_mensagem_ja_reentregue_nao_quebra():
    tempo = Tempo()
    f = FilaMemoria(visibilidade_seg=1, agora=tempo.agora)
    f.publicar({"x": 1})
    m1 = f.receber()[0]
    tempo.t = 2
    m2 = f.receber()[0]
    f.ack(m1)
    assert f.tamanho() == 0
    f.ack(m2)  # idempotente


def test_adiar_devolve_a_mensagem_antes_do_visibility_timeout():
    tempo = Tempo()
    f = FilaMemoria(visibilidade_seg=30, agora=tempo.agora)
    f.publicar({"x": 1})
    m = f.receber()[0]
    f.adiar(m, 2)
    tempo.t = 1.9
    assert f.receber() == []
    tempo.t = 2.0
    assert len(f.receber()) == 1

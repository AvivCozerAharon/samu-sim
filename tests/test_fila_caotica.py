import pytest

from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.fila_caotica import Caos, FalhaInjetada, FilaCaotica


class Tempo:
    t = 0.0

    def agora(self):
        return self.t


def test_desligado_e_uma_fila_normal():
    caos = Caos(duplicar=1, atrasar=1, perder_ack=1, falhar_publicar=1)
    caos.ligado.clear()
    f = FilaCaotica(FilaMemoria(), caos)
    f.publicar({"x": 1})
    m = f.receber()
    assert [x.corpo for x in m] == [{"x": 1}]
    f.ack(m[0])
    assert f.tamanho() == 0


def test_duplica():
    f = FilaCaotica(FilaMemoria(), Caos(duplicar=1, atrasar=0, perder_ack=0, falhar_publicar=0))
    f.publicar({"x": 1})
    assert [m.corpo for m in f.receber()] == [{"x": 1}, {"x": 1}]


def test_atrasa_ate_o_prazo():
    tempo = Tempo()
    f = FilaCaotica(FilaMemoria(agora=tempo.agora), Caos(duplicar=0, atrasar=1, atraso_max_seg=1, perder_ack=0,
                                                          falhar_publicar=0), agora=tempo.agora)
    f.publicar({"x": 1})
    assert f.receber() == [] and f.tamanho() == 1
    tempo.t = 1.0
    assert len(f.receber()) == 1


def test_ack_perdido_faz_a_mensagem_voltar():
    tempo = Tempo()
    f = FilaCaotica(FilaMemoria(visibilidade_seg=1, agora=tempo.agora),
                    Caos(duplicar=0, atrasar=0, perder_ack=1, falhar_publicar=0))
    f.publicar({"x": 1})
    f.ack(f.receber()[0])
    tempo.t = 1.0
    assert len(f.receber()) == 1


def test_processo_morre_ao_publicar():
    f = FilaCaotica(FilaMemoria(), Caos(falhar_publicar=1))
    with pytest.raises(FalhaInjetada):
        f.publicar({"x": 1})
    assert f.tamanho() == 0 and f.injetadas["publicacao_falhou"] == 1

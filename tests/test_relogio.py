import pytest
from samu_sim.core.relogio import Relogio


class RelogioFake:
    def __init__(self):
        self.t = 100.0
        self.dormidas = []

    def agora(self):
        return self.t

    def dormir(self, s):
        self.dormidas.append(s)
        self.t += s


def test_agora_sim_avanca_com_fator():
    f = RelogioFake()
    r = Relogio(fator=10, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 3.0
    assert r.agora_sim() == pytest.approx(30.0)


def test_definir_fator_nao_salta_o_tempo():
    f = RelogioFake()
    r = Relogio(fator=10, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 3.0  # sim = 30
    r.definir_fator(2)
    assert r.agora_sim() == pytest.approx(30.0)
    f.t += 5.0  # + 10 sim
    assert r.agora_sim() == pytest.approx(40.0)


def test_dormir_sim_divide_pelo_fator():
    f = RelogioFake()
    r = Relogio(fator=20, agora_real=f.agora, dormir_real=f.dormir)
    r.dormir_sim(60)
    assert r.agora_sim() == pytest.approx(60.0)
    assert sum(f.dormidas) == pytest.approx(3.0)


def test_dormir_sim_em_pedacos_respeita_mudanca_de_fator():
    f = RelogioFake()
    r = Relogio(fator=1, agora_real=f.agora, dormir_real=f.dormir)
    chamadas = {"n": 0}
    dormir_original = f.dormir

    def dormir_e_acelera(s):
        dormir_original(s)
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            r.definir_fator(100)

    r._dormir_real = dormir_e_acelera
    r.dormir_sim(10)
    assert r.agora_sim() == pytest.approx(10.0, abs=0.01)
    assert sum(f.dormidas) < 5.0  # acelerou apos o 2o pedaco


def test_sincronizar_substitui_checkpoint():
    f = RelogioFake()
    r = Relogio(fator=1, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 10                       # sim = 10
    r.sincronizar(inicio_real=f.t - 2, inicio_sim=1000, fator=5)
    assert r.agora_sim() == pytest.approx(1010)   # 1000 + 2*5
    assert r.fator == 5


def test_fator_zero_pausa_sem_dividir_por_zero():
    f = RelogioFake()
    r = Relogio(fator=10, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 1                        # sim = 10
    r.definir_fator(0)
    f.t += 100
    assert r.agora_sim() == pytest.approx(10) and r.pausado
    n = {"i": 0}

    def dormir(s):
        f.dormir(s)
        n["i"] += 1
        if n["i"] == 3:
            r.definir_fator(10)

    r._dormir_real = dormir
    r.dormir_sim(20)
    assert r.agora_sim() == pytest.approx(30, abs=0.01)

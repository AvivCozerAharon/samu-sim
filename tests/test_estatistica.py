import pytest

from samu_sim.estatistica import diferenca_pareada, ic_bootstrap


def test_ic_bootstrap_contem_media_e_estreita_com_mais_dados():
    r = ic_bootstrap([10, 12, 11, 13, 9, 10, 12, 11], seed=1)
    assert r["baixo"] <= r["media"] <= r["alto"]
    assert r["n"] == 8
    largo = ic_bootstrap([10, 14], seed=1)
    assert (largo["alto"] - largo["baixo"]) > (r["alto"] - r["baixo"])


def test_ic_bootstrap_vazio_e_um_valor():
    assert ic_bootstrap([])["media"] is None
    r = ic_bootstrap([5.0])
    assert r["media"] == r["baixo"] == r["alto"] == 5.0


def test_ic_bootstrap_ignora_none():
    assert ic_bootstrap([1, None, 3])["n"] == 2


def test_diferenca_pareada_detecta_ganho_consistente():
    a = [100, 110, 105, 120, 98, 107]
    b = [x - 8 for x in a]  # sempre 8 melhor
    r = diferenca_pareada(a, b, seed=1)
    assert r["media"] == pytest.approx(-8)
    assert r["significativo"] is True and r["alto"] < 0


def test_diferenca_pareada_ruido_nao_significativo():
    a = [100, 110, 105, 120, 98, 107]
    b = [101, 108, 106, 119, 99, 106]
    r = diferenca_pareada(a, b, seed=1)
    assert r["significativo"] is False


def test_diferenca_pareada_exige_mesmo_tamanho():
    with pytest.raises(ValueError):
        diferenca_pareada([1, 2], [1])

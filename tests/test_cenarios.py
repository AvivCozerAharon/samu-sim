import time

import pytest

from samu_sim.cenarios import Cenario, GerenciadorCenarios, comparar, executar, extrair


def fake_rodar(**kw):
    seed, n = kw["seed"], kw["n_ambulancias"]
    p90 = 1200 - 10 * n + seed  # mais frota = melhor, seed = ruido
    return {"metricas": {"total": 100, "atendidos": 95, "pendentes": 5 if n < 80 else 0,
                         "resposta": {"p50": p90 / 2, "p90": p90, "media": p90 / 1.5},
                         "por_zona": {"Oeste": {"p90": p90 + 100}},
                         "por_prioridade": {"vermelho": {"p90": p90 - 50}},
                         "espera_despacho": {"p90": 30}},
            "eventos": {}, "ambulancias": [], "alocacao": {}}


def esperar(g, ids, status="concluido"):
    for _ in range(200):
        if all(g.obter(i)["status"] == status for i in ids):
            return
        time.sleep(0.02)
    raise AssertionError("jobs nao terminaram")


def test_extrair_linha_por_seed():
    linha = extrair(fake_rodar(seed=1, n_ambulancias=73))
    assert linha["p90"] == 471 and linha["Oeste"] == 571 and linha["Barra"] is None
    assert linha["pendentes"] == 5


def test_executar_resume_com_ic():
    r = executar(Cenario("base"), [1, 2, 3], 3600, 100, fake_rodar)
    assert r["seeds"] == [1, 2, 3] and len(r["por_seed"]) == 3
    assert r["resumo"]["p90"]["n"] == 3
    assert r["resumo"]["p90"]["baixo"] <= r["resumo"]["p90"]["media"] <= r["resumo"]["p90"]["alto"]
    assert r["cenario"]["nome"] == "base"


def test_comparar_pareado_detecta_ganho_de_frota():
    a = executar(Cenario("73"), [1, 2, 3, 4], 3600, 100, fake_rodar)
    b = executar(Cenario("80", n_ambulancias=80), [1, 2, 3, 4], 3600, 100, fake_rodar)
    d = comparar(a, b)
    assert d["p90"]["media"] == -70 and d["p90"]["significativo"] is True
    assert d["pendentes"]["media"] == -5


def test_comparar_exige_mesmas_seeds():
    a = executar(Cenario("a"), [1, 2], 3600, 100, fake_rodar)
    b = executar(Cenario("b"), [1, 3], 3600, 100, fake_rodar)
    with pytest.raises(ValueError):
        comparar(a, b)


def test_cenario_serializa_ida_e_volta():
    c = Cenario("x", n_ambulancias=75, alocacao={"b1": 75},
                bases_extra=({"id": "cand-1", "nome": "C", "lat": -22.9, "lon": -43.6},))
    assert Cenario.de_dict(c.para_dict()) == c
    assert c.objetos_bases_extra()[0].tipo == "candidata"


def test_gerenciador_roda_em_ordem_e_expoe_status():
    g = GerenciadorCenarios(lambda c, seeds, dur, fator: executar(c, seeds, dur, fator, fake_rodar))
    i1 = g.submeter(Cenario("um"), [1, 2], 3600, 100)
    i2 = g.submeter(Cenario("dois", n_ambulancias=80), [1, 2], 3600, 100)
    esperar(g, [i1, i2])
    assert g.obter(i1)["resultado"]["resumo"]["p90"]["media"] > g.obter(i2)["resultado"]["resumo"]["p90"]["media"]
    assert [j["id"] for j in g.listar()] == [i1, i2]
    assert "resultado" not in g.listar()[0]
    g.encerrar()


def test_gerenciador_registra_erro():
    def explode(*a):
        raise RuntimeError("boom")
    g = GerenciadorCenarios(explode)
    i = g.submeter(Cenario("x"), [1], 10, 1)
    esperar(g, [i], "erro")
    assert "boom" in g.obter(i)["erro"]
    assert g.obter("nada") is None
    g.encerrar()


def test_criar_gerenciador_limita_fator(monkeypatch):
    from samu_sim import cenarios as mod
    chamadas = []
    monkeypatch.setattr(mod, "executar", lambda c, s, d, f, fn: chamadas.append(f) or {"resumo": {}})
    g = mod.criar_gerenciador(fator_max=500)
    i = g.submeter(Cenario("x"), [1], 10, 3000)
    esperar(g, [i])
    assert chamadas == [500]
    g.encerrar()

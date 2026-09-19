from samu_sim.cenarios import Cenario
from samu_sim.core.modelos import Base
from samu_sim.expansao import candidatas, cenario_candidata, demanda_descoberta
from samu_sim.gerador.demanda import Bairro, carregar_bairros, carregar_bases

B = Base("b1", "Base 1", -22.90, -43.20)


def test_demanda_descoberta_zero_quando_coberto():
    perto = Bairro("Perto", "Centro", -22.905, -43.205, 10000, 1.0)
    longe = Bairro("Longe", "Oeste", -22.90, -43.60, 10000, 1.0)
    assert demanda_descoberta(perto, [B], 5.0) == 0
    assert demanda_descoberta(longe, [B], 5.0) == longe.peso


def test_candidatas_ordenadas_e_com_slug():
    bairros = [Bairro("Santa Cruz", "Oeste", -22.92, -43.68, 200000, 1.0),
               Bairro("Guaratiba", "Oeste", -23.00, -43.60, 50000, 1.0),
               Bairro("Centro", "Centro", -22.905, -43.205, 40000, 9.5)]
    c = candidatas(bairros, [B], raio_km=5.0, max_n=5)
    assert [x["bairro"] for x in c] == ["Santa Cruz", "Guaratiba"]
    assert c[0]["id"] == "cand-santa-cruz" and c[0]["dist_base_mais_proxima_km"] > 40


def test_candidatas_com_dados_reais_tem_barra_ou_oeste():
    c = candidatas(carregar_bairros("dados/bairros.csv"), carregar_bases("dados/bases.csv"))
    assert 1 <= len(c) <= 12
    assert any(x["zona"] in ("Barra", "Oeste") for x in c)


def test_cenario_candidata_soma_frota():
    cand = {"id": "cand-x", "nome": "Nova base — X", "lat": -22.9, "lon": -43.6}
    c = cenario_candidata(cand, {"b1": 70, "b2": 3}, extra=2, transito=True)
    assert isinstance(c, Cenario) and c.n_ambulancias == 75 and c.transito
    assert c.alocacao["cand-x"] == 2 and c.bases_extra[0]["id"] == "cand-x"

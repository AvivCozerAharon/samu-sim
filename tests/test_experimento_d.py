from samu_sim.core.modelos import Base
from samu_sim.gerador.demanda import Bairro
from scripts import experimento_d
from tests.test_cenarios import fake_rodar


def test_experimento_d_escolhe_finalistas_e_compara():
    bases = [Base("b1", "Base 1", -22.90, -43.20), Base("b2", "Base 2", -22.95, -43.35)]
    bairros = [Bairro("Santa Cruz", "Oeste", -22.92, -43.68, 200000, 1.0),
               Bairro("Guaratiba", "Oeste", -23.00, -43.60, 50000, 1.0),
               Bairro("Centro", "Centro", -22.905, -43.205, 40000, 9.5)]
    res = experimento_d.executar(fake_rodar, bairros, bases, {"b1": 40, "b2": 33}, [1], [1, 2], 3600, 7200, 100,
                                 extra=2, max_candidatas=2, n_finalistas=1, log=lambda *_: None)
    assert len(res["triagem"]) == 2 and len(res["finalistas"]) == 1
    f = res["finalistas"][0]
    assert f["resultado"]["cenario"]["n_ambulancias"] == 75
    assert f["vs_baseline"]["p90"]["media"] == -20  # fake: -10 s por ambulancia
    assert f["vs_controle"]["p90"]["media"] == 0  # controle tambem tem 75
    assert res["controle"]["cenario"]["n_ambulancias"] == 75
    assert res["config"]["controle_base"] == "Base 1"  # cobre o Centro (peso 9.5x)

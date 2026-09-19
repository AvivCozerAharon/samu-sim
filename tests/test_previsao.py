from samu_sim.core.modelos import Ambulancia, Base
from samu_sim.gerador.demanda import Bairro
from samu_sim.infra.repositorio import RepositorioMemoria
from samu_sim.previsao import ModeloDemanda, Reposicionador


def eventos_sinteticos():
    ev = []
    for dia in range(10):
        for h in range(24):
            n = 6 if 18 <= h <= 21 else 1
            for _ in range(n):
                ev.append({"tipo": "chamado_criado", "ts_sim": dia * 86400 + h * 3600 + 10, "zona": "Oeste"})
            ev.append({"tipo": "chamado_criado", "ts_sim": dia * 86400 + h * 3600 + 20, "zona": "Sul"})
    return ev


def test_modelo_aprende_pico_e_normaliza_por_dia():
    m = ModeloDemanda.treinar(eventos_sinteticos())
    assert 9 < m.dias <= 10.01
    assert m.taxa["Oeste"][19] > 4 and m.taxa["Oeste"][3] < 2
    assert m.prever("Oeste", 18 * 3600, horas=2) > 3 * m.prever("Sul", 18 * 3600, horas=2)


def test_modelo_salva_e_carrega(tmp_path):
    m = ModeloDemanda.treinar(eventos_sinteticos())
    m.salvar(tmp_path / "m.json")
    assert ModeloDemanda.carregar(tmp_path / "m.json").taxa["Oeste"][19] == m.taxa["Oeste"][19]


def test_reposicionador_escolhe_zona_com_mais_demanda_e_menos_cobertura():
    m = ModeloDemanda.treinar(eventos_sinteticos())
    bases = {"sul": Base("sul", "UPA Sul", -22.97, -43.19, "upa"), "oeste": Base("oeste", "UPA Oeste", -22.90, -43.30, "upa")}
    bairros = [Bairro("Copacabana", "Sul", -22.97, -43.19, 100), Bairro("Bangu", "Oeste", -22.90, -43.30, 100)]
    repo = RepositorioMemoria()
    for i in range(3):  # Sul ja tem 3 livres; Oeste nenhuma
        repo.salvar_ambulancia(Ambulancia(id=f"s{i}", base_id="sul", lat=-22.97, lon=-43.19, worker_id="w0"))
    r = Reposicionador(m, bases, bairros, repo)
    alvo, expl = r.escolher_base((-22.95, -43.22), agora_sim=18 * 3600, base_atual="sul")
    assert alvo.id == "oeste" and expl["zona"] == "Oeste" and expl["livres_na_zona"] == 0
    # de madrugada a demanda do Oeste cai; com 3 livres no Sul ainda compensa ir ao Oeste (0 livres)
    alvo2, _ = r.escolher_base((-22.95, -43.22), agora_sim=3 * 3600, base_atual="sul")
    assert alvo2.id == "oeste"

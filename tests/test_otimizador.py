"""Cenario sintetico: 2 bases, uma ociosa (Sul) e uma sobrecarregada (Oeste). O rodar falso
devolve P90 melhor quanto mais ambulancias a base Oeste tiver."""
from samu_sim.core.modelos import Base
from samu_sim.gerador.demanda import Bairro
from samu_sim.otimizador import Otimizador, diagnosticar, objetivo, propor

BASES = {"sul": Base("sul", "UPA Sul", -22.97, -43.19, "upa"), "oeste": Base("oeste", "UPA Oeste", -22.90, -43.56, "upa")}
BAIRROS = [Bairro("Copacabana", "Sul", -22.97, -43.19, 100_000), Bairro("Campo Grande", "Oeste", -22.90, -43.56, 350_000)]


def rodar_falso(alocacao):
    n_oeste = alocacao.get("oeste", 0)
    p90_oeste = 60 * (40 - 5 * n_oeste)   # 40 min com 0, cai 5 min por ambulancia
    p90_sul = 60 * 10
    chamados = []
    # chamados do Oeste ocupam ambulancias do oeste; do Sul quase nada
    for i in range(20):
        chamados.append({"id": f"o{i}", "zona": "Oeste", "prioridade": "verde", "criado_em": 0, "despachado_em": 30,
                         "liberado_em": 3000, "ambulancia_id": f"amb-o{i % max(n_oeste, 1)}"})
    for i in range(2):
        chamados.append({"id": f"s{i}", "zona": "Sul", "prioridade": "verde", "criado_em": 0, "despachado_em": 5,
                         "liberado_em": 600, "ambulancia_id": "amb-s0"})
    ambulancias = [{"id": f"amb-o{i}", "base_id": "oeste"} for i in range(n_oeste)]
    ambulancias += [{"id": f"amb-s{i}", "base_id": "sul"} for i in range(alocacao.get("sul", 0))]
    p90 = max(p90_oeste, p90_sul)
    return {
        "rodada": {"duracao_sim_seg": 86400},
        "metricas": {"resposta": {"p90": p90}, "pendentes": 0,
                     "por_zona": {"Oeste": {"p90": p90_oeste}, "Sul": {"p90": p90_sul}},
                     "por_prioridade": {"verde": {"p90": p90}}},
        "chamados": chamados, "ambulancias": ambulancias,
    }


def test_objetivo_pondera_vermelhos():
    m = {"resposta": {"p90": 600}, "pendentes": 0, "por_prioridade": {"vermelho": {"p90": 300}, "verde": {"p90": 900}}}
    assert objetivo(m) == (3 * 300 + 1 * 600 + 0.5 * 900) / 60  # amarelo sem chegadas -> usa o global


def test_diagnostico_e_proposta_movem_para_a_zona_pior():
    aloc = {"sul": 4, "oeste": 2}
    diag = diagnosticar(rodar_falso(aloc), BASES, BAIRROS)
    assert diag["utilizacao_base"]["sul"] < diag["utilizacao_base"]["oeste"]
    nova, acoes, mov = propor(diag, aloc, BASES, BAIRROS, set())
    assert nova == {"sul": 3, "oeste": 3} and mov == ("sul", "oeste")
    assert "Oeste" in acoes[0] and "UPA Sul" in acoes[1] and "UPA Oeste" in acoes[2]


def test_otimizador_converge_e_para_quando_nao_ha_mais_movimentos():
    o = Otimizador(rodar_falso, BASES, BAIRROS, {"sul": 4, "oeste": 2})
    hist = o.executar(10)
    assert hist[0].J_anterior is None and hist[0].aceito
    assert all(t.aceito for t in hist[1:4])          # cada movimento melhora 5 min no Oeste
    assert o.alocacao["oeste"] >= 5 and o.alocacao["sul"] <= 1
    assert hist[-1].J < hist[0].J
    assert len(hist) <= 10

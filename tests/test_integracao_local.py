from samu_sim.local import rodar, montar_frota
from samu_sim.gerador.demanda import carregar_bases


def test_montar_frota_distribui_por_base_e_worker():
    bases = carregar_bases("dados/bases.csv")
    frota = montar_frota(bases, n_ambulancias=25, n_workers=2)
    assert len(frota) == 25
    assert frota[0].id == "amb-000" and frota[0].base_id == "base-01" and frota[0].worker_id == "w0"
    assert frota[1].base_id == "base-02" and frota[1].worker_id == "w1"
    assert frota[10].base_id == "base-01"
    assert sum(1 for a in frota if a.worker_id == "w0") == 13


def test_fluxo_completo_em_memoria():
    """gerador -> 2 despachantes -> 2 workers, 6 h simuladas em poucos segundos reais."""
    r = rodar(fator=20000, duracao_sim_seg=6 * 3600, n_ambulancias=30,
              chamados_por_dia=1000, seed=7, visibilidade_seg=0.05)
    m = r["metricas"]
    assert m["total"] >= 40                       # 0-6h e madrugada (~7% do dia)
    assert m["atendidos"] >= 0.6 * m["total"]     # a maioria concluiu o ciclo
    assert m["resposta"]["p90"] is not None and m["resposta"]["p90"] > 0
    # nenhum chamado despachado duas vezes: 1 evento 'despachada' por chamado despachado
    assert r["eventos"].get("despachada", 0) == m["atendidos"] + m["despachados"]
    assert r["eventos"].get("erro_ciclo", 0) == 0
    assert "Oeste" in m["por_zona"]

from samu_sim.local import rodar, montar_frota
from samu_sim.gerador.demanda import carregar_bases


def test_montar_frota_distribui_por_base_e_worker():
    bases = carregar_bases("dados/bases.csv")
    frota = montar_frota(bases, n_ambulancias=len(bases) + 5, n_workers=2)
    assert len(frota) == len(bases) + 5
    assert frota[0].id == "amb-000" and frota[0].base_id == "base-01" and frota[0].worker_id == "w0"
    assert frota[1].base_id == "base-02" and frota[1].worker_id == "w1"
    assert frota[len(bases)].base_id == "base-01"  # round-robin volta ao inicio
    assert sum(1 for a in frota if a.worker_id == "w0") == (len(bases) + 5 + 1) // 2


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


def test_montar_frota_com_alocacao():
    import pytest
    bases = carregar_bases("dados/bases.csv")
    frota = montar_frota(bases, 5, 2, alocacao={"base-05": 3, "base-01": 2})
    assert [a.base_id for a in frota] == ["base-01", "base-01", "base-05", "base-05", "base-05"]
    with pytest.raises(ValueError, match="soma"):
        montar_frota(bases, 6, 2, alocacao={"base-05": 3, "base-01": 2})
    with pytest.raises(ValueError, match="desconhecidas"):
        montar_frota(bases, 1, 2, alocacao={"base-99": 1})


def test_reposicionamento_muda_base_de_ambulancias():
    r = rodar(fator=20000, duracao_sim_seg=6 * 3600, n_ambulancias=40, chamados_por_dia=1000,
              seed=7, visibilidade_seg=0.05, reposicionamento=True)
    assert r["eventos"].get("reposicionada", 0) >= 1
    assert r["eventos"].get("erro_ciclo", 0) == 0
    assert r["rodada"]["reposicionamento"] is True

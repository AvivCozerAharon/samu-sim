from samu_sim.gerador.demanda import carregar_bairros


def test_bairros_do_censo_2022():
    bairros = carregar_bairros("dados/bairros.csv")
    assert len(bairros) == 165
    assert 6_150_000 < sum(b.populacao for b in bairros) < 6_300_000
    assert {b.zona for b in bairros} == {"Centro", "Sul", "Norte", "Oeste", "Barra"}
    for b in bairros:  # bbox do municipio
        assert -23.10 < b.lat < -22.74 and -43.80 < b.lon < -43.09, b.nome


def test_ranking_de_demanda_bate_com_samu_2024():
    bairros = carregar_bairros("dados/bairros.csv")
    top = sorted(bairros, key=lambda b: -b.populacao * b.fator_demanda)[:3]
    assert [b.nome for b in top] == ["Campo Grande", "Santa Cruz", "Centro"]
    assert next(b for b in bairros if b.nome == "Paqueta").fator_demanda == 0

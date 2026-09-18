from collections import Counter
from samu_sim.core.geo import haversine_km
from samu_sim.gerador.demanda import carregar_bairros, carregar_bases, GeradorChamados, PESOS_HORA


def test_carrega_csvs():
    bairros = carregar_bairros("dados/bairros.csv")
    bases = carregar_bases("dados/bases.csv")
    assert len(bairros) == 19 and len(bases) == 10
    assert {b.zona for b in bairros} == {"Centro", "Sul", "Norte", "Oeste", "Barra"}
    assert bases[0].id == "base-01"


def test_pesos_hora_tem_24_valores_com_picos():
    assert len(PESOS_HORA) == 24
    assert PESOS_HORA[9] > PESOS_HORA[3] and PESOS_HORA[19] > PESOS_HORA[14]


def test_gerar_dia_e_deterministico_e_ordenado():
    bairros = carregar_bairros("dados/bairros.csv")
    g1 = GeradorChamados(bairros, seed=42, chamados_por_dia=100).gerar_dia()
    g2 = GeradorChamados(bairros, seed=42, chamados_por_dia=100).gerar_dia()
    assert [c.id for c in g1] == [c.id for c in g2]
    assert [(c.lat, c.criado_em) for c in g1] == [(c.lat, c.criado_em) for c in g2]
    assert len(g1) == 100
    assert all(0 <= c.criado_em < 86400 for c in g1)
    assert [c.criado_em for c in g1] == sorted(c.criado_em for c in g1)


def test_chamados_ficam_perto_do_centroide_e_seguem_populacao():
    bairros = carregar_bairros("dados/bairros.csv")
    por_nome = {b.nome: b for b in bairros}
    chamados = GeradorChamados(bairros, seed=1, chamados_por_dia=3000, raio_km=1.5).gerar_dia()
    for c in chamados[:200]:
        b = por_nome[c.bairro]
        assert haversine_km(b.lat, b.lon, c.lat, c.lon) <= 1.5 + 1e-6
        assert c.zona == b.zona
    contagem = Counter(c.bairro for c in chamados)
    assert contagem["Campo Grande"] > contagem["Centro"]  # 328k vs 41k habitantes


def test_dias_diferentes_ids_diferentes():
    bairros = carregar_bairros("dados/bairros.csv")
    g = GeradorChamados(bairros, seed=1, chamados_por_dia=10)
    assert g.gerar_dia(0)[0].id == "ch-00-00000"
    assert g.gerar_dia(1)[0].id == "ch-01-00000"
    assert g.gerar_dia(1)[0].criado_em >= 86400

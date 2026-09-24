from samu_sim.caos import rodar


def test_rodada_curta_sob_caos_nao_viola_invariantes():
    """Fumaca: 3 h simuladas com duplicatas, atrasos, acks perdidos, processos morrendo ao publicar e
    workers caindo. O scripts/caos.py roda dezenas destas; aqui basta uma, rapida."""
    r = rodar(seed=3, fator=4000, duracao_sim_seg=3 * 3600, quedas_por_worker=1)
    assert r["drenou"], r
    assert r["ok"], r["violacoes"][:5]
    assert r["falhas_injetadas"]["duplicada"] > 0

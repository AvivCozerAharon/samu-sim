from samu_sim.invariantes import verificar


def ev(tipo, amb=None, ch=None, v=None, t=0.0, **k):
    return {"tipo": tipo, "ambulancia_id": amb, "chamado_id": ch, "versao": v, "ts_real": t, "ts_sim": t, **k}


def ok_final(chs=("ch-1",), ambs=("amb-1",)):
    return ([{"id": c, "status": "atendido"} for c in chs],
            [{"id": a, "status": "disponivel", "chamado_id": None} for a in ambs])


CICLO = [ev("despachada", "amb-1", "ch-1", 1, 1), ev("chegou", "amb-1", "ch-1", 3, 2),
         ev("transporte_iniciado", "amb-1", "ch-1", 4, 3), ev("liberada", "amb-1", "ch-1", 5, 4)]


def test_ciclo_normal_passa():
    chs, ambs = ok_final()
    assert verificar(CICLO, chs, ambs, drenado=True)["ok"]


def test_ordem_pela_versao_e_nao_pelo_relogio():
    # os logs de processos diferentes chegam fora de ordem; a versao do registro decide
    chs, ambs = ok_final()
    embaralhado = [CICLO[3], CICLO[1], CICLO[0], CICLO[2]]
    assert verificar(embaralhado, chs, ambs, drenado=True)["ok"]


def test_ambulancia_em_dois_chamados_viola_i1():
    evs = CICLO[:2] + [ev("despachada", "amb-1", "ch-2", 4, 3)]
    chs, ambs = ok_final(("ch-1", "ch-2"))
    r = verificar(evs, chs, ambs, drenado=False)
    assert r["por_invariante"] == {"I1": 1}


def test_reaper_pode_liberar_de_qualquer_estado():
    evs = CICLO[:2] + [ev("reaper_liberou", "amb-1", "ch-1", 4, 3), ev("despachada", "amb-1", "ch-1", 5, 4),
                       ev("chegou", "amb-1", "ch-1", 7, 5), ev("liberada", "amb-1", "ch-1", 8, 6),
                       ev("chamado_devolvido", None, "ch-1", None, 3)]
    chs, ambs = ok_final()
    assert verificar(evs, chs, ambs, drenado=True)["ok"]


def test_conclusao_dupla_viola_i2_e_duas_ambulancias_violam_i5():
    evs = CICLO + [ev("despachada", "amb-2", "ch-1", 1, 1), ev("chegou", "amb-2", "ch-1", 3, 2),
                   ev("liberada", "amb-2", "ch-1", 4, 3)]
    chs, ambs = ok_final(ambs=("amb-1", "amb-2"))
    r = verificar(evs, chs, ambs, drenado=True)
    assert r["por_invariante"] == {"I2": 1, "I5": 1}


def test_depois_de_drenar_nada_pode_ficar_parado():
    chs = [{"id": "ch-1", "status": "despachado"}]
    ambs = [{"id": "amb-1", "status": "no_local", "chamado_id": "ch-1"}]
    r = verificar(CICLO[:2], chs, ambs, drenado=True)
    assert r["por_invariante"] == {"I3": 1, "I4": 1}
    assert verificar(CICLO[:2], chs, ambs, drenado=False)["ok"]  # no meio da rodada, ainda vale

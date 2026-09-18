import json
from scripts.analisar_rodada import analisar, carregar_eventos


def ev(tipo, ts, **k):
    return {"ts_sim": ts, "ts_real": 0, "rodada_id": "r", "servico": "s", "tipo": tipo, **k}


def test_analisar_calcula_metricas_e_detecta_duplicatas():
    eventos = [
        ev("chamado_criado", 0, chamado_id="a", zona="Sul"),
        ev("chamado_criado", 0, chamado_id="b", zona="Oeste"),
        ev("despachada", 10, chamado_id="a", ambulancia_id="1", espera_seg=10),
        ev("despachada", 20, chamado_id="b", ambulancia_id="2", espera_seg=20),
        ev("despachada", 25, chamado_id="b", ambulancia_id="3", espera_seg=25),   # duplicata!
        ev("chegou", 300, chamado_id="a", zona="Sul", resposta_seg=300),
        ev("chegou", 900, chamado_id="b", zona="Oeste", resposta_seg=900),
        ev("reaper_liberou", 950, ambulancia_id="9"),
    ]
    r = analisar(eventos)
    assert r["resposta"]["n"] == 2 and r["resposta"]["p50"] == 600
    assert r["por_zona"]["Oeste"]["p90"] == 900
    assert r["espera_despacho"]["p50"] == 20
    assert r["contagens"]["reaper_liberou"] == 1
    assert r["despachos_duplicados"] == ["b"]
    assert r["chamados_criados"] == 2 and r["chamados_atendidos"] == 2


def test_carregar_eventos_ordena_por_ts_sim(tmp_path):
    (tmp_path / "a.jsonl").write_text(json.dumps(ev("x", 5)) + "\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(json.dumps(ev("y", 1)) + "\n\n", encoding="utf-8")
    assert [e["tipo"] for e in carregar_eventos(tmp_path)] == ["y", "x"]

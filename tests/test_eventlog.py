import json
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria, EventLogJsonl


def test_memoria_registra_campos_comuns():
    r = Relogio(fator=1)
    log = EventLogMemoria(r, servico="teste", rodada_id="r1")
    log.registrar("chamado_criado", chamado_id="ch-1")
    e = log.eventos[0]
    assert e["tipo"] == "chamado_criado" and e["chamado_id"] == "ch-1"
    assert e["servico"] == "teste" and e["rodada_id"] == "r1"
    assert "ts_sim" in e and "ts_real" in e
    assert log.contar("chamado_criado") == 1 and log.contar("outro") == 0


def test_jsonl_escreve_uma_linha_por_evento(tmp_path):
    r = Relogio(fator=1)
    log = EventLogJsonl(tmp_path, r, servico="despachante", rodada_id="r9")
    log.registrar("despachada", chamado_id="ch-1", ambulancia_id="amb-2")
    log.registrar("reserva_falhou", chamado_id="ch-1", ambulancia_id="amb-3")
    log.fechar()
    arquivo = tmp_path / "r9" / "despachante.jsonl"
    linhas = arquivo.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[1])["tipo"] == "reserva_falhou"


def test_enviar_para_s3_usa_chave_por_rodada(tmp_path):
    from pathlib import Path
    from samu_sim.eventlog import enviar_para_s3
    r = Relogio(fator=1)
    log = EventLogJsonl(tmp_path, r, servico="api", rodada_id="r1")
    log.registrar("x")
    log.fechar()
    chamadas = []

    class S3:
        def upload_file(self, arquivo, bucket, chave):
            chamadas.append((Path(arquivo).name, bucket, chave))

    assert enviar_para_s3(tmp_path, "r1", "meu-bucket", "api", s3=S3()) == "r1/api.jsonl"
    assert chamadas == [("api.jsonl", "meu-bucket", "r1/api.jsonl")]
    assert enviar_para_s3(tmp_path, "r1", "", "api", s3=S3()) is None
    assert enviar_para_s3(tmp_path, "r1", "b", "inexistente", s3=S3()) is None

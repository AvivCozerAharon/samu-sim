"""Event log append-only: fonte unica de verdade para metricas e dataset futuro."""
import json
import threading
import time
from pathlib import Path
from typing import Protocol

from samu_sim.core.relogio import Relogio


class EventLog(Protocol):
    def registrar(self, tipo: str, **campos) -> None: ...


class _Base:
    def __init__(self, relogio: Relogio, servico: str, rodada_id: str):
        self._relogio = relogio
        self._servico = servico
        self._rodada_id = rodada_id

    def _montar(self, tipo: str, campos: dict) -> dict:
        return {
            "ts_sim": self._relogio.agora_sim(),
            "ts_real": time.time(),
            "rodada_id": self._rodada_id,
            "servico": self._servico,
            "tipo": tipo,
            **campos,
        }


class EventLogMemoria(_Base):
    def __init__(self, relogio: Relogio, servico: str, rodada_id: str = "local"):
        super().__init__(relogio, servico, rodada_id)
        self.eventos: list[dict] = []
        self._lock = threading.Lock()

    def registrar(self, tipo: str, **campos) -> None:
        with self._lock:
            self.eventos.append(self._montar(tipo, campos))

    def contar(self, tipo: str) -> int:
        with self._lock:
            return sum(1 for e in self.eventos if e["tipo"] == tipo)


class EventLogJsonl(_Base):
    def __init__(self, diretorio: str | Path, relogio: Relogio, servico: str, rodada_id: str):
        super().__init__(relogio, servico, rodada_id)
        pasta = Path(diretorio) / rodada_id
        pasta.mkdir(parents=True, exist_ok=True)
        self._arquivo = open(pasta / f"{servico}.jsonl", "a", encoding="utf-8")
        self._lock = threading.Lock()

    def registrar(self, tipo: str, **campos) -> None:
        linha = json.dumps(self._montar(tipo, campos), ensure_ascii=False, default=str)
        with self._lock:
            self._arquivo.write(linha + "\n")
            self._arquivo.flush()

    def fechar(self) -> None:
        with self._lock:
            if not self._arquivo.closed:
                self._arquivo.close()


def enviar_para_s3(log_dir, rodada_id: str, bucket: str, servico: str, s3=None) -> str | None:
    """Envia <log_dir>/<rodada_id>/<servico>.jsonl para s3://<bucket>/<rodada_id>/<servico>.jsonl.
    Sem bucket configurado ou sem arquivo, nao faz nada (retorna None)."""
    if not bucket:
        return None
    arquivo = Path(log_dir) / rodada_id / f"{servico}.jsonl"
    if not arquivo.exists():
        return None
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    chave = f"{rodada_id}/{servico}.jsonl"
    s3.upload_file(str(arquivo), bucket, chave)
    return chave

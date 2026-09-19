"""Plumbing comum aos servicos: logging JSON, montagem da infra a partir da Config,
relogio sincronizado com a tabela rodada, loop de servico e sinais."""
import json
import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from samu_sim.core.config import Config
from samu_sim.core.modelos import Base
from samu_sim.core.relogio import Relogio
from samu_sim.gerador.demanda import Bairro, carregar_bairros, carregar_bases
from samu_sim.infra.aws import FilaSQS, RepositorioDynamo, cliente_sqs, recurso_dynamo
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio


class _FormatadorJson(logging.Formatter):
    def __init__(self, servico: str):
        super().__init__()
        self._servico = servico

    def format(self, r: logging.LogRecord) -> str:
        return json.dumps({"ts": time.time(), "nivel": r.levelname, "servico": self._servico,
                           "msg": r.getMessage()}, ensure_ascii=False)


def configurar_logging(servico: str) -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_FormatadorJson(servico))
    logging.basicConfig(level=logging.INFO, handlers=[h], force=True)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@dataclass
class Infra:
    repo: Repositorio
    fila_chamados: dict[str, Fila]  # por prioridade
    filas_eventos: dict[str, Fila]
    bases: dict[str, Base]
    bairros: list[Bairro]


def montar_infra(cfg: Config) -> Infra:
    sqs = cliente_sqs(cfg)
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)

    def fila(nome: str) -> FilaSQS:
        return FilaSQS(sqs, sqs.get_queue_url(QueueName=nome)["QueueUrl"])

    filas_eventos = {f"w{k}": fila(cfg.fila_eventos(f"w{k}")) for k in range(cfg.n_workers)}
    dados = Path(cfg.dados_dir)
    bases = {b.id: b for b in carregar_bases(dados / "bases.csv")}
    filas_chamados = {p: fila(nome) for p, nome in cfg.filas_chamados().items()}
    return Infra(repo, filas_chamados, filas_eventos, bases, carregar_bairros(dados / "bairros.csv"))


def relogio_da_rodada(repo: Repositorio, agora_real=time.time, espera_max_seg: float = 60.0,
                      mono=time.monotonic) -> Relogio:
    fim = time.monotonic() + espera_max_seg
    while True:
        rodada = repo.obter_rodada()
        if rodada is not None:
            break
        if time.monotonic() > fim:
            raise RuntimeError("tabela rodada vazia: rode o bootstrap")
        time.sleep(1)
    r = Relogio(agora_real=agora_real, mono=mono)
    r.sincronizar(rodada.inicio_real, rodada.inicio_sim, rodada.fator)
    return r


class SincronizadorRelogio:
    """Rele a tabela rodada periodicamente e aplica mudancas de checkpoint/fator ao relogio."""

    def __init__(self, relogio: Relogio, repo: Repositorio, intervalo_seg: float,
                 parar: threading.Event, ao_mudar=None):
        self._relogio = relogio
        self._repo = repo
        self._intervalo = intervalo_seg
        self._parar = parar
        self._ao_mudar = ao_mudar
        self._ultimo: tuple[float, float, float] | None = None

    def sincronizar_uma_vez(self) -> bool:
        rodada = self._repo.obter_rodada()
        if rodada is None:
            return False
        chave = (rodada.inicio_real, rodada.inicio_sim, rodada.fator)
        if self._ultimo is None:
            self._ultimo = chave
            return False
        if chave == self._ultimo:
            return False
        self._ultimo = chave
        self._relogio.sincronizar(*chave)
        logging.info(f"relogio sincronizado: fator={rodada.fator} inicio_sim={rodada.inicio_sim:.0f}")
        if self._ao_mudar:
            self._ao_mudar(rodada)
        return True

    def iniciar(self) -> threading.Thread:
        def loop():
            self.sincronizar_uma_vez()
            while not self._parar.wait(self._intervalo):
                try:
                    self.sincronizar_uma_vez()
                except Exception as e:  # noqa: BLE001
                    logging.warning(f"falha ao sincronizar relogio: {e!r}")
        t = threading.Thread(target=loop, name="sync-relogio", daemon=True)
        t.start()
        return t


def loop_servico(processar, parar: threading.Event, ocioso_seg: float = 0.05) -> None:
    while not parar.is_set():
        try:
            if processar() == 0 and ocioso_seg > 0:
                time.sleep(ocioso_seg)
        except Exception as e:  # noqa: BLE001 - loga e continua; a fila reentrega
            logging.exception(f"erro no loop de servico: {e!r}")
            time.sleep(1)


def instalar_sinais(parar: threading.Event) -> None:
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, lambda *_: parar.set())
        except ValueError:
            pass  # fora da main thread (testes)

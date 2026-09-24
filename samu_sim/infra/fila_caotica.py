"""Fila caotica: envolve uma Fila e injeta, com semente, as falhas que o SQS standard e os
processos permitem - mensagem duplicada, atrasada, fora de ordem, ack perdido e processo que
morre ao publicar. Mesma interface da Fila: o codigo do sistema nao sabe que esta sob caos."""
import random
import threading
import time
from dataclasses import dataclass, field

from samu_sim.infra.fila import Fila, Mensagem


class FalhaInjetada(Exception):
    """O processo 'morreu' no meio da operacao: quem chamou nao continua o que ia fazer."""


@dataclass
class Caos:
    duplicar: float = 0.10         # publica uma segunda copia (at-least-once)
    atrasar: float = 0.10          # a mensagem so fica visivel depois de um atraso
    atraso_max_seg: float = 0.3    # segundos reais
    reordenar: bool = True         # o lote recebido vem embaralhado
    perder_ack: float = 0.05       # consumidor morreu depois de processar e antes do ack
    falhar_publicar: float = 0.02  # processo morreu ao publicar (a mensagem nao sai)
    ligado: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self):
        self.ligado.set()


class FilaCaotica:
    def __init__(self, base: Fila, caos: Caos, seed: int = 0, agora=time.monotonic):
        self._base = base
        self._caos = caos
        self._rng = random.Random(seed)
        self._agora = agora
        self._atrasadas: list[tuple[float, dict]] = []
        self._lock = threading.Lock()
        self.injetadas = {"duplicada": 0, "atrasada": 0, "ack_perdido": 0, "publicacao_falhou": 0}

    def _sorteio(self, p: float) -> bool:
        if not self._caos.ligado.is_set() or p <= 0:
            return False
        with self._lock:
            return self._rng.random() < p

    def publicar(self, corpo: dict) -> None:
        if self._sorteio(self._caos.falhar_publicar):
            self.injetadas["publicacao_falhou"] += 1
            raise FalhaInjetada("processo morreu ao publicar")
        copias = 2 if self._sorteio(self._caos.duplicar) else 1
        if copias == 2:
            self.injetadas["duplicada"] += 1
        for _ in range(copias):
            if self._sorteio(self._caos.atrasar):
                self.injetadas["atrasada"] += 1
                with self._lock:
                    atraso = self._rng.uniform(0, self._caos.atraso_max_seg)
                    self._atrasadas.append((self._agora() + atraso, dict(corpo)))
            else:
                self._base.publicar(corpo)

    def _liberar_atrasadas(self) -> None:
        agora = self._agora()
        with self._lock:
            prontas = [c for t, c in self._atrasadas if t <= agora]
            self._atrasadas = [(t, c) for t, c in self._atrasadas if t > agora]
        for c in prontas:
            self._base.publicar(c)

    def receber(self, max_msgs: int = 10) -> list[Mensagem]:
        self._liberar_atrasadas()
        msgs = self._base.receber(max_msgs)
        if self._caos.reordenar and self._caos.ligado.is_set() and len(msgs) > 1:
            with self._lock:
                self._rng.shuffle(msgs)
        return msgs

    def ack(self, msg: Mensagem) -> None:
        if self._sorteio(self._caos.perder_ack):
            self.injetadas["ack_perdido"] += 1
            return  # a mensagem volta depois do visibility timeout
        self._base.ack(msg)

    def adiar(self, msg: Mensagem, seg: float) -> None:
        self._base.adiar(msg, seg)

    def tamanho(self) -> int:
        self._liberar_atrasadas()
        with self._lock:
            pendentes = len(self._atrasadas)
        return self._base.tamanho() + pendentes

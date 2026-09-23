"""Fila com semantica de SQS standard: at-least-once, visibility timeout, ack explicito."""
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Mensagem:
    id: str
    corpo: dict
    handle: object = None


class Fila(Protocol):
    def publicar(self, corpo: dict) -> None: ...
    def receber(self, max_msgs: int = 10) -> list[Mensagem]: ...
    def ack(self, msg: Mensagem) -> None: ...
    def adiar(self, msg: Mensagem, seg: float) -> None: ...


@dataclass
class _Item:
    msg: Mensagem
    visivel_em: float = 0.0


class FilaMemoria:
    def __init__(self, visibilidade_seg: float = 30.0, agora=time.monotonic):
        self._visibilidade = visibilidade_seg
        self._agora = agora
        self._itens: list[_Item] = []
        self._lock = threading.Lock()

    def publicar(self, corpo: dict) -> None:
        with self._lock:
            self._itens.append(_Item(Mensagem(id=uuid.uuid4().hex, corpo=dict(corpo))))

    def receber(self, max_msgs: int = 10) -> list[Mensagem]:
        agora = self._agora()
        entregues: list[Mensagem] = []
        with self._lock:
            for item in self._itens:
                if len(entregues) >= max_msgs:
                    break
                if item.visivel_em <= agora:
                    item.visivel_em = agora + self._visibilidade
                    entregues.append(Mensagem(item.msg.id, dict(item.msg.corpo), handle=item.msg.id))
        return entregues

    def ack(self, msg: Mensagem) -> None:
        with self._lock:
            self._itens = [i for i in self._itens if i.msg.id != msg.id]

    def adiar(self, msg: Mensagem, seg: float) -> None:
        """Como ChangeMessageVisibility: a mensagem em voo volta a ficar visivel em `seg`."""
        with self._lock:
            for item in self._itens:
                if item.msg.id == msg.id:
                    item.visivel_em = self._agora() + seg
                    return

    def tamanho(self) -> int:
        with self._lock:
            return len(self._itens)

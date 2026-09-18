"""Relogio simulado: agora_sim = inicio_sim + (agora_real - inicio_real) * fator.

Mudar o fator grava um novo checkpoint, entao o tempo simulado nunca salta.
dormir_sim dorme em pedacos de no maximo PEDACO_MAX_REAL segundos reais para
que uma mudanca de fator feita por outra thread seja respeitada.
"""
import threading
import time

PEDACO_MAX_REAL = 0.5


class Relogio:
    def __init__(self, fator: float = 1.0, inicio_sim: float = 0.0,
                 agora_real=time.monotonic, dormir_real=time.sleep):
        self._agora_real = agora_real
        self._dormir_real = dormir_real
        self._lock = threading.Lock()
        self._fator = float(fator)
        self._inicio_sim = float(inicio_sim)
        self._inicio_real = agora_real()

    @property
    def fator(self) -> float:
        return self._fator

    def checkpoint(self) -> tuple[float, float]:
        with self._lock:
            return self._inicio_real, self._inicio_sim

    def agora_sim(self) -> float:
        with self._lock:
            return self._inicio_sim + (self._agora_real() - self._inicio_real) * self._fator

    def definir_fator(self, novo: float) -> None:
        with self._lock:
            agora_real = self._agora_real()
            self._inicio_sim = self._inicio_sim + (agora_real - self._inicio_real) * self._fator
            self._inicio_real = agora_real
            self._fator = float(novo)

    def dormir_sim(self, segundos: float) -> None:
        alvo = self.agora_sim() + segundos
        while True:
            resta_sim = alvo - self.agora_sim()
            if resta_sim <= 0:
                return
            self._dormir_real(min(resta_sim / self._fator, PEDACO_MAX_REAL))

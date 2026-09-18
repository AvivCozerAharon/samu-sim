"""Relogio simulado: agora_sim = inicio_sim + (agora_real - inicio_real) * fator.

O checkpoint (inicio_real, inicio_sim, fator) e compartilhado entre processos via
a tabela rodada e usa wall-clock (time.time). Mas wall-clock nao e monotonico:
NTP e VMs (Docker Desktop/WSL2) dao saltos de segundos ou minutos. Por isso, ao
sincronizar, o relogio captura o par (wall, monotonico) e dali em diante avanca
so com o monotonico. Um salto do wall-clock so afeta quem re-sincronizar.

Mudar o fator grava um novo checkpoint, entao o tempo simulado nunca salta.
dormir_sim dorme em pedacos de no maximo PEDACO_MAX_REAL segundos reais para
que uma mudanca de fator feita por outra thread seja respeitada.
"""
import threading
import time

PEDACO_MAX_REAL = 0.5


class Relogio:
    def __init__(self, fator: float = 1.0, inicio_sim: float = 0.0,
                 agora_real=time.monotonic, dormir_real=time.sleep, mono=None):
        self._agora_real = agora_real
        self._mono = mono or agora_real
        self._dormir_real = dormir_real
        self._lock = threading.Lock()
        self._fator = float(fator)
        self._inicio_sim = float(inicio_sim)
        self._inicio_real = agora_real()
        self._wall_sync = self._inicio_real
        self._mono_sync = self._mono()

    @property
    def fator(self) -> float:
        return self._fator

    @property
    def pausado(self) -> bool:
        return self._fator == 0

    def checkpoint(self) -> tuple[float, float]:
        with self._lock:
            return self._inicio_real, self._inicio_sim

    def _decorrido_real(self) -> float:
        """Segundos reais desde inicio_real: offset fixo do wall-clock na sincronizacao
        + avanco monotonico desde entao."""
        return (self._wall_sync - self._inicio_real) + (self._mono() - self._mono_sync)

    def agora_sim(self) -> float:
        with self._lock:
            return self._inicio_sim + self._decorrido_real() * self._fator

    def definir_fator(self, novo: float) -> None:
        with self._lock:
            self._inicio_sim = self._inicio_sim + self._decorrido_real() * self._fator
            self._inicio_real = self._agora_real()
            self._wall_sync = self._inicio_real
            self._mono_sync = self._mono()
            self._fator = float(novo)

    def sincronizar(self, inicio_real: float, inicio_sim: float, fator: float) -> None:
        """Substitui o checkpoint (usado pelos servicos ao reler a tabela rodada)."""
        with self._lock:
            self._inicio_real = float(inicio_real)
            self._inicio_sim = float(inicio_sim)
            self._fator = float(fator)
            self._wall_sync = self._agora_real()
            self._mono_sync = self._mono()

    def dormir_sim(self, segundos: float) -> None:
        alvo = self.agora_sim() + segundos
        while True:
            resta_sim = alvo - self.agora_sim()
            if resta_sim <= 0:
                return
            fator = self._fator
            if fator <= 0:  # pausado: espera sem dividir por zero
                self._dormir_real(PEDACO_MAX_REAL)
                continue
            self._dormir_real(min(resta_sim / fator, PEDACO_MAX_REAL))

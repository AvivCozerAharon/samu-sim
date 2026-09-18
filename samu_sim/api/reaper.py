"""Reaper: libera ambulancias cujo worker parou de bater heartbeat e devolve o
chamado (se nao atendido) para a fila. Roda periodicamente dentro da api."""
import time

from samu_sim.core.modelos import Base, StatusAmbulancia, StatusChamado
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio


class Reaper:
    def __init__(self, repo: Repositorio, fila_chamados: Fila, bases: dict[str, Base],
                 eventlog: EventLog, timeout_seg: float = 120.0, agora_real=time.time):
        self._repo = repo
        self._fila = fila_chamados
        self._bases = bases
        self._log = eventlog
        self._timeout = timeout_seg
        self._agora_real = agora_real

    def executar_uma_vez(self) -> int:
        agora = self._agora_real()
        liberadas = 0
        for a in self._repo.listar_ambulancias():
            if a.status == StatusAmbulancia.DISPONIVEL:
                continue
            idade = agora - a.heartbeat_em
            if idade <= self._timeout:
                continue
            base = self._bases[a.base_id]
            try:
                self._repo.liberar_ambulancia(a.id, a.versao, base.lat, base.lon)
            except ConflitoVersao:
                continue  # alguem mexeu nela agora; reavalia na proxima passada
            liberadas += 1
            self._log.registrar("reaper_liberou", ambulancia_id=a.id, chamado_id=a.chamado_id,
                                worker_id=a.worker_id, idade_seg=idade, status_anterior=str(a.status))
            if a.chamado_id:
                self._devolver_chamado(a.chamado_id)
        return liberadas

    def _devolver_chamado(self, chamado_id: str) -> None:
        c = self._repo.obter_chamado(chamado_id)
        if c is None or c.status == StatusChamado.ATENDIDO:
            return
        c.status = StatusChamado.PENDENTE
        c.ambulancia_id = None
        c.despachado_em = None
        c.tentativas += 1
        self._repo.salvar_chamado(c)
        self._fila.publicar({"chamado_id": c.id, "lat": c.lat, "lon": c.lon,
                             "bairro": c.bairro, "zona": c.zona, "criado_em": c.criado_em})

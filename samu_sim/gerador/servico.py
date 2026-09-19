"""Servico gerador: publica os chamados de um dia no ritmo do relogio simulado."""
import threading

from samu_sim.core.modelos import Chamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio

ESPERA_MAX_REAL = 0.5  # dorme no maximo isso (em segundos reais) por vez para checar `parar`
TOLERANCIA_ATRASO_SIM = 60.0  # chamados ate 1 min sim no passado ainda sao publicados


class ServicoGerador:
    def __init__(self, chamados: list[Chamado], fila: Fila, repo: Repositorio,
                 relogio: Relogio, eventlog: EventLog):
        self._chamados = chamados
        self._fila = fila
        self._repo = repo
        self._relogio = relogio
        self._log = eventlog

    def executar(self, parar: threading.Event) -> int:
        # chamados ja no passado (gerador subiu atrasado ou foi reiniciado no meio da
        # rodada) sao descartados: publica-los inflaria a espera com atraso ficticio
        agora = self._relogio.agora_sim()
        pendentes = [c for c in self._chamados if c.criado_em >= agora - TOLERANCIA_ATRASO_SIM]
        pulados = len(self._chamados) - len(pendentes)
        if pulados:
            self._log.registrar("chamados_pulados", quantidade=pulados, agora_sim=agora)
        publicados = 0
        for c in pendentes:
            while not parar.is_set() and self._relogio.agora_sim() < c.criado_em:
                resta_sim = c.criado_em - self._relogio.agora_sim()
                self._relogio.dormir_sim(min(resta_sim, ESPERA_MAX_REAL * self._relogio.fator))
            if parar.is_set():
                break
            self._repo.salvar_chamado(c)
            self._fila.publicar({
                "chamado_id": c.id, "lat": c.lat, "lon": c.lon,
                "bairro": c.bairro, "zona": c.zona, "criado_em": c.criado_em,
            })
            self._log.registrar("chamado_criado", chamado_id=c.id, bairro=c.bairro, zona=c.zona)
            publicados += 1
        return publicados

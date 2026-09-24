"""Servico gerador: publica os chamados de um dia no ritmo do relogio simulado."""
import threading

from samu_sim.core.modelos import PRIORIDADES, Chamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio

ESPERA_MAX_REAL = 0.5  # dorme no maximo isso (em segundos reais) por vez para checar `parar`
TOLERANCIA_ATRASO_SIM = 60.0  # chamados ate 1 min sim no passado ainda sao publicados


class ServicoGerador:
    def __init__(self, chamados: list[Chamado], filas: "Fila | dict[str, Fila]", repo: Repositorio,
                 relogio: Relogio, eventlog: EventLog):
        self._chamados = chamados
        # uma fila por prioridade; uma Fila unica (testes/legado) serve para todas
        self._filas = filas if isinstance(filas, dict) else {p: filas for p in PRIORIDADES}
        self._repo = repo
        self._relogio = relogio
        self._log = eventlog

    def executar(self, parar: threading.Event) -> int:
        agora = self._relogio.agora_sim()
        retomando = bool(self._chamados) and self._repo.obter_chamado(self._chamados[0].id) is not None
        if retomando:
            # reinicio no meio da rodada: os chamados atrasados aconteceram de verdade e tem que
            # entrar (atrasados); os que ja existem sao pulados pelo criar_chamado
            pendentes = list(self._chamados)
        else:
            # primeira subida atrasada (ex.: build da imagem na EC2): o que ja passou nao e
            # publicado, senao a espera sairia inflada com um atraso que nao existiu
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
            if not self._repo.criar_chamado(c):
                continue  # ja existia: este gerador reiniciou; nunca sobrescreve um chamado em andamento
            self._filas[c.prioridade].publicar({
                "chamado_id": c.id, "lat": c.lat, "lon": c.lon, "prioridade": c.prioridade,
                "bairro": c.bairro, "zona": c.zona, "criado_em": c.criado_em,
            })
            self._repo.marcar_publicado(c.id)  # outbox: se morrer antes daqui, o reaper republica
            self._log.registrar("chamado_criado", chamado_id=c.id, bairro=c.bairro, zona=c.zona,
                                prioridade=c.prioridade, tipo_chamado=c.tipo)
            publicados += 1
        return publicados

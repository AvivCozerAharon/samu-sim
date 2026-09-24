"""Despachante: consome chamados, aplica a politica e reserva a ambulancia
com lock otimista. Idempotente por chamado (mensagens duplicadas sao ignoradas)."""
import time

from samu_sim.core.modelos import PRIORIDADES, Ambulancia, StatusAmbulancia, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila, Mensagem
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio
from samu_sim.politicas import Politica
from samu_sim.roteador import Roteador


class Despachante:
    def __init__(self, fila_chamados: "Fila | dict[str, Fila]", filas_eventos: dict[str, Fila], repo: Repositorio,
                 politica: Politica, roteador: Roteador, relogio: Relogio, eventlog: EventLog,
                 cache_seg: float = 2.0, agora_real=time.time, reentrega_seg: float = 2.0):
        self._agora_real = agora_real
        # sem ambulancia: a mensagem volta em `reentrega_seg` (nao no visibility timeout de 30 s)
        # e, ate la, este despachante nao desce para prioridades menores (sem inversao)
        self._reentrega_seg = reentrega_seg
        self._segurar_ate: dict[str, float] = {}
        # filas por prioridade (vermelho -> amarelo -> verde); uma Fila unica serve para todas
        self._filas = (fila_chamados if isinstance(fila_chamados, dict)
                       else {p: fila_chamados for p in PRIORIDADES})
        self._fila_atual: Fila = self._filas[PRIORIDADES[0]]
        self._filas_eventos = filas_eventos
        self._repo = repo
        self._politica = politica
        self._roteador = roteador
        self._relogio = relogio
        self._log = eventlog
        self._cache_seg = cache_seg
        self._cache: tuple[float, list[Ambulancia]] | None = None

    def processar_lote(self) -> int:
        """So desce de nivel (vermelho -> amarelo -> verde) quando a fila acima esta vazia
        e nenhum chamado dela esta esperando ambulancia."""
        vistas: set[int] = set()
        for pri in PRIORIDADES:
            fila = self._filas[pri]
            if id(fila) in vistas:  # mesma Fila para varias prioridades (modo legado)
                continue
            vistas.add(id(fila))
            msgs = fila.receber()
            if msgs:
                self._fila_atual = fila
                return sum(1 for msg in msgs if self.processar(msg))
            if self._segurar_ate.get(pri, 0.0) > time.monotonic():
                return 0  # ha um chamado desta prioridade voltando em instantes: nao atende os menores
        return 0

    def processar(self, msg: Mensagem) -> bool:
        chamado_id = msg.corpo["chamado_id"]
        chamado = self._repo.obter_chamado(chamado_id)
        if chamado is None:
            # gerador salva antes de publicar; se nao existe, mensagem invalida -> descarta
            self._log.registrar("chamado_desconhecido", chamado_id=chamado_id)
            self._fila_atual.ack(msg)
            return True
        if chamado.status != StatusChamado.PENDENTE:
            self._log.registrar("chamado_ja_despachado", chamado_id=chamado_id)
            self._fila_atual.ack(msg)
            return True

        destino = (chamado.lat, chamado.lon)
        candidatas = self._politica.escolher(chamado, self._disponiveis(), self._roteador)
        self._log.registrar("despacho_tentado", chamado_id=chamado_id, candidatas=len(candidatas))
        for amb in candidatas:
            try:
                # heartbeat na reserva: sem isso o reaper veria heartbeat_em=0 e liberaria na hora
                reservada = self._repo.reservar_ambulancia(amb.id, amb.versao, chamado_id,
                                                           heartbeat_em=self._agora_real())
            except ConflitoVersao:
                self._log.registrar("reserva_falhou", chamado_id=chamado_id, ambulancia_id=amb.id)
                self._invalidar_cache()
                continue
            eta = self._roteador.eta((reservada.lat, reservada.lon), destino)
            agora = self._relogio.agora_sim()
            chamado.status = StatusChamado.DESPACHADO
            chamado.ambulancia_id = reservada.id
            chamado.despachado_em = agora
            chamado.chegada_prevista_em = agora + eta
            try:
                # condicional: se outro despachante pegou a mesma mensagem duplicada e ja
                # despachou este chamado, desfaz a reserva em vez de mandar duas ambulancias
                self._repo.salvar_chamado_se(chamado, StatusChamado.PENDENTE, None)
            except ConflitoVersao:
                try:
                    self._repo.liberar_ambulancia(reservada.id, reservada.versao, reservada.lat, reservada.lon)
                except ConflitoVersao:
                    pass
                self._log.registrar("despacho_duplicado_evitado", chamado_id=chamado_id,
                                    ambulancia_id=reservada.id)
                self._invalidar_cache()
                self._fila_atual.ack(msg)
                return True
            # o evento descreve a escrita que acabou de acontecer, entao vem antes de publicar: se o
            # processo morrer na publicacao, o log continua fiel ao estado (e o reaper recupera)
            self._log.registrar("despachada", chamado_id=chamado_id, ambulancia_id=reservada.id,
                                versao=reservada.versao,
                                eta_seg=eta, espera_seg=agora - chamado.criado_em,
                                prioridade=chamado.prioridade, zona=chamado.zona)
            self._filas_eventos[reservada.worker_id].publicar({
                "tipo": "despachada", "chamado_id": chamado_id,
                "ambulancia_id": reservada.id, "eta_seg": eta, "ts_sim": agora,
            })
            self._invalidar_cache()
            self._fila_atual.ack(msg)
            return True

        # nenhuma candidata reservavel: nao da ack; a mensagem volta em reentrega_seg
        self._log.registrar("sem_ambulancia", chamado_id=chamado_id, prioridade=chamado.prioridade)
        self._fila_atual.adiar(msg, self._reentrega_seg)
        self._segurar_ate[chamado.prioridade] = time.monotonic() + self._reentrega_seg
        return False

    def _disponiveis(self) -> list[Ambulancia]:
        agora = time.monotonic()
        if self._cache and agora - self._cache[0] < self._cache_seg:
            return self._cache[1]
        lista = self._repo.listar_ambulancias(StatusAmbulancia.DISPONIVEL)
        self._cache = (agora, lista)
        return lista

    def _invalidar_cache(self) -> None:
        self._cache = None

"""Worker de ambulancias: consome eventos 'despachada' das suas ambulancias e
simula o ciclo a_caminho -> no_local -> retornando -> disponivel. Cada transicao
e condicional em (status, versao); duplicatas/atrasos sao rejeitados."""
import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait

from samu_sim.core.modelos import Base, StatusAmbulancia as SA, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio
from samu_sim.roteador import Roteador


class WorkerAmbulancia:
    def __init__(self, worker_id: str, fila_eventos: Fila, repo: Repositorio, relogio: Relogio,
                 roteador: Roteador, bases: dict[str, Base], eventlog: EventLog,
                 atendimento_seg: tuple[float, float] = (600, 1200),
                 max_simultaneas: int = 50, seed: int = 0, agora_real=time.time):
        self.worker_id = worker_id
        self._agora_real = agora_real
        self._fila = fila_eventos
        self._repo = repo
        self._relogio = relogio
        self._roteador = roteador
        self._bases = bases
        self._log = eventlog
        self._atendimento = atendimento_seg
        self._rng = random.Random(f"{seed}-{worker_id}")
        self._pool = ThreadPoolExecutor(max_workers=max_simultaneas, thread_name_prefix=worker_id)
        self._em_voo: set[Future] = set()
        self._lock = threading.Lock()

    def processar_lote(self) -> int:
        n = 0
        for msg in self._fila.receber():
            corpo = msg.corpo
            amb_id, ch_id, eta = corpo["ambulancia_id"], corpo["chamado_id"], float(corpo["eta_seg"])
            a = self._repo.obter_ambulancia(amb_id)
            try:
                if a is None:
                    raise ConflitoVersao("ambulancia inexistente")
                if a.chamado_id != ch_id:
                    # mensagem antiga: o reaper liberou e a ambulancia ja foi reatribuida
                    raise ConflitoVersao(f"reservada para {a.chamado_id}, msg e de {ch_id}")
                self._repo.transicionar(amb_id, SA.RESERVADA, SA.A_CAMINHO, a.versao,
                                        heartbeat_em=self._agora_real())
            except ConflitoVersao as e:
                self._log.registrar("transicao_rejeitada", ambulancia_id=amb_id, chamado_id=ch_id,
                                    de="reservada", para="a_caminho", motivo=str(e))
                self._fila.ack(msg)
                n += 1
                continue
            self._fila.ack(msg)
            n += 1
            fut = self._pool.submit(self._ciclo, amb_id, ch_id, eta)
            with self._lock:
                self._em_voo.add(fut)
            fut.add_done_callback(self._concluido)
        return n

    def aguardar_ciclos(self, timeout: float | None = None) -> None:
        with self._lock:
            pendentes = set(self._em_voo)
        wait(pendentes, timeout=timeout)

    def bater_heartbeat(self) -> int:
        """Atualiza heartbeat_em (tempo real) das ambulancias ativas deste worker."""
        ts = self._agora_real()
        n = 0
        for a in self._repo.listar_ambulancias(worker_id=self.worker_id):
            if a.status != SA.DISPONIVEL:
                self._repo.atualizar_heartbeat(a.id, ts)
                n += 1
        return n

    def iniciar_heartbeat(self, intervalo_seg: float, parar: threading.Event) -> threading.Thread:
        def loop():
            while not parar.wait(intervalo_seg):
                try:
                    self.bater_heartbeat()
                except Exception as e:  # noqa: BLE001 - heartbeat nunca derruba o worker
                    self._log.registrar("erro_heartbeat", worker_id=self.worker_id, erro=repr(e))
        t = threading.Thread(target=loop, name=f"heartbeat-{self.worker_id}", daemon=True)
        t.start()
        return t

    def encerrar(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _concluido(self, fut: Future) -> None:
        with self._lock:
            self._em_voo.discard(fut)
        exc = fut.exception()
        if exc:
            self._log.registrar("erro_ciclo", worker_id=self.worker_id, erro=repr(exc))

    def _transicionar(self, amb_id: str, de: SA, para: SA, **campos):
        a = self._repo.obter_ambulancia(amb_id)
        return self._repo.transicionar(amb_id, de, para, a.versao,
                                       heartbeat_em=self._agora_real(), **campos)

    def _ciclo(self, amb_id: str, ch_id: str, eta: float) -> None:
        chamado = self._repo.obter_chamado(ch_id)
        self._relogio.dormir_sim(eta)

        agora = self._relogio.agora_sim()
        self._transicionar(amb_id, SA.A_CAMINHO, SA.NO_LOCAL, lat=chamado.lat, lon=chamado.lon)
        chamado.chegada_em = agora
        self._repo.salvar_chamado(chamado)
        self._log.registrar("chegou", ambulancia_id=amb_id, chamado_id=ch_id, zona=chamado.zona,
                            resposta_seg=agora - chamado.criado_em)

        self._relogio.dormir_sim(self._rng.uniform(*self._atendimento))

        agora = self._relogio.agora_sim()
        chamado.liberado_em = agora
        chamado.status = StatusChamado.ATENDIDO
        self._repo.salvar_chamado(chamado)
        a = self._transicionar(amb_id, SA.NO_LOCAL, SA.RETORNANDO)
        self._log.registrar("liberada", ambulancia_id=amb_id, chamado_id=ch_id)

        base = self._bases[a.base_id]
        self._relogio.dormir_sim(self._roteador.eta((a.lat, a.lon), (base.lat, base.lon)))
        self._transicionar(amb_id, SA.RETORNANDO, SA.DISPONIVEL,
                           lat=base.lat, lon=base.lon, chamado_id=None)

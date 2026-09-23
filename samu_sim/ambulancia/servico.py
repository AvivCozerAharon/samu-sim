"""Worker de ambulancias: consome eventos 'despachada' das suas ambulancias e
simula o ciclo a_caminho -> no_local -> retornando -> disponivel. Cada transicao
e condicional em (status, versao); duplicatas/atrasos sao rejeitados."""
import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait

from samu_sim.core.geo import haversine_km
from samu_sim.core.modelos import Base, StatusAmbulancia as SA, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio
from samu_sim.roteador import Roteador


class _Derrubado(Exception):
    """O processo do worker 'morreu' (caos): o ciclo em voo some sem deixar rastro."""


PASSO_RETORNO_SIM = 30.0  # atualiza a posicao no retorno a cada 30 s simulados (ou 1/20 do trajeto)


class WorkerAmbulancia:
    def __init__(self, worker_id: str, fila_eventos: Fila, repo: Repositorio, relogio: Relogio,
                 roteador: Roteador, bases: dict[str, Base], eventlog: EventLog,
                 atendimento_seg: tuple[float, float] = (1200, 1800),
                 entrega_seg: tuple[float, float] = (480, 900),
                 max_simultaneas: int = 50, seed: int = 0, agora_real=time.time,
                 reposicionador=None):
        self.worker_id = worker_id
        self._reposicionador = reposicionador  # None = volta sempre a base de origem
        self._agora_real = agora_real
        self._fila = fila_eventos
        self._repo = repo
        self._relogio = relogio
        self._roteador = roteador
        self._bases = bases
        self._log = eventlog
        self._atendimento = atendimento_seg  # no local (literatura SAMU: ~20-30 min)
        self._entrega = entrega_seg          # passagem do paciente no hospital (~8-15 min)
        self._hospitais = [b for b in bases.values() if b.tipo == "hospital"]
        self._rng = random.Random(f"{seed}-{worker_id}")
        self._pool = ThreadPoolExecutor(max_workers=max_simultaneas, thread_name_prefix=worker_id)
        self._em_voo: set[Future] = set()
        self._lock = threading.Lock()
        self._morto = threading.Event()  # derrubar()/reviver(): simula a queda do processo
        self._pausado = threading.Event()  # pausar()/retomar(): processo congelado (GC, VM parada)
        # ambulancias com ciclo em voo neste processo. O heartbeat so fala por elas: um worker que
        # reiniciou nao pode manter vivas as ambulancias cujo ciclo morreu com o processo anterior
        self._ativas: set[str] = set()

    def derrubar(self) -> None:
        """Simula a morte do processo: para de consumir, de bater heartbeat e os ciclos em voo
        morrem na proxima espera. O estado no banco fica como estava (e o reaper que resolva)."""
        self._morto.set()
        with self._lock:
            self._ativas.clear()  # a memoria do processo morreu junto

    def reviver(self) -> None:
        """Simula o restart do container: volta a consumir; a memoria dos ciclos antigos se perdeu."""
        self._morto.clear()

    def pausar(self) -> None:
        """Simula o processo congelado (pausa de GC, VM parada): nao consome, nao bate heartbeat e
        os ciclos param onde estao - mas com a memoria intacta. Ao retomar, cada ciclo continua de
        onde parou, com a versao que tinha visto: se o reaper deu a ambulancia a outro nesse meio
        tempo, a proxima escrita dele falha (ciclo_obsoleto)."""
        self._pausado.set()

    def retomar(self) -> None:
        self._pausado.clear()

    @property
    def estado(self) -> str:
        return "caido" if self._morto.is_set() else "pausado" if self._pausado.is_set() else "vivo"

    def ciclos_em_voo(self) -> int:
        with self._lock:
            return len(self._ativas)

    def _dormir(self, segundos: float) -> None:
        """Espera em pedacos de ate 0,5 s real para que um derrubar() pare o ciclo na hora."""
        alvo = self._relogio.agora_sim() + segundos
        while True:
            if self._morto.is_set():
                raise _Derrubado()
            if self._pausado.is_set():
                time.sleep(0.05)  # congelado: o relogio anda, o ciclo nao
                continue
            resta = alvo - self._relogio.agora_sim()
            if resta <= 0:
                return
            self._relogio.dormir_sim(min(resta, 0.5 * max(self._relogio.fator, 1e-9)))

    def processar_lote(self) -> int:
        if self._morto.is_set() or self._pausado.is_set():
            return 0
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
                if a.worker_id != self.worker_id:
                    # este worker ficou fora e o reaper passou a ambulancia para outro
                    raise ConflitoVersao(f"agora e do worker {a.worker_id}")
                a = self._repo.transicionar(amb_id, SA.RESERVADA, SA.A_CAMINHO, a.versao,
                                            heartbeat_em=self._agora_real())
            except ConflitoVersao as e:
                self._log.registrar("transicao_rejeitada", ambulancia_id=amb_id, chamado_id=ch_id,
                                    de="reservada", para="a_caminho", motivo=str(e))
                self._fila.ack(msg)
                n += 1
                continue
            self._fila.ack(msg)
            n += 1
            with self._lock:
                self._ativas.add(amb_id)
            fut = self._pool.submit(self._ciclo_rastreado, amb_id, ch_id, eta, a.versao)
            with self._lock:
                self._em_voo.add(fut)
            fut.add_done_callback(self._concluido)
        return n

    def aguardar_ciclos(self, timeout: float | None = None) -> None:
        with self._lock:
            pendentes = set(self._em_voo)
        wait(pendentes, timeout=timeout)

    def bater_heartbeat(self) -> int:
        """Atualiza heartbeat_em (tempo real) das ambulancias com ciclo em voo neste processo.
        (Antes listava todas as nao disponiveis do worker no banco: apos um restart, o worker novo
        mantinha vivas para sempre as ambulancias do ciclo que morreu, e o reaper nunca as liberava.
        De quebra, sai um scan da tabela a cada heartbeat.)"""
        if self._morto.is_set() or self._pausado.is_set():
            return 0
        ts = self._agora_real()
        # o worker tambem se anuncia vivo: e assim que o reaper sabe para quem passar as
        # ambulancias de um worker que morreu (senao o despachante continua mandando para ele)
        self._repo.registrar_worker(self.worker_id, ts)
        with self._lock:
            ids = list(self._ativas)
        for amb_id in ids:
            self._repo.atualizar_heartbeat(amb_id, ts)
        return len(ids)

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
        if exc and not isinstance(exc, _Derrubado):
            self._log.registrar("erro_ciclo", worker_id=self.worker_id, erro=repr(exc))

    def _gravar_chamado(self, chamado, amb_id: str) -> bool:
        """Grava o progresso do chamado so se ele ainda for desta ambulancia. Se o reaper
        o devolveu para a fila (e talvez outro ja o despachou), este ciclo para aqui."""
        try:
            self._repo.salvar_chamado_se(chamado, StatusChamado.DESPACHADO, amb_id)
            return True
        except ConflitoVersao:
            self._log.registrar("chamado_retomado", ambulancia_id=amb_id, chamado_id=chamado.id)
            return False

    def _transicionar(self, amb_id: str, de: SA, para: SA, versao: int, **campos):
        """`versao` e a que ESTE ciclo viu na sua ultima transicao - funciona como fencing token.
        (Antes relia a versao atual do banco: um ciclo que ficou pausado enquanto o reaper liberava
        e reatribuia a ambulancia voltava, lia a versao nova e passava pelo lock otimista.)"""
        return self._repo.transicionar(amb_id, de, para, versao, heartbeat_em=self._agora_real(), **campos)

    def _ciclo_rastreado(self, amb_id: str, ch_id: str, eta: float, versao: int) -> None:
        try:
            self._ciclo(amb_id, ch_id, eta, versao)
        except ConflitoVersao as e:
            # a ambulancia mudou de dono enquanto este ciclo estava parado: ele e obsoleto e para
            self._log.registrar("ciclo_obsoleto", ambulancia_id=amb_id, chamado_id=ch_id, motivo=str(e))
        finally:
            with self._lock:
                self._ativas.discard(amb_id)

    def _ciclo(self, amb_id: str, ch_id: str, eta: float, versao: int) -> None:
        chamado = self._repo.obter_chamado(ch_id)
        self._dormir(eta)

        agora = self._relogio.agora_sim()
        a = self._transicionar(amb_id, SA.A_CAMINHO, SA.NO_LOCAL, versao, lat=chamado.lat, lon=chamado.lon)
        chamado.chegada_em = agora
        if not self._gravar_chamado(chamado, amb_id):
            return
        self._log.registrar("chegou", ambulancia_id=amb_id, chamado_id=ch_id, versao=a.versao, zona=chamado.zona,
                            prioridade=chamado.prioridade, resposta_seg=agora - chamado.criado_em)

        self._dormir(self._rng.uniform(*self._atendimento))

        # transporte ao hospital mais proximo (ciclo real do SAMU: a ambulancia so libera
        # depois de entregar o paciente); sem hospital cadastrado, volta direto
        posicao = (chamado.lat, chamado.lon)
        hospital = self._hospital_mais_proximo(posicao)
        if hospital is not None:
            eta_h = self._roteador.eta(posicao, (hospital.lat, hospital.lon))
            a = self._transicionar(amb_id, SA.NO_LOCAL, SA.TRANSPORTANDO, a.versao)
            chamado.transporte_em = self._relogio.agora_sim()
            chamado.hospital_previsto_em = chamado.transporte_em + eta_h
            chamado.hospital_id = hospital.id
            if not self._gravar_chamado(chamado, amb_id):
                return
            self._log.registrar("transporte_iniciado", ambulancia_id=amb_id, chamado_id=ch_id, versao=a.versao,
                                hospital_id=hospital.id, eta_seg=eta_h)
            self._dormir(eta_h)
            self._log.registrar("hospital_chegou", ambulancia_id=amb_id, chamado_id=ch_id, hospital_id=hospital.id)
            self._dormir(self._rng.uniform(*self._entrega))
            posicao = (hospital.lat, hospital.lon)
            de = SA.TRANSPORTANDO
        else:
            de = SA.NO_LOCAL

        agora = self._relogio.agora_sim()
        chamado.liberado_em = agora
        chamado.status = StatusChamado.ATENDIDO
        if not self._gravar_chamado(chamado, amb_id):
            return
        # ja e despachavel aqui (no hospital ou no local): o retorno a base e interrompivel
        campos = {"lat": posicao[0], "lon": posicao[1], "chamado_id": None}
        explicacao = None
        if self._reposicionador is not None:
            atual = self._repo.obter_ambulancia(amb_id)
            alvo, explicacao = self._reposicionador.escolher_base(posicao, agora, atual.base_id)
            if alvo.id != atual.base_id:
                campos["base_id"] = alvo.id
        a = self._transicionar(amb_id, de, SA.DISPONIVEL, a.versao, **campos)
        self._log.registrar("liberada", ambulancia_id=amb_id, chamado_id=ch_id, versao=a.versao)
        if explicacao is not None and "base_id" in campos:
            self._log.registrar("reposicionada", ambulancia_id=amb_id, base_id=a.base_id, **explicacao)
        self._retornar(amb_id, posicao, self._bases[a.base_id])

    def _retornar(self, amb_id: str, origem, base: Base) -> None:
        """Volta a base movendo a posicao a cada passo; se for reservada no caminho, para
        (a proxima corrida sai de onde ela estiver)."""
        destino = (base.lat, base.lon)
        total = self._roteador.eta(origem, destino)
        if total <= 0:
            return
        passo = max(PASSO_RETORNO_SIM, total / 20)
        decorrido = 0.0
        while decorrido < total:
            self._dormir(min(passo, total - decorrido))
            decorrido = min(total, decorrido + passo)
            t = decorrido / total
            lat = origem[0] + (destino[0] - origem[0]) * t
            lon = origem[1] + (destino[1] - origem[1]) * t
            if not self._repo.atualizar_posicao_se_disponivel(amb_id, lat, lon):
                self._log.registrar("retorno_interrompido", ambulancia_id=amb_id, progresso=round(t, 2))
                return

    def _hospital_mais_proximo(self, p):
        if not self._hospitais:
            return None
        return min(self._hospitais, key=lambda h: haversine_km(p[0], p[1], h.lat, h.lon))

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
                            prioridade=chamado.prioridade, resposta_seg=agora - chamado.criado_em)

        self._relogio.dormir_sim(self._rng.uniform(*self._atendimento))

        # transporte ao hospital mais proximo (ciclo real do SAMU: a ambulancia so libera
        # depois de entregar o paciente); sem hospital cadastrado, volta direto
        posicao = (chamado.lat, chamado.lon)
        hospital = self._hospital_mais_proximo(posicao)
        if hospital is not None:
            eta_h = self._roteador.eta(posicao, (hospital.lat, hospital.lon))
            a = self._transicionar(amb_id, SA.NO_LOCAL, SA.TRANSPORTANDO)
            chamado.transporte_em = self._relogio.agora_sim()
            chamado.hospital_previsto_em = chamado.transporte_em + eta_h
            chamado.hospital_id = hospital.id
            self._repo.salvar_chamado(chamado)
            self._log.registrar("transporte_iniciado", ambulancia_id=amb_id, chamado_id=ch_id,
                                hospital_id=hospital.id, eta_seg=eta_h)
            self._relogio.dormir_sim(eta_h)
            self._log.registrar("hospital_chegou", ambulancia_id=amb_id, chamado_id=ch_id, hospital_id=hospital.id)
            self._relogio.dormir_sim(self._rng.uniform(*self._entrega))
            posicao = (hospital.lat, hospital.lon)
            de = SA.TRANSPORTANDO
        else:
            de = SA.NO_LOCAL

        agora = self._relogio.agora_sim()
        chamado.liberado_em = agora
        chamado.status = StatusChamado.ATENDIDO
        self._repo.salvar_chamado(chamado)
        # ja e despachavel aqui (no hospital ou no local): o retorno a base e interrompivel
        campos = {"lat": posicao[0], "lon": posicao[1], "chamado_id": None}
        explicacao = None
        if self._reposicionador is not None:
            atual = self._repo.obter_ambulancia(amb_id)
            alvo, explicacao = self._reposicionador.escolher_base(posicao, agora, atual.base_id)
            if alvo.id != atual.base_id:
                campos["base_id"] = alvo.id
        a = self._transicionar(amb_id, de, SA.DISPONIVEL, **campos)
        self._log.registrar("liberada", ambulancia_id=amb_id, chamado_id=ch_id)
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
            self._relogio.dormir_sim(min(passo, total - decorrido))
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

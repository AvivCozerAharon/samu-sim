"""Laboratorio de falhas: o console local controla, ao vivo, as mesmas falhas do scripts/caos.py -
fila caotica, workers que caem ou congelam, mais ou menos despachantes disputando a frota e
ocorrencias com varias vitimas - e ve as invariantes serem verificadas enquanto tudo acontece.
So existe no modo em memoria (scripts/dev_api.py): na AWS, derrubar um worker e `docker kill`."""
import random
import threading
import time
import uuid
from dataclasses import asdict

from samu_sim.core.geo import deslocar, haversine_km
from samu_sim.core.modelos import Chamado, StatusAmbulancia, StatusChamado
from samu_sim.eventlog import EventLogJsonl
from samu_sim.infra.fila_caotica import Caos, FalhaInjetada
from samu_sim.invariantes import verificar

# cada falha injetada ao lado do mecanismo que a resolve (e o evento que prova)
PARES = [
    {"falha": "mensagem duplicada", "injetada": "duplicada", "mecanismo": "idempotência por status",
     "eventos": ["chamado_ja_despachado", "transicao_rejeitada"]},
    {"falha": "ack perdido", "injetada": "ack_perdido", "mecanismo": "reentrega + idempotência",
     "eventos": ["chamado_ja_despachado", "transicao_rejeitada"]},
    {"falha": "processo morreu ao publicar", "injetada": "publicacao_falhou", "mecanismo": "outbox + reaper",
     "eventos": ["chamado_republicado", "reaper_liberou"]},
    {"falha": "worker caiu", "injetada": "worker_derrubado", "mecanismo": "heartbeat + reaper",
     "eventos": ["reaper_liberou", "chamado_devolvido"]},
    {"falha": "dono da ambulância sumiu", "injetada": None, "mecanismo": "rebalanceamento da frota",
     "eventos": ["ambulancia_reatribuida"]},
    {"falha": "worker congelado", "injetada": "worker_pausado", "mecanismo": "versão como fencing token",
     "eventos": ["ciclo_obsoleto", "chamado_retomado"]},
    {"falha": "corrida entre despachantes", "injetada": None, "mecanismo": "lock otimista",
     "eventos": ["reserva_falhou", "despacho_duplicado_evitado"]},
]


class EventLogLab(EventLogJsonl):
    """Grava o JSONL de sempre e guarda uma copia em memoria para o verificador."""

    def __init__(self, compartilhado: list, lock: threading.Lock, *a, **k):
        super().__init__(*a, **k)
        self._comp, self._comp_lock = compartilhado, lock

    def registrar(self, tipo: str, **campos) -> None:
        e = self._montar(tipo, campos)
        super().registrar(tipo, **campos)
        with self._comp_lock:
            self._comp.append(e)


class Laboratorio:
    def __init__(self, repo, relogio, caos: Caos, filas_ch: dict, filas_ev: dict, workers: list,
                 criar_despachante, bairros, log_factory, eventos: list, eventos_lock: threading.Lock,
                 n_despachantes: int = 2):
        self._repo, self._relogio, self.caos = repo, relogio, caos
        self._filas_ch, self._filas_ev = filas_ch, filas_ev
        self._workers = {w.worker_id: w for w in workers}
        self._criar_despachante = criar_despachante  # (i) -> (Despachante, loop_fn)
        self._bairros = bairros
        self._log = log_factory("laboratorio")
        self._eventos, self._eventos_lock = eventos, eventos_lock
        self._despachantes: list[tuple[str, threading.Event]] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._contagem = {"worker_derrubado": 0, "worker_pausado": 0}
        self._veredito = None  # ultimo "drenar e verificar"
        self.caos.ligado.clear()  # o laboratorio abre com o caos desligado
        for _ in range(n_despachantes):
            self.adicionar_despachante()

    # ---------- despachantes ----------
    def adicionar_despachante(self) -> int:
        with self._lock:
            if len(self._despachantes) >= 8:
                return len(self._despachantes)
            self._seq += 1
            nome = f"despachante-{self._seq}"
            parar = threading.Event()
            self._despachantes.append((nome, parar))
        d, loop = self._criar_despachante(nome)
        threading.Thread(target=loop, args=(d.processar_lote, parar), daemon=True, name=nome).start()
        self._log.registrar("despachante_adicionado", despachante=nome, total=len(self._despachantes))
        return len(self._despachantes)

    def remover_despachante(self) -> int:
        with self._lock:
            if len(self._despachantes) <= 1:
                return len(self._despachantes)
            nome, parar = self._despachantes.pop()
        parar.set()
        self._log.registrar("despachante_removido", despachante=nome, total=len(self._despachantes))
        return len(self._despachantes)

    # ---------- falhas ----------
    def configurar_caos(self, ligado: bool | None = None, **taxas) -> None:
        for k in ("duplicar", "atrasar", "perder_ack", "falhar_publicar"):
            if k in taxas and taxas[k] is not None:
                setattr(self.caos, k, max(0.0, min(0.5, float(taxas[k]))))
        if ligado is not None:
            (self.caos.ligado.set if ligado else self.caos.ligado.clear)()
        self._log.registrar("caos_configurado", ligado=self.caos.ligado.is_set(),
                            **{k: getattr(self.caos, k) for k in ("duplicar", "atrasar", "perder_ack", "falhar_publicar")})

    def worker(self, worker_id: str, acao: str, segundos: float = 10.0) -> str:
        w = self._workers[worker_id]
        if acao == "derrubar":
            w.derrubar()
            self._contagem["worker_derrubado"] += 1
            self._log.registrar("worker_derrubado", worker_id=worker_id)
        elif acao == "reviver":
            w.reviver()
            w.retomar()
            self._log.registrar("worker_revivido", worker_id=worker_id)
        elif acao == "pausar":
            w.pausar()
            self._contagem["worker_pausado"] += 1
            self._log.registrar("worker_pausado", worker_id=worker_id, segundos=segundos)

            def retomar():
                time.sleep(segundos)
                w.retomar()
                self._log.registrar("worker_retomado", worker_id=worker_id)
            threading.Thread(target=retomar, daemon=True).start()
        else:
            raise ValueError(f"acao desconhecida: {acao}")
        return w.estado

    # ---------- ocorrencia com varias vitimas ----------
    def ocorrencia(self, lat: float, lon: float, vitimas: int, prioridade: str = "vermelho") -> dict:
        vitimas = max(1, min(int(vitimas), 20))
        b = min(self._bairros, key=lambda x: haversine_km(lat, lon, x.lat, x.lon))
        oc = "oc-" + uuid.uuid4().hex[:5]
        agora = self._relogio.agora_sim()
        rng = random.Random(oc)
        criados = []
        for i in range(vitimas):
            # vitimas espalhadas em ~100 m (o mesmo acidente, pontos um pouco diferentes)
            plat, plon = deslocar(lat, lon, rng.uniform(0, 0.1), rng.uniform(0, 360))
            c = Chamado(id=f"{oc}-{i + 1}", lat=plat, lon=plon, bairro=b.nome, zona=b.zona, criado_em=agora,
                        prioridade=prioridade, tipo="trauma", ocorrencia_id=oc)
            if not self._repo.criar_chamado(c):
                continue
            self._log.registrar("chamado_criado", chamado_id=c.id, bairro=c.bairro, zona=c.zona,
                                prioridade=prioridade, tipo_chamado="trauma", ocorrencia_id=oc)
            try:
                self._filas_ch[prioridade].publicar({"chamado_id": c.id, "lat": c.lat, "lon": c.lon,
                                                     "prioridade": prioridade, "bairro": c.bairro,
                                                     "zona": c.zona, "criado_em": c.criado_em})
                self._repo.marcar_publicado(c.id)
            except FalhaInjetada:
                pass  # ficou salvo e fora da fila: o outbox do reaper resolve
            criados.append(c.id)
        self._log.registrar("ocorrencia_criada", ocorrencia_id=oc, vitimas=len(criados), bairro=b.nome,
                            zona=b.zona, lat=lat, lon=lon, prioridade=prioridade)
        return {"ocorrencia_id": oc, "chamados": criados, "bairro": b.nome}

    # ---------- verificacao ----------
    def _copiar_eventos(self) -> list[dict]:
        with self._eventos_lock:
            return list(self._eventos)

    def _mudar_fator(self, fator: float) -> None:
        """Como o POST /controle: novo checkpoint na rodada, para o tempo simulado nao saltar."""
        r = self._repo.obter_rodada()
        r.inicio_sim, r.inicio_real, r.fator = self._relogio.agora_sim(), time.time(), fator
        self._repo.salvar_rodada(r)
        self._relogio.sincronizar(r.inicio_real, r.inicio_sim, fator)

    def drenar_e_verificar(self, fator_drenagem: float = 300.0, max_sim_seg: float = 6 * 3600,
                           max_real_seg: float = 150.0) -> dict:
        """Desliga o caos, revive todo mundo e espera todos os chamados abertos ate agora
        terminarem - com o relogio acelerado, porque cada atendimento leva mais de 1 h simulada.
        Os chamados novos do gerador continuam chegando e nao entram no julgamento."""
        self._veredito = {"status": "drenando", "inicio_sim": self._relogio.agora_sim()}
        self.configurar_caos(ligado=False)
        for wid in self._workers:
            self.worker(wid, "reviver")
        corte = {c.id for c in self._repo.listar_chamados()}
        fator_antes = self._relogio.fator or 1.0
        self._mudar_fator(max(fator_antes, fator_drenagem))
        t0, s0 = time.time(), self._relogio.agora_sim()
        drenou = False
        try:
            while time.time() - t0 < max_real_seg and self._relogio.agora_sim() - s0 < max_sim_seg:
                chs = [c for c in self._repo.listar_chamados() if c.id in corte]
                if all(c.status == StatusChamado.ATENDIDO for c in chs):
                    drenou = True
                    break
                time.sleep(0.25)
        finally:
            self._mudar_fator(fator_antes)
        chs = [asdict(c) for c in self._repo.listar_chamados() if c.id in corte]
        # ambulancia presa = nao disponivel segurando chamado do corte (ou nenhum chamado)
        ambs = [asdict(a) for a in self._repo.listar_ambulancias()
                if a.status != StatusAmbulancia.DISPONIVEL and (a.chamado_id is None or a.chamado_id in corte)]
        r = verificar(self._copiar_eventos(), chs, ambs, drenado=True)
        r.update(status="concluido", drenou=drenou, chamados_julgados=len(chs), tempo_real_seg=round(time.time() - t0, 1),
                 tempo_sim_min=round((self._relogio.agora_sim() - s0) / 60))
        self._veredito = r
        self._log.registrar("verificacao_concluida", ok=r["ok"], violacoes=len(r["violacoes"]),
                            chamados=len(chs))
        return r

    def estado(self) -> dict:
        eventos = self._copiar_eventos()
        ao_vivo = verificar(eventos, [], [], drenado=False)  # I1, I2, I5 valem a qualquer momento
        inj = {k: sum(f.injetadas[k] for f in [*self._filas_ch.values(), *self._filas_ev.values()])
               for k in ("duplicada", "atrasada", "ack_perdido", "publicacao_falhou")} | self._contagem
        rec = ao_vivo["recuperacoes"]
        ocorrencias = {}
        for e in eventos:
            if e["tipo"] == "ocorrencia_criada":
                ocorrencias[e["ocorrencia_id"]] = {"id": e["ocorrencia_id"], "vitimas": e["vitimas"],
                                                   "bairro": e["bairro"], "lat": e["lat"], "lon": e["lon"]}
        if ocorrencias:
            por_oc = {}
            for c in self._repo.listar_chamados():
                if c.ocorrencia_id in ocorrencias:
                    s = por_oc.setdefault(c.ocorrencia_id, {"aguardando": 0, "a_caminho": 0, "atendidos": 0})
                    s["atendidos" if c.status == StatusChamado.ATENDIDO else
                      "a_caminho" if c.status == StatusChamado.DESPACHADO else "aguardando"] += 1
            for oid, s in por_oc.items():
                ocorrencias[oid].update(s)
        return {
            "caos": {"ligado": self.caos.ligado.is_set(),
                     **{k: getattr(self.caos, k) for k in ("duplicar", "atrasar", "perder_ack", "falhar_publicar")}},
            "workers": [{"id": wid, "estado": w.estado, "ciclos": w.ciclos_em_voo()} for wid, w in self._workers.items()],
            "despachantes": [n for n, _ in self._despachantes],
            "pares": [p | {"n_injetadas": inj.get(p["injetada"]) if p["injetada"] else None,
                           "n_recuperacoes": sum(rec.get(k, 0) for k in p["eventos"])} for p in PARES],
            "injetadas": inj,
            "recuperacoes": rec,
            "invariantes_ao_vivo": {"ok": ao_vivo["ok"], "por_invariante": ao_vivo["por_invariante"],
                                    "violacoes": ao_vivo["violacoes"][:5]},
            "veredito": self._veredito,
            "ocorrencias": list(ocorrencias.values())[-6:],
        }

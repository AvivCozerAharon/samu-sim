"""Rodada sob caos: o mesmo sistema do runner local (gerador, despachantes, workers, reaper), com
filas que duplicam, atrasam, reordenam e perdem acks, processos que morrem ao publicar, e workers
derrubados e revividos no meio do atendimento. No fim o caos desliga, o sistema drena e o
verificador de invariantes julga a rodada.

Uso: python scripts/caos.py --rodadas 20"""
import random
import threading
import time
import uuid
from dataclasses import asdict

from samu_sim.api.reaper import Reaper
from samu_sim.core.config import Config
from samu_sim.core.modelos import PRIORIDADES, Rodada, StatusAmbulancia, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.despachante.servico import Despachante
from samu_sim.ambulancia.servico import WorkerAmbulancia
from samu_sim.eventlog import EventLogMemoria
from samu_sim.gerador.demanda import CHAMADOS_POR_DIA_RIO, GeradorChamados, carregar_bairros, carregar_bases
from samu_sim.gerador.servico import ServicoGerador
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.fila_caotica import Caos, FalhaInjetada, FilaCaotica
from samu_sim.infra.repositorio import RepositorioMemoria
from samu_sim.invariantes import verificar
from samu_sim.local import montar_frota
from samu_sim.politicas import criar_politica
from samu_sim.roteador import criar_roteador

# tempos REAIS do caos (a fator 2000, 1 s real = 33 min simulados)
VISIBILIDADE_SEG = 0.2
HEARTBEAT_SEG = 0.05
REAPER_INTERVALO_SEG = 0.1
REAPER_TIMEOUT_SEG = 0.5
QUEDA_SEG = (0.5, 1.5)   # quanto tempo o worker fica fora antes do restart
OCIOSO_SEG = 0.005


def _loop(processar, parar: threading.Event, log, nome: str) -> None:
    """Como o loop_servico de producao: falha no processamento nao derruba o servico."""
    while not parar.is_set():
        try:
            if processar() == 0:
                time.sleep(OCIOSO_SEG)
        except FalhaInjetada:
            log.registrar("processo_reiniciado", servico=nome)
        except Exception as e:  # noqa: BLE001
            log.registrar("erro_servico", servico=nome, erro=repr(e))
            time.sleep(OCIOSO_SEG)


def rodar(seed: int = 42, caos: Caos | None = None, fator: float = 2000, duracao_sim_seg: float = 12 * 3600,
          n_ambulancias: int = 73, chamados_por_dia: int = CHAMADOS_POR_DIA_RIO, politica: str = "menor_eta",
          n_despachantes: int = 2, n_workers: int = 2, quedas_por_worker: int = 2,
          drenagem_max_sim: float = 12 * 3600) -> dict:
    caos = caos or Caos()
    rng = random.Random(f"caos-{seed}")
    relogio = Relogio(fator=fator)
    repo = RepositorioMemoria()
    repo.salvar_rodada(Rodada(uuid.uuid4().hex[:8], seed, politica, fator, n_ambulancias, "matriz", *relogio.checkpoint()))
    bairros, bases = carregar_bairros("dados/bairros.csv"), carregar_bases("dados/bases.csv")
    for a in montar_frota(bases, n_ambulancias, n_workers):
        repo.salvar_ambulancia(a)
    logs: list[EventLogMemoria] = []

    def novo_log(servico):
        log = EventLogMemoria(relogio, servico)
        logs.append(log)
        return log

    filas_ch = {p: FilaCaotica(FilaMemoria(VISIBILIDADE_SEG), caos, seed=rng.randrange(1 << 30)) for p in PRIORIDADES}
    filas_ev = {f"w{k}": FilaCaotica(FilaMemoria(VISIBILIDADE_SEG), caos, seed=rng.randrange(1 << 30))
                for k in range(n_workers)}
    rot = criar_roteador("matriz", Config())
    bases_por_id = {b.id: b for b in bases}
    chamados = [c for c in GeradorChamados(bairros, seed, chamados_por_dia).gerar_dia(0) if c.criado_em < duracao_sim_seg]
    log_caos = novo_log("caos")

    despachantes = [Despachante(filas_ch, filas_ev, repo, criar_politica(politica), rot, relogio,
                                novo_log(f"despachante-{i}"), reentrega_seg=VISIBILIDADE_SEG)
                    for i in range(n_despachantes)]
    workers = [WorkerAmbulancia(f"w{k}", filas_ev[f"w{k}"], repo, relogio, rot, bases_por_id,
                                novo_log(f"ambulancia-w{k}"), seed=seed) for k in range(n_workers)]
    reaper = Reaper(repo, filas_ch, bases_por_id, novo_log("api"), timeout_seg=REAPER_TIMEOUT_SEG,
                    agora_sim=relogio.agora_sim)
    parar = threading.Event()

    def gerador():
        # o container do gerador reinicia quando o processo morre; ao subir, ele relê a lista
        log = novo_log("gerador")
        while not parar.is_set():
            try:
                ServicoGerador(chamados, filas_ch, repo, relogio, log).executar(parar)
                return
            except FalhaInjetada:
                log.registrar("processo_reiniciado", servico="gerador")

    def reaper_loop():
        while not parar.wait(REAPER_INTERVALO_SEG):
            try:
                reaper.executar_uma_vez()
            except FalhaInjetada:
                log_caos.registrar("processo_reiniciado", servico="reaper")

    def quedas():
        # cada worker cai `quedas_por_worker` vezes em horarios sorteados e volta depois
        agenda = sorted((rng.uniform(0.1, 0.9) * duracao_sim_seg, w) for w in workers for _ in range(quedas_por_worker))
        for t, w in agenda:
            while relogio.agora_sim() < t and not parar.is_set():
                time.sleep(0.01)
            if parar.is_set() or not caos.ligado.is_set():
                return
            w.derrubar()
            log_caos.registrar("worker_derrubado", worker_id=w.worker_id)
            time.sleep(rng.uniform(*QUEDA_SEG))
            w.reviver()
            log_caos.registrar("worker_revivido", worker_id=w.worker_id)

    threads = [threading.Thread(target=gerador, daemon=True), threading.Thread(target=reaper_loop, daemon=True),
               threading.Thread(target=quedas, daemon=True)]
    threads += [threading.Thread(target=_loop, args=(d.processar_lote, parar, log_caos, f"despachante-{i}"), daemon=True)
                for i, d in enumerate(despachantes)]
    threads += [threading.Thread(target=_loop, args=(w.processar_lote, parar, log_caos, w.worker_id), daemon=True)
                for w in workers]
    threads += [w.iniciar_heartbeat(HEARTBEAT_SEG, parar) for w in workers]
    t0 = time.time()
    for t in threads:
        if not t.is_alive():
            t.start()

    while relogio.agora_sim() < duracao_sim_seg:
        time.sleep(0.05)
    # drenagem: sem falhas novas e com todo mundo de pe, o sistema tem que se resolver sozinho
    caos.ligado.clear()
    for w in workers:
        w.reviver()
    fim = duracao_sim_seg + drenagem_max_sim
    drenado = False
    while relogio.agora_sim() < fim:
        chs, ambs = repo.listar_chamados(), repo.listar_ambulancias()
        if (len(chs) == len(chamados) and all(c.status == StatusChamado.ATENDIDO for c in chs)
                and all(a.status == StatusAmbulancia.DISPONIVEL and a.chamado_id is None for a in ambs)):
            drenado = True
            break
        time.sleep(0.05)
    parar.set()
    for w in workers:
        w.aguardar_ciclos(timeout=2)
        w.encerrar()

    eventos = [e for log in logs for e in log.eventos]
    chs = [asdict(c) for c in repo.listar_chamados()]
    # chamado gerado que nunca chegou ao banco tambem e chamado perdido
    salvos = {c["id"] for c in chs}
    chs += [asdict(c) | {"status": "nunca_salvo"} for c in chamados if c.id not in salvos]
    resultado = verificar(eventos, chs, [asdict(a) for a in repo.listar_ambulancias()], drenado=True)
    resultado["drenou"] = drenado
    resultado["falhas_injetadas"] = {
        k: sum(f.injetadas[k] for f in [*filas_ch.values(), *filas_ev.values()])
        for k in ("duplicada", "atrasada", "ack_perdido", "publicacao_falhou")}
    resultado["falhas_injetadas"]["worker_derrubado"] = sum(1 for e in eventos if e["tipo"] == "worker_derrubado")
    resultado["seed"] = seed
    resultado["tempo_real_seg"] = round(time.time() - t0, 1)
    return resultado

"""Simulacao inteira em memoria + API num processo so (sem Docker/AWS), para desenvolver o front e
para a demo: o console ganha o Laboratorio de falhas (fila caotica, workers que caem ou congelam,
despachantes a mais, ocorrencia com varias vitimas e verificacao das invariantes).
Uso: python scripts/dev_api.py --fator 60 --ambulancias 73 [--sem-transito] [--sem-laboratorio]"""
import argparse
import logging
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.ambulancia.servico import WorkerAmbulancia  # noqa: E402
from samu_sim.api import criar_app  # noqa: E402
from samu_sim.cenarios import criar_gerenciador  # noqa: E402
from samu_sim.core.config import Config  # noqa: E402
from samu_sim.core.modelos import PRIORIDADES, Rodada  # noqa: E402
from samu_sim.core.relogio import Relogio  # noqa: E402
from samu_sim.core.runtime import SincronizadorRelogio, loop_servico  # noqa: E402
from samu_sim.despachante.servico import Despachante  # noqa: E402
from samu_sim.eventlog import EventLogJsonl  # noqa: E402
from samu_sim.gerador.demanda import CHAMADOS_POR_DIA_RIO, GeradorChamados, carregar_bairros, carregar_bases  # noqa: E402
from samu_sim.gerador.servico import ServicoGerador  # noqa: E402
from samu_sim.infra.fila import FilaMemoria  # noqa: E402
from samu_sim.infra.fila_caotica import Caos, FalhaInjetada, FilaCaotica  # noqa: E402
from samu_sim.infra.repositorio import RepositorioMemoria  # noqa: E402
from samu_sim.laboratorio import EventLogLab, Laboratorio  # noqa: E402
from samu_sim.local import montar_frota  # noqa: E402
from samu_sim.politicas import criar_politica  # noqa: E402
from samu_sim.roteador import criar_roteador  # noqa: E402

# no laboratorio a recuperacao tem que acontecer em segundos, na frente de quem assiste
LAB_HEARTBEAT_SEG, LAB_REAPER_INTERVALO_SEG, LAB_REAPER_TIMEOUT_SEG = 2.0, 2.0, 6.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fator", type=float, default=60)
    p.add_argument("--ambulancias", type=int, default=73)
    p.add_argument("--chamados-por-dia", type=int, default=CHAMADOS_POR_DIA_RIO)
    p.add_argument("--politica", default="menor_eta")
    p.add_argument("--roteador", default="matriz")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--sem-transito", action="store_true", help="desliga o fator de transito por hora")
    p.add_argument("--sem-laboratorio", action="store_true", help="console sem o laboratorio de falhas")
    a = p.parse_args()
    lab_ligado = not a.sem_laboratorio

    cfg = Config(transito=not a.sem_transito)
    rodada_id = "dev-" + uuid.uuid4().hex[:6]
    relogio = Relogio(fator=a.fator, agora_real=time.time, mono=time.monotonic)
    repo = RepositorioMemoria()
    repo.salvar_rodada(Rodada(rodada_id, a.seed, a.politica, a.fator, a.ambulancias, a.roteador,
                              *relogio.checkpoint()))
    bairros = carregar_bairros("dados/bairros.csv")
    bases = carregar_bases("dados/bases.csv")
    for amb in montar_frota(bases, a.ambulancias, 2):
        repo.salvar_ambulancia(amb)
    caos = Caos()
    envolver = (lambda f, s: FilaCaotica(f, caos, seed=s)) if lab_ligado else (lambda f, s: f)
    fila = {p_: envolver(FilaMemoria(visibilidade_seg=5), i) for i, p_ in enumerate(PRIORIDADES)}
    filas_ev = {w: envolver(FilaMemoria(), 10 + i) for i, w in enumerate(("w0", "w1"))}
    rot = criar_roteador(a.roteador, cfg, relogio=relogio)
    bases_por_id = {b.id: b for b in bases}
    log_dir = Path(tempfile.gettempdir()) / "samu-sim-dev"
    eventos, eventos_lock = [], threading.Lock()
    if lab_ligado:
        log = lambda s: EventLogLab(eventos, eventos_lock, log_dir, relogio, s, rodada_id)  # noqa: E731
    else:
        log = lambda s: EventLogJsonl(log_dir, relogio, s, rodada_id)  # noqa: E731

    chamados = []
    for dia in range(7):
        chamados += GeradorChamados(bairros, a.seed, a.chamados_por_dia).gerar_dia(dia)
    workers = [WorkerAmbulancia(w, filas_ev[w], repo, relogio, rot, bases_por_id, log(w), seed=a.seed)
               for w in ("w0", "w1")]
    parar = threading.Event()
    SincronizadorRelogio(relogio, repo, 1.0, parar).iniciar()

    log_gerador = log("gerador")

    def gerador():
        # como o container com restart: se o processo morre ao publicar, ele sobe de novo e retoma
        while not parar.is_set():
            try:
                ServicoGerador(chamados, fila, repo, relogio, log_gerador).executar(parar)
                return
            except FalhaInjetada:
                log_gerador.registrar("processo_reiniciado", servico="gerador")
    threading.Thread(target=gerador, daemon=True).start()
    for w in workers:
        threading.Thread(target=loop_servico, args=(w.processar_lote, parar, 0.05), daemon=True).start()

    def criar_despachante(nome):
        d = Despachante(fila, filas_ev, repo, criar_politica(a.politica), rot, relogio, log(nome))
        return d, lambda processar, parar_d: loop_servico(processar, parar_d, 0.05)

    lab = None
    if lab_ligado:
        for w in workers:
            w.iniciar_heartbeat(LAB_HEARTBEAT_SEG, parar)
        lab = Laboratorio(repo, relogio, caos, fila, filas_ev, workers, criar_despachante, bairros, log,
                          eventos, eventos_lock)
    else:
        for i in range(2):
            d, loop = criar_despachante(f"d{i}")
            threading.Thread(target=loop, args=(d.processar_lote, parar), daemon=True).start()

    app = criar_app(repo, fila, bases_por_id, relogio, log("api"), log_dir=log_dir, rodada_id=rodada_id,
                    turnos_path="docs/experimentos/turnos.json", gerenciador_cenarios=criar_gerenciador(),
                    expansao_path="docs/experimentos/expansao.json", transito=cfg.transito,
                    reaper_timeout_seg=LAB_REAPER_TIMEOUT_SEG if lab_ligado else 120.0, laboratorio=lab)

    if lab_ligado:
        def reaper_loop():
            while not parar.wait(LAB_REAPER_INTERVALO_SEG):
                try:
                    app.state.reaper.executar_uma_vez()
                except FalhaInjetada:
                    pass  # o reaper "morreu" ao publicar; o outbox pega na proxima passada
                except Exception as e:  # noqa: BLE001
                    logging.exception(f"erro no reaper: {e!r}")
        threading.Thread(target=reaper_loop, daemon=True).start()

    print(f"samu-sim dev: http://localhost:{a.porta}/  (fator {a.fator}, {a.ambulancias} ambulancias, {a.politica}, "
          f"{a.roteador}, transito {'ligado' if cfg.transito else 'desligado'}, "
          f"laboratorio {'ligado' if lab_ligado else 'desligado'})")
    uvicorn.run(app, host="127.0.0.1", port=a.porta, log_level="warning")
    parar.set()


if __name__ == "__main__":
    main()

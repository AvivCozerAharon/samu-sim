"""Simulacao inteira em memoria + API num processo so (sem Docker/AWS), para desenvolver o front.
Uso: python scripts/dev_api.py --fator 20 --ambulancias 50 --politica menor_eta --roteador matriz"""
import argparse
import sys
import threading
import time
import uuid
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.ambulancia.servico import WorkerAmbulancia  # noqa: E402
from samu_sim.api import criar_app  # noqa: E402
from samu_sim.core.config import Config  # noqa: E402
from samu_sim.core.modelos import Rodada  # noqa: E402
from samu_sim.core.relogio import Relogio  # noqa: E402
from samu_sim.core.runtime import SincronizadorRelogio, loop_servico  # noqa: E402
from samu_sim.despachante.servico import Despachante  # noqa: E402
from samu_sim.eventlog import EventLogMemoria  # noqa: E402
from samu_sim.gerador.demanda import GeradorChamados, carregar_bairros, carregar_bases  # noqa: E402
from samu_sim.gerador.servico import ServicoGerador  # noqa: E402
from samu_sim.infra.fila import FilaMemoria  # noqa: E402
from samu_sim.infra.repositorio import RepositorioMemoria  # noqa: E402
from samu_sim.local import montar_frota  # noqa: E402
from samu_sim.politicas import criar_politica  # noqa: E402
from samu_sim.roteador import criar_roteador  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fator", type=float, default=20)
    p.add_argument("--ambulancias", type=int, default=50)
    p.add_argument("--chamados-por-dia", type=int, default=400)
    p.add_argument("--politica", default="menor_eta")
    p.add_argument("--roteador", default="matriz")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--porta", type=int, default=8000)
    a = p.parse_args()

    cfg = Config()
    rodada_id = "dev-" + uuid.uuid4().hex[:6]
    relogio = Relogio(fator=a.fator, agora_real=time.time, mono=time.monotonic)
    repo = RepositorioMemoria()
    repo.salvar_rodada(Rodada(rodada_id, a.seed, a.politica, a.fator, a.ambulancias, a.roteador,
                              *relogio.checkpoint()))
    bairros = carregar_bairros("dados/bairros.csv")
    bases = carregar_bases("dados/bases.csv")
    for amb in montar_frota(bases, a.ambulancias, 2):
        repo.salvar_ambulancia(amb)
    fila = FilaMemoria(visibilidade_seg=5)
    filas_ev = {"w0": FilaMemoria(), "w1": FilaMemoria()}
    rot = criar_roteador(a.roteador, cfg)
    bases_por_id = {b.id: b for b in bases}
    log = lambda s: EventLogMemoria(relogio, s, rodada_id)  # noqa: E731

    chamados = []
    for dia in range(7):
        chamados += GeradorChamados(bairros, a.seed, a.chamados_por_dia).gerar_dia(dia)
    gerador = ServicoGerador(chamados, fila, repo, relogio, log("gerador"))
    despachantes = [Despachante(fila, filas_ev, repo, criar_politica(a.politica), rot, relogio, log(f"d{i}"))
                    for i in range(2)]
    workers = [WorkerAmbulancia(w, filas_ev[w], repo, relogio, rot, bases_por_id, log(w), seed=a.seed)
               for w in ("w0", "w1")]
    parar = threading.Event()
    SincronizadorRelogio(relogio, repo, 1.0, parar).iniciar()
    threading.Thread(target=gerador.executar, args=(parar,), daemon=True).start()
    for d in despachantes:
        threading.Thread(target=loop_servico, args=(d.processar_lote, parar, 0.05), daemon=True).start()
    for w in workers:
        threading.Thread(target=loop_servico, args=(w.processar_lote, parar, 0.05), daemon=True).start()

    app = criar_app(repo, fila, bases_por_id, relogio, log("api"))
    print(f"samu-sim dev: http://localhost:{a.porta}/  (fator {a.fator}, {a.ambulancias} ambulancias, {a.politica}, {a.roteador})")
    uvicorn.run(app, host="127.0.0.1", port=a.porta, log_level="warning")
    parar.set()


if __name__ == "__main__":
    main()

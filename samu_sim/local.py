"""Runner local: monta gerador, despachantes e workers em memoria e roda em threads.
Uso: python -m samu_sim.local --fator 20 --duracao-sim 3600"""
import argparse
import json
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

from samu_sim.ambulancia.servico import WorkerAmbulancia
from samu_sim.core.metricas import calcular
from samu_sim.core.modelos import Ambulancia, Base, Rodada
from samu_sim.core.relogio import Relogio
from samu_sim.despachante.servico import Despachante
from samu_sim.eventlog import EventLogJsonl, EventLogMemoria
from samu_sim.gerador.demanda import GeradorChamados, carregar_bairros, carregar_bases
from samu_sim.gerador.servico import ServicoGerador
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria
from samu_sim.politicas import criar_politica
from samu_sim.roteador import criar_roteador

INTERVALO_OCIOSO_REAL = 0.02


def montar_frota(bases: list[Base], n_ambulancias: int, n_workers: int) -> list[Ambulancia]:
    frota = []
    for i in range(n_ambulancias):
        b = bases[i % len(bases)]
        frota.append(Ambulancia(id=f"amb-{i:03d}", base_id=b.id, lat=b.lat, lon=b.lon,
                                worker_id=f"w{i % n_workers}"))
    return frota


def rodar(fator: float, duracao_sim_seg: float, n_ambulancias: int = 50,
          politica: str = "mais_proxima", roteador: str = "haversine", seed: int = 42,
          chamados_por_dia: int = 300, n_despachantes: int = 2, n_workers: int = 2,
          visibilidade_seg: float = 30.0, log_dir: str | None = None) -> dict:
    rodada_id = uuid.uuid4().hex[:8]
    relogio = Relogio(fator=fator)
    repo = RepositorioMemoria()
    repo.salvar_rodada(Rodada(rodada_id, seed, politica, fator, n_ambulancias, roteador,
                              *relogio.checkpoint()))
    bairros = carregar_bairros("dados/bairros.csv")
    bases = carregar_bases("dados/bases.csv")
    for a in montar_frota(bases, n_ambulancias, n_workers):
        repo.salvar_ambulancia(a)

    logs_mem: list[EventLogMemoria] = []
    logs_jsonl: list[EventLogJsonl] = []

    def novo_log(servico: str):
        if log_dir:
            log = EventLogJsonl(log_dir, relogio, servico, rodada_id)
            logs_jsonl.append(log)
            return log
        log = EventLogMemoria(relogio, servico, rodada_id)
        logs_mem.append(log)
        return log

    fila_chamados = FilaMemoria(visibilidade_seg=visibilidade_seg)
    filas_eventos = {f"w{k}": FilaMemoria(visibilidade_seg=visibilidade_seg) for k in range(n_workers)}
    rot = criar_roteador(roteador)
    bases_por_id = {b.id: b for b in bases}

    chamados = GeradorChamados(bairros, seed, chamados_por_dia).gerar_dia(0)
    chamados = [c for c in chamados if c.criado_em < duracao_sim_seg]
    gerador = ServicoGerador(chamados, fila_chamados, repo, relogio, novo_log("gerador"))
    despachantes = [Despachante(fila_chamados, filas_eventos, repo, criar_politica(politica), rot,
                                relogio, novo_log(f"despachante-{i}")) for i in range(n_despachantes)]
    workers = [WorkerAmbulancia(f"w{k}", filas_eventos[f"w{k}"], repo, relogio, rot, bases_por_id,
                                novo_log(f"ambulancia-w{k}"), seed=seed) for k in range(n_workers)]

    parar = threading.Event()

    def loop(processar):
        while not parar.is_set():
            if processar() == 0:
                time.sleep(INTERVALO_OCIOSO_REAL)

    threads = [threading.Thread(target=gerador.executar, args=(parar,), daemon=True)]
    threads += [threading.Thread(target=loop, args=(d.processar_lote,), daemon=True) for d in despachantes]
    threads += [threading.Thread(target=loop, args=(w.processar_lote,), daemon=True) for w in workers]
    for t in threads:
        t.start()

    while relogio.agora_sim() < duracao_sim_seg:
        time.sleep(0.05)
    parar.set()
    for t in threads:
        t.join(timeout=2)
    for w in workers:
        w.aguardar_ciclos(timeout=5)
        w.encerrar()
    for log in logs_jsonl:
        log.fechar()

    eventos = Counter()
    for log in logs_mem:
        eventos.update(e["tipo"] for e in log.eventos)
    if log_dir:
        for arquivo in (Path(log_dir) / rodada_id).glob("*.jsonl"):
            with open(arquivo, encoding="utf-8") as f:
                eventos.update(json.loads(linha)["tipo"] for linha in f if linha.strip())
    return {
        "rodada": {"id": rodada_id, "fator": fator, "politica": politica, "roteador": roteador,
                   "seed": seed, "n_ambulancias": n_ambulancias, "duracao_sim_seg": duracao_sim_seg},
        "metricas": calcular(repo.listar_chamados()),
        "eventos": dict(eventos),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="samu-sim: rodada local em memoria")
    p.add_argument("--fator", type=float, default=20)
    p.add_argument("--duracao-sim", type=float, default=3600, help="segundos simulados")
    p.add_argument("--ambulancias", type=int, default=50)
    p.add_argument("--politica", default="mais_proxima")
    p.add_argument("--roteador", default="haversine")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--chamados-por-dia", type=int, default=300)
    p.add_argument("--log-dir", default=None, help="grava event log JSONL nesta pasta")
    a = p.parse_args()
    r = rodar(a.fator, a.duracao_sim, a.ambulancias, a.politica, a.roteador, a.seed,
              a.chamados_por_dia, log_dir=a.log_dir)
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

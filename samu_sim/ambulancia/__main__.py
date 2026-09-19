import logging
import threading

from samu_sim.ambulancia.servico import WorkerAmbulancia
from samu_sim.core.config import Config
from samu_sim.core.runtime import (SincronizadorRelogio, configurar_logging, instalar_sinais,
                                   loop_servico, montar_infra, relogio_da_rodada)
from samu_sim.eventlog import EventLogJsonl, enviar_para_s3
from samu_sim.roteador import criar_roteador


def main() -> None:
    cfg = Config.do_ambiente()
    nome = f"ambulancia-{cfg.worker_id}"
    configurar_logging(nome)
    infra = montar_infra(cfg)
    relogio = relogio_da_rodada(infra.repo)
    rodada = infra.repo.obter_rodada()
    parar = threading.Event()
    instalar_sinais(parar)
    SincronizadorRelogio(relogio, infra.repo, cfg.sync_relogio_seg, parar).iniciar()
    log = EventLogJsonl(cfg.log_dir, relogio, nome, cfg.rodada_id)
    w = WorkerAmbulancia(cfg.worker_id, infra.filas_eventos[cfg.worker_id], infra.repo, relogio,
                         criar_roteador(rodada.roteador, cfg), infra.bases, log, seed=rodada.seed)
    w.iniciar_heartbeat(cfg.heartbeat_seg, parar)
    logging.info(f"{nome}: pronto (heartbeat a cada {cfg.heartbeat_seg}s)")
    loop_servico(w.processar_lote, parar, ocioso_seg=0.0)
    w.aguardar_ciclos(timeout=5)
    w.encerrar()
    log.fechar()
    try:
        chave = enviar_para_s3(cfg.log_dir, cfg.rodada_id, cfg.s3_bucket, nome)
        if chave:
            logging.info(f"event log enviado: s3://{cfg.s3_bucket}/{chave}")
    except Exception as e:  # noqa: BLE001 - upload nunca derruba o encerramento
        logging.warning(f"falha ao enviar event log para o S3: {e!r}")


if __name__ == "__main__":
    main()

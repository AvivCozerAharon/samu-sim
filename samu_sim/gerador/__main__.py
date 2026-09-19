import logging
import threading

from samu_sim.core.config import Config
from samu_sim.core.runtime import (SincronizadorRelogio, configurar_logging, instalar_sinais,
                                   montar_infra, relogio_da_rodada)
from samu_sim.eventlog import EventLogJsonl, enviar_para_s3
from samu_sim.gerador.demanda import GeradorChamados
from samu_sim.gerador.servico import ServicoGerador


def main() -> None:
    cfg = Config.do_ambiente()
    configurar_logging("gerador")
    infra = montar_infra(cfg)
    relogio = relogio_da_rodada(infra.repo)
    rodada = infra.repo.obter_rodada()
    parar = threading.Event()
    instalar_sinais(parar)
    SincronizadorRelogio(relogio, infra.repo, cfg.sync_relogio_seg, parar).iniciar()
    log = EventLogJsonl(cfg.log_dir, relogio, "gerador", cfg.rodada_id)
    chamados = GeradorChamados(infra.bairros, rodada.seed, cfg.chamados_por_dia).gerar_dia(0)
    logging.info(f"gerador: {len(chamados)} chamados/dia, seed={rodada.seed}, fator={relogio.fator}")
    n = ServicoGerador(chamados, infra.fila_chamados, infra.repo, relogio, log).executar(parar)
    log.registrar("gerador_encerrou", publicados=n)
    log.fechar()
    try:
        chave = enviar_para_s3(cfg.log_dir, cfg.rodada_id, cfg.s3_bucket, "gerador")
        if chave:
            logging.info(f"event log enviado: s3://{cfg.s3_bucket}/{chave}")
    except Exception as e:  # noqa: BLE001 - upload nunca derruba o encerramento
        logging.warning(f"falha ao enviar event log para o S3: {e!r}")
    logging.info(f"gerador encerrou: {n} publicados")


if __name__ == "__main__":
    main()

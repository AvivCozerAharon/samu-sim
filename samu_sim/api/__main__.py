import logging
import threading

import uvicorn

from samu_sim.api import criar_app
from samu_sim.cenarios import criar_gerenciador
from samu_sim.core.config import Config
from samu_sim.core.runtime import (SincronizadorRelogio, configurar_logging, montar_infra,
                                   relogio_da_rodada)
from samu_sim.eventlog import EventLogJsonl, enviar_para_s3


def main() -> None:
    cfg = Config.do_ambiente()
    configurar_logging("api")
    infra = montar_infra(cfg)
    relogio = relogio_da_rodada(infra.repo)
    parar = threading.Event()
    SincronizadorRelogio(relogio, infra.repo, cfg.sync_relogio_seg, parar).iniciar()
    log = EventLogJsonl(cfg.log_dir, relogio, "api", cfg.rodada_id)
    app = criar_app(infra.repo, infra.fila_chamados, infra.bases, relogio, log,
                    reaper_timeout_seg=cfg.reaper_timeout_seg, log_dir=cfg.log_dir,
                    rodada_id=cfg.rodada_id, turnos_path="docs/experimentos/turnos.json",
                    gerenciador_cenarios=criar_gerenciador(cfg.cenarios_fator_max), expansao_path="docs/experimentos/expansao.json",
                    fator_max=cfg.cenarios_fator_max, transito=cfg.transito)

    def loop_reaper():
        while not parar.wait(cfg.reaper_intervalo_seg):
            try:
                n = app.state.reaper.executar_uma_vez()
                if n:
                    logging.warning(f"reaper liberou {n} ambulancia(s)")
            except Exception as e:  # noqa: BLE001
                logging.exception(f"erro no reaper: {e!r}")

    threading.Thread(target=loop_reaper, name="reaper", daemon=True).start()
    logging.info(f"api na porta {cfg.api_porta}; reaper a cada {cfg.reaper_intervalo_seg}s")
    uvicorn.run(app, host="0.0.0.0", port=cfg.api_porta, log_level="warning")
    parar.set()
    log.fechar()
    try:
        chave = enviar_para_s3(cfg.log_dir, cfg.rodada_id, cfg.s3_bucket, "api")
        if chave:
            logging.info(f"event log enviado: s3://{cfg.s3_bucket}/{chave}")
    except Exception as e:  # noqa: BLE001 - upload nunca derruba o encerramento
        logging.warning(f"falha ao enviar event log para o S3: {e!r}")


if __name__ == "__main__":
    main()

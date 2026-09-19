import logging
import os
import threading

from samu_sim.core.config import Config
from samu_sim.core.runtime import (SincronizadorRelogio, configurar_logging, instalar_sinais,
                                   loop_servico, montar_infra, relogio_da_rodada)
from samu_sim.despachante.servico import Despachante
from samu_sim.eventlog import EventLogJsonl
from samu_sim.politicas import criar_politica
from samu_sim.roteador import criar_roteador


def main() -> None:
    cfg = Config.do_ambiente()
    nome = f"despachante-{os.environ.get('HOSTNAME', os.getpid())}"
    configurar_logging(nome)
    infra = montar_infra(cfg)
    relogio = relogio_da_rodada(infra.repo)
    rodada = infra.repo.obter_rodada()
    parar = threading.Event()
    instalar_sinais(parar)
    log = EventLogJsonl(cfg.log_dir, relogio, nome, cfg.rodada_id)
    rot = criar_roteador(rodada.roteador, cfg,
                         ao_falhar=lambda m: log.registrar("roteador_fallback", motivo=m))
    d = Despachante(infra.fila_chamados, infra.filas_eventos, infra.repo,
                    criar_politica(rodada.politica), rot, relogio, log)

    def trocar_politica(rod):
        d._politica = criar_politica(rod.politica)

    SincronizadorRelogio(relogio, infra.repo, cfg.sync_relogio_seg, parar, ao_mudar=trocar_politica).iniciar()
    logging.info(f"{nome}: politica={rodada.politica} roteador={rodada.roteador}")
    loop_servico(d.processar_lote, parar, ocioso_seg=0.0)  # FilaSQS ja faz long polling de 1 s
    log.fechar()


if __name__ == "__main__":
    main()

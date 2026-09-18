import threading
from samu_sim.core.modelos import Rodada
from samu_sim.core.runtime import SincronizadorRelogio, relogio_da_rodada
from samu_sim.infra.repositorio import RepositorioMemoria


def rodada(fator, inicio_real, inicio_sim=0.0):
    return Rodada("atual", 1, "mais_proxima", fator, 5, "haversine", inicio_real, inicio_sim)


def test_relogio_da_rodada_usa_checkpoint():
    repo = RepositorioMemoria()
    repo.salvar_rodada(rodada(fator=10, inicio_real=1000.0, inicio_sim=500.0))
    r = relogio_da_rodada(repo, agora_real=lambda: 1003.0)
    assert r.agora_sim() == 530.0 and r.fator == 10


def test_sincronizador_aplica_mudanca_de_fator():
    repo = RepositorioMemoria()
    repo.salvar_rodada(rodada(fator=10, inicio_real=1000.0))
    t = {"v": 1003.0}
    r = relogio_da_rodada(repo, agora_real=lambda: t["v"])
    mudancas = []
    s = SincronizadorRelogio(r, repo, intervalo_seg=0.01, parar=threading.Event(),
                             ao_mudar=lambda rod: mudancas.append(rod.fator))
    assert s.sincronizar_uma_vez() is False          # nada mudou
    repo.salvar_rodada(rodada(fator=2, inicio_real=1003.0, inicio_sim=30.0))
    assert s.sincronizar_uma_vez() is True
    t["v"] = 1008.0
    assert r.agora_sim() == 40.0 and mudancas == [2]

"""Reaper: libera ambulancias cujo worker parou de bater heartbeat e devolve o
chamado (se nao atendido) para a fila. Tambem fecha o outbox: republica chamado
PENDENTE que foi salvo mas nunca chegou a fila. Roda periodicamente dentro da api."""
import time

from samu_sim.core.modelos import PRIORIDADES, Base, StatusAmbulancia, StatusChamado
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio


class Reaper:
    def __init__(self, repo: Repositorio, fila_chamados: "Fila | dict[str, Fila]", bases: dict[str, Base],
                 eventlog: EventLog, timeout_seg: float = 120.0, agora_real=time.time, agora_sim=None):
        self._repo = repo
        self._filas = (fila_chamados if isinstance(fila_chamados, dict)
                       else {p: fila_chamados for p in PRIORIDADES})
        self._bases = bases
        self._log = eventlog
        self._timeout = timeout_seg
        self._agora_real = agora_real
        self._agora_sim = agora_sim  # com ele, a ambulancia liberada fica onde estaria (estimativa)
        self._suspeitos: set[str] = set()  # PENDENTE sem publicar na passada anterior
        self.max_equilibrio = 4  # ambulancias ociosas movidas por passada para reequilibrar

    def executar_uma_vez(self) -> int:
        agora = self._agora_real()
        registro = self._repo.listar_workers()
        vivos = sorted(w for w, ts in registro.items() if agora - ts <= self._timeout)
        mortos = {w for w in registro if w not in vivos}
        ambulancias = self._repo.listar_ambulancias()
        carga = {w: 0 for w in vivos}
        for a in ambulancias:
            if a.worker_id in carga:
                carga[a.worker_id] += 1

        def novo_dono(a) -> str | None:
            # so troca de dono se o atual esta comprovadamente morto e existe alguem vivo
            if a.worker_id not in mortos or not vivos:
                return None
            dono = min(vivos, key=lambda w: carga[w])
            carga[dono] += 1
            return dono

        liberadas = 0
        for a in ambulancias:
            dono = novo_dono(a)
            if a.status == StatusAmbulancia.DISPONIVEL:
                if dono:  # ociosa, mas de um worker morto: o despachante mandaria trabalho para ninguem
                    self._reatribuir(a, dono, "dono_morto")
                continue
            idade = agora - a.heartbeat_em
            if idade <= self._timeout:
                if dono:  # ainda protegida pelo heartbeat da reserva; volta na proxima passada
                    carga[dono] -= 1
                continue
            lat, lon = self._posicao_estimada(a)
            try:
                nova = self._repo.liberar_ambulancia(a.id, a.versao, lat, lon, worker_id=dono)
            except ConflitoVersao:
                continue  # alguem mexeu nela agora; reavalia na proxima passada
            liberadas += 1
            self._log.registrar("reaper_liberou", ambulancia_id=a.id, chamado_id=a.chamado_id, versao=nova.versao,
                                worker_id=a.worker_id, novo_worker=dono, idade_seg=idade,
                                status_anterior=str(a.status))
            if a.chamado_id:
                self._devolver_chamado(a.chamado_id, a.id)
        self._equilibrar(vivos, carga)
        self.republicar_nao_publicados()
        return liberadas

    def _posicao_estimada(self, a) -> tuple[float, float]:
        """O banco so grava a posicao nas transicoes. Uma ambulancia a caminho (ou levando o
        paciente) cujo worker sumiu nao parou na rua: estima onde ela esta pelos horarios
        previstos, como o mapa faz. Sem relogio simulado, fica na ultima posicao gravada."""
        if self._agora_sim is None or not a.chamado_id:
            return a.lat, a.lon
        c = self._repo.obter_chamado(a.chamado_id)
        if c is None:
            return a.lat, a.lon
        agora = self._agora_sim()
        if a.status == StatusAmbulancia.A_CAMINHO and c.despachado_em is not None and (c.chegada_prevista_em or 0) > c.despachado_em:
            origem, destino, t0, t1 = (a.lat, a.lon), (c.lat, c.lon), c.despachado_em, c.chegada_prevista_em
        elif (a.status == StatusAmbulancia.TRANSPORTANDO and c.hospital_id in self._bases and c.transporte_em is not None
              and (c.hospital_previsto_em or 0) > c.transporte_em):
            h = self._bases[c.hospital_id]
            origem, destino, t0, t1 = (a.lat, a.lon), (h.lat, h.lon), c.transporte_em, c.hospital_previsto_em
        else:
            return a.lat, a.lon
        f = min(1.0, max(0.0, (agora - t0) / (t1 - t0)))
        return origem[0] + (destino[0] - origem[0]) * f, origem[1] + (destino[1] - origem[1]) * f

    def _reatribuir(self, a, dono: str, motivo: str) -> bool:
        try:
            nova = self._repo.reatribuir_worker(a.id, a.versao, dono)
        except ConflitoVersao:
            return False
        self._log.registrar("ambulancia_reatribuida", ambulancia_id=a.id, de=a.worker_id, para=dono,
                            versao=nova.versao, motivo=motivo)
        return True

    def _equilibrar(self, vivos: list[str], carga: dict[str, int]) -> None:
        """Quando um worker volta, ele esta vazio: passa algumas ambulancias ociosas dos mais
        carregados para ele (poucas por passada, so as disponiveis, sempre condicional)."""
        if len(vivos) < 2:
            return
        movidas = 0
        while movidas < self.max_equilibrio:
            cheio, vazio = max(vivos, key=lambda w: carga[w]), min(vivos, key=lambda w: carga[w])
            if carga[cheio] - carga[vazio] <= 1:
                return
            ociosas = [a for a in self._repo.listar_ambulancias(StatusAmbulancia.DISPONIVEL, worker_id=cheio)]
            if not ociosas or not self._reatribuir(ociosas[0], vazio, "equilibrio"):
                return
            carga[cheio] -= 1
            carga[vazio] += 1
            movidas += 1

    def _devolver_chamado(self, chamado_id: str, ambulancia_id: str) -> None:
        c = self._repo.obter_chamado(chamado_id)
        if c is None or c.status != StatusChamado.DESPACHADO or c.ambulancia_id != ambulancia_id:
            return  # ja atendido, ou ja redespachado para outra ambulancia: nao mexe
        c.status = StatusChamado.PENDENTE
        c.ambulancia_id = None
        c.despachado_em = None
        c.tentativas += 1
        try:
            # condicional: entre o obter e o salvar, outro processo pode ter mexido nele
            self._repo.salvar_chamado_se(c, StatusChamado.DESPACHADO, ambulancia_id, publicado=False)
        except ConflitoVersao:
            self._log.registrar("devolucao_ignorada", chamado_id=chamado_id, ambulancia_id=ambulancia_id)
            return
        self._log.registrar("chamado_devolvido", chamado_id=chamado_id, ambulancia_id=ambulancia_id,
                            tentativas=c.tentativas)
        self._publicar(c)

    def republicar_nao_publicados(self) -> int:
        """Outbox: PENDENTE com publicado=False em duas passadas seguidas (>= 1 intervalo do
        reaper) morreu entre salvar e publicar. Republica; duplicata e inofensiva, porque o
        despachante e idempotente por status do chamado."""
        agora = {c.id: c for c in self._repo.listar_chamados()
                 if c.status == StatusChamado.PENDENTE and c.publicado is False}
        republicados = self._suspeitos & agora.keys()
        for cid in republicados:
            self._publicar(agora[cid])
            self._log.registrar("chamado_republicado", chamado_id=cid)
        self._suspeitos = set(agora) - republicados
        return len(republicados)

    def _publicar(self, c) -> None:
        self._filas[c.prioridade].publicar({"chamado_id": c.id, "lat": c.lat, "lon": c.lon,
                                            "prioridade": c.prioridade, "bairro": c.bairro,
                                            "zona": c.zona, "criado_em": c.criado_em})
        self._repo.marcar_publicado(c.id)

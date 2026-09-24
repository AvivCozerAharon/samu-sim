"""Repositorio de estado. A implementacao em memoria imita o DynamoDB:
atualizacoes condicionais em (status, versao) e copias em toda leitura."""
import threading
from dataclasses import replace
from typing import Protocol

from samu_sim.core.modelos import (
    Ambulancia, Chamado, Rodada, StatusAmbulancia, StatusChamado, transicao_valida,
)


class ConflitoVersao(Exception):
    """A condicao (status, versao) nao bateu: outro processo mudou o registro."""


class Repositorio(Protocol):
    def salvar_ambulancia(self, a: Ambulancia) -> None: ...
    def obter_ambulancia(self, id: str) -> Ambulancia | None: ...
    def listar_ambulancias(self, status: StatusAmbulancia | None = None,
                           worker_id: str | None = None) -> list[Ambulancia]: ...
    def reservar_ambulancia(self, id: str, versao: int, chamado_id: str,
                            heartbeat_em: float = 0.0) -> Ambulancia: ...
    def atualizar_heartbeat(self, id: str, ts: float) -> None: ...
    def atualizar_posicao_se_disponivel(self, id: str, lat: float, lon: float) -> bool: ...
    def liberar_ambulancia(self, id: str, versao: int, lat: float, lon: float,
                           worker_id: str | None = None) -> Ambulancia: ...
    def reatribuir_worker(self, id: str, versao: int, worker_id: str) -> Ambulancia: ...
    def registrar_worker(self, worker_id: str, ts: float) -> None: ...
    def listar_workers(self) -> dict[str, float]: ...
    def transicionar(self, id: str, de: StatusAmbulancia, para: StatusAmbulancia,
                     versao: int, **campos) -> Ambulancia: ...
    def salvar_chamado(self, c: Chamado) -> None: ...
    def criar_chamado(self, c: Chamado) -> bool: ...
    def salvar_chamado_se(self, c: Chamado, status: StatusChamado, ambulancia_id: str | None,
                          publicado: bool | None = None) -> None: ...
    def marcar_publicado(self, id: str) -> None: ...
    def obter_chamado(self, id: str) -> Chamado | None: ...
    def listar_chamados(self) -> list[Chamado]: ...
    def salvar_rodada(self, r: Rodada) -> None: ...
    def obter_rodada(self) -> Rodada | None: ...


class RepositorioMemoria:
    def __init__(self):
        self._amb: dict[str, Ambulancia] = {}
        self._ch: dict[str, Chamado] = {}
        self._rodada: Rodada | None = None
        self._workers: dict[str, float] = {}
        self._lock = threading.Lock()

    # --- ambulancias ---
    def salvar_ambulancia(self, a: Ambulancia) -> None:
        with self._lock:
            self._amb[a.id] = replace(a)

    def obter_ambulancia(self, id: str) -> Ambulancia | None:
        with self._lock:
            a = self._amb.get(id)
            return replace(a) if a else None

    def listar_ambulancias(self, status: StatusAmbulancia | None = None,
                           worker_id: str | None = None) -> list[Ambulancia]:
        with self._lock:
            return [replace(a) for a in self._amb.values()
                    if (status is None or a.status == status)
                    and (worker_id is None or a.worker_id == worker_id)]

    def atualizar_heartbeat(self, id: str, ts: float) -> None:
        """Grava so o heartbeat, sem mexer na versao (nao invalida transicoes em voo)."""
        with self._lock:
            a = self._amb.get(id)
            if a is not None:
                self._amb[id] = replace(a, heartbeat_em=ts)

    def atualizar_posicao_se_disponivel(self, id: str, lat: float, lon: float) -> bool:
        """Move uma ambulancia disponivel (retorno a base) sem mexer na versao; se ela foi
        reservada no meio do caminho, nao mexe e devolve False."""
        with self._lock:
            a = self._amb.get(id)
            if a is None or a.status != StatusAmbulancia.DISPONIVEL:
                return False
            self._amb[id] = replace(a, lat=lat, lon=lon)
            return True

    def liberar_ambulancia(self, id: str, versao: int, lat: float, lon: float,
                           worker_id: str | None = None) -> Ambulancia:
        """Usado pelo reaper: forca DISPONIVEL de qualquer estado, condicional so na versao.
        Com worker_id, a ambulancia muda de dono (o anterior morreu)."""
        with self._lock:
            a = self._amb.get(id)
            if a is None or a.versao != versao:
                raise ConflitoVersao(f"{id}: esperado v{versao}, atual v{a.versao if a else None}")
            novo = replace(a, status=StatusAmbulancia.DISPONIVEL, chamado_id=None, lat=lat, lon=lon,
                           worker_id=worker_id or a.worker_id, versao=versao + 1)
            self._amb[id] = novo
            return replace(novo)

    def reatribuir_worker(self, id: str, versao: int, worker_id: str) -> Ambulancia:
        """Troca o dono de uma ambulancia ociosa (condicional em DISPONIVEL e na versao)."""
        with self._lock:
            a = self._amb.get(id)
            if a is None or a.versao != versao or a.status != StatusAmbulancia.DISPONIVEL:
                raise ConflitoVersao(f"{id}: nao esta disponivel na v{versao}")
            novo = replace(a, worker_id=worker_id, versao=versao + 1)
            self._amb[id] = novo
            return replace(novo)

    def registrar_worker(self, worker_id: str, ts: float) -> None:
        with self._lock:
            self._workers[worker_id] = ts

    def listar_workers(self) -> dict[str, float]:
        with self._lock:
            return dict(self._workers)

    def reservar_ambulancia(self, id: str, versao: int, chamado_id: str,
                            heartbeat_em: float = 0.0) -> Ambulancia:
        return self.transicionar(id, StatusAmbulancia.DISPONIVEL, StatusAmbulancia.RESERVADA,
                                 versao, chamado_id=chamado_id, heartbeat_em=heartbeat_em)

    def transicionar(self, id: str, de: StatusAmbulancia, para: StatusAmbulancia,
                     versao: int, **campos) -> Ambulancia:
        if not transicao_valida(de, para):
            raise ConflitoVersao(f"transicao invalida {de}->{para}")
        with self._lock:
            a = self._amb.get(id)
            if a is None or a.status != de or a.versao != versao:
                raise ConflitoVersao(
                    f"{id}: esperado ({de}, v{versao}), atual "
                    f"({a.status if a else None}, v{a.versao if a else None})")
            novo = replace(a, status=para, versao=versao + 1, **campos)
            self._amb[id] = novo
            return replace(novo)

    # --- chamados ---
    def salvar_chamado(self, c: Chamado) -> None:
        with self._lock:
            self._ch[c.id] = replace(c)

    def criar_chamado(self, c: Chamado) -> bool:
        """Insere so se o id ainda nao existe; False se ja existia (nunca sobrescreve)."""
        with self._lock:
            if c.id in self._ch:
                return False
            self._ch[c.id] = replace(c)
            return True

    def salvar_chamado_se(self, c: Chamado, status: StatusChamado, ambulancia_id: str | None,
                          publicado: bool | None = None) -> None:
        """Grava o chamado so se o registro atual ainda estiver em (status, ambulancia_id).
        Impede que dois processos (despachante x reaper x worker) sobrescrevam um ao outro.
        `publicado` so e gravado se informado; por padrao fica o valor atual."""
        with self._lock:
            atual = self._ch.get(c.id)
            if atual is None or atual.status != status or atual.ambulancia_id != ambulancia_id:
                raise ConflitoVersao(
                    f"{c.id}: esperado ({status}, {ambulancia_id}), atual "
                    f"({atual.status if atual else None}, {atual.ambulancia_id if atual else None})")
            self._ch[c.id] = replace(c, publicado=atual.publicado if publicado is None else publicado)

    def marcar_publicado(self, id: str) -> None:
        """Outbox: o chamado ja esta na fila. So mexe nesse campo."""
        with self._lock:
            c = self._ch.get(id)
            if c is not None:
                self._ch[id] = replace(c, publicado=True)

    def obter_chamado(self, id: str) -> Chamado | None:
        with self._lock:
            c = self._ch.get(id)
            return replace(c) if c else None

    def listar_chamados(self) -> list[Chamado]:
        with self._lock:
            return [replace(c) for c in self._ch.values()]

    # --- rodada ---
    def salvar_rodada(self, r: Rodada) -> None:
        with self._lock:
            self._rodada = replace(r)

    def obter_rodada(self) -> Rodada | None:
        with self._lock:
            return replace(self._rodada) if self._rodada else None

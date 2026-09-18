"""Repositorio de estado. A implementacao em memoria imita o DynamoDB:
atualizacoes condicionais em (status, versao) e copias em toda leitura."""
import threading
from dataclasses import replace
from typing import Protocol

from samu_sim.core.modelos import (
    Ambulancia, Chamado, Rodada, StatusAmbulancia, transicao_valida,
)


class ConflitoVersao(Exception):
    """A condicao (status, versao) nao bateu: outro processo mudou o registro."""


class Repositorio(Protocol):
    def salvar_ambulancia(self, a: Ambulancia) -> None: ...
    def obter_ambulancia(self, id: str) -> Ambulancia | None: ...
    def listar_ambulancias(self, status: StatusAmbulancia | None = None) -> list[Ambulancia]: ...
    def reservar_ambulancia(self, id: str, versao: int, chamado_id: str) -> Ambulancia: ...
    def transicionar(self, id: str, de: StatusAmbulancia, para: StatusAmbulancia,
                     versao: int, **campos) -> Ambulancia: ...
    def salvar_chamado(self, c: Chamado) -> None: ...
    def obter_chamado(self, id: str) -> Chamado | None: ...
    def listar_chamados(self) -> list[Chamado]: ...
    def salvar_rodada(self, r: Rodada) -> None: ...
    def obter_rodada(self) -> Rodada | None: ...


class RepositorioMemoria:
    def __init__(self):
        self._amb: dict[str, Ambulancia] = {}
        self._ch: dict[str, Chamado] = {}
        self._rodada: Rodada | None = None
        self._lock = threading.Lock()

    # --- ambulancias ---
    def salvar_ambulancia(self, a: Ambulancia) -> None:
        with self._lock:
            self._amb[a.id] = replace(a)

    def obter_ambulancia(self, id: str) -> Ambulancia | None:
        with self._lock:
            a = self._amb.get(id)
            return replace(a) if a else None

    def listar_ambulancias(self, status: StatusAmbulancia | None = None) -> list[Ambulancia]:
        with self._lock:
            return [replace(a) for a in self._amb.values() if status is None or a.status == status]

    def reservar_ambulancia(self, id: str, versao: int, chamado_id: str) -> Ambulancia:
        return self.transicionar(id, StatusAmbulancia.DISPONIVEL, StatusAmbulancia.RESERVADA,
                                 versao, chamado_id=chamado_id)

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

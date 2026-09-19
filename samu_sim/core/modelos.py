"""Modelos de dominio do samu-sim. Tempos sao segundos simulados (float)."""
from dataclasses import dataclass
from enum import StrEnum


class StatusAmbulancia(StrEnum):
    DISPONIVEL = "disponivel"
    RESERVADA = "reservada"
    A_CAMINHO = "a_caminho"
    NO_LOCAL = "no_local"
    TRANSPORTANDO = "transportando"  # levando o paciente ao hospital
    RETORNANDO = "retornando"


class StatusChamado(StrEnum):
    PENDENTE = "pendente"
    DESPACHADO = "despachado"
    ATENDIDO = "atendido"


PRIORIDADES = ("vermelho", "amarelo", "verde")  # ordem de atendimento (mais grave primeiro)

TRANSICOES_VALIDAS: set[tuple[StatusAmbulancia, StatusAmbulancia]] = {
    (StatusAmbulancia.DISPONIVEL, StatusAmbulancia.RESERVADA),
    (StatusAmbulancia.RESERVADA, StatusAmbulancia.A_CAMINHO),
    (StatusAmbulancia.A_CAMINHO, StatusAmbulancia.NO_LOCAL),
    (StatusAmbulancia.NO_LOCAL, StatusAmbulancia.TRANSPORTANDO),
    (StatusAmbulancia.NO_LOCAL, StatusAmbulancia.RETORNANDO),
    (StatusAmbulancia.NO_LOCAL, StatusAmbulancia.DISPONIVEL),
    (StatusAmbulancia.TRANSPORTANDO, StatusAmbulancia.RETORNANDO),
    (StatusAmbulancia.TRANSPORTANDO, StatusAmbulancia.DISPONIVEL),
    (StatusAmbulancia.RETORNANDO, StatusAmbulancia.DISPONIVEL),
}


def transicao_valida(de: StatusAmbulancia, para: StatusAmbulancia) -> bool:
    return (de, para) in TRANSICOES_VALIDAS


@dataclass
class Base:
    id: str
    nome: str
    lat: float
    lon: float
    tipo: str = "base"  # hospital | upa (hospitais recebem o transporte do paciente)


@dataclass
class Ambulancia:
    id: str
    base_id: str
    lat: float
    lon: float
    worker_id: str
    status: StatusAmbulancia = StatusAmbulancia.DISPONIVEL
    versao: int = 0
    chamado_id: str | None = None
    heartbeat_em: float = 0.0


@dataclass
class Chamado:
    id: str
    lat: float
    lon: float
    bairro: str
    zona: str
    criado_em: float
    prioridade: str = "verde"  # vermelho (risco de vida) | amarelo (urgente) | verde (pouco urgente)
    tipo: str = "clinico"      # clinico | trauma
    status: StatusChamado = StatusChamado.PENDENTE
    despachado_em: float | None = None
    chegada_prevista_em: float | None = None  # despachado_em + ETA (para o mapa)
    chegada_em: float | None = None
    transporte_em: float | None = None        # saiu do local rumo ao hospital
    hospital_previsto_em: float | None = None # transporte_em + ETA ao hospital
    hospital_id: str | None = None
    liberado_em: float | None = None
    ambulancia_id: str | None = None
    tentativas: int = 0


@dataclass
class Rodada:
    id: str
    seed: int
    politica: str
    fator: float
    n_ambulancias: int
    roteador: str
    inicio_real: float
    inicio_sim: float
    pausada: bool = False

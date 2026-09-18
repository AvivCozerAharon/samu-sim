# samu-sim — Plano D1: núcleo em memória

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ter gerador → despachante → workers de ambulância rodando em-processo (tudo em memória), com política plugável, relógio acelerado, event log e métricas P50/P90 — e a suíte de testes provando idempotência e lock otimista.

**Architecture:** Pacote `samu_sim` com `core` (modelos, relógio, geo, métricas), `infra` (protocolos `Fila` e `Repositorio` + implementações em memória), `roteador` (haversine), `politicas` (mais_proxima, menor_eta), `eventlog`, e os três serviços como classes com método `processar_lote()`/`executar()` que recebem suas dependências por construtor. `samu_sim/local.py` monta tudo em memória com threads. Nada de boto3/FastAPI neste plano — isso é D2.

**Tech Stack:** Python 3.12, stdlib (`dataclasses`, `threading`, `concurrent.futures`, `csv`, `json`, `random`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-18-samu-sim-design.md`

## Global Constraints

- Python 3.12; nomes em português (mesma convenção do spec: `Relogio`, `Fila`, `Repositorio`, `Politica`, `Roteador`).
- Toda dependência externa tem implementação em memória; a suíte roda sem Docker.
- Status de ambulância: `disponivel | reservada | a_caminho | no_local | retornando`. Status de chamado: `pendente | despachado | atendido`.
- Tempo simulado em segundos (`float`) desde o início da rodada; `agora_sim = inicio_sim + (agora_real - inicio_real) * fator`.
- Toda mudança de estado de ambulância passa por `transicionar(...)` condicional em `(status, versao)`; conflito levanta `ConflitoVersao`.
- Zonas: `Centro, Sul, Norte, Oeste, Barra`.
- Commits pequenos, mensagem em português, terminando com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Rodar testes com `python -m pytest -q` a partir de `D:\codes\samu-sim`.

---

## Estrutura de arquivos deste plano

```
samu-sim/
  pyproject.toml
  .gitignore
  samu_sim/__init__.py
  samu_sim/core/__init__.py
  samu_sim/core/modelos.py       dataclasses + enums + TRANSICOES_VALIDAS
  samu_sim/core/geo.py           haversine_km, deslocar
  samu_sim/core/relogio.py       Relogio
  samu_sim/core/metricas.py      calcular(chamados) -> dict
  samu_sim/infra/__init__.py
  samu_sim/infra/fila.py         Mensagem, Fila (Protocol), FilaMemoria
  samu_sim/infra/repositorio.py  ConflitoVersao, Repositorio (Protocol), RepositorioMemoria
  samu_sim/roteador/__init__.py  Roteador (Protocol), RoteadorHaversine
  samu_sim/politicas/__init__.py Politica (Protocol), MaisProxima, MenorEta, criar_politica
  samu_sim/eventlog/__init__.py  EventLog (Protocol), EventLogMemoria, EventLogJsonl
  samu_sim/gerador/__init__.py
  samu_sim/gerador/demanda.py    Bairro, carregar_bairros, GeradorChamados
  samu_sim/gerador/servico.py    ServicoGerador
  samu_sim/despachante/__init__.py
  samu_sim/despachante/servico.py Despachante
  samu_sim/ambulancia/__init__.py
  samu_sim/ambulancia/servico.py WorkerAmbulancia
  samu_sim/local.py              montar_frota, carregar_bases, rodar (+ CLI)
  dados/bairros.csv              ~19 bairros do Rio (centróide + população aprox.)
  dados/bases.csv                10 hospitais/UPAs (coordenadas aprox.)
  tests/test_modelos.py
  tests/test_geo.py
  tests/test_relogio.py
  tests/test_fila.py
  tests/test_repositorio.py
  tests/test_roteador.py
  tests/test_politicas.py
  tests/test_eventlog.py
  tests/test_demanda.py
  tests/test_gerador_servico.py
  tests/test_despachante.py
  tests/test_ambulancia.py
  tests/test_metricas.py
  tests/test_integracao_local.py
```

---

### Task 1: Esqueleto do projeto

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `samu_sim/__init__.py`, `samu_sim/core/__init__.py`, `samu_sim/infra/__init__.py`, `samu_sim/gerador/__init__.py`, `samu_sim/despachante/__init__.py`, `samu_sim/ambulancia/__init__.py`, `tests/__init__.py`
- Test: `tests/test_pacote.py`

**Interfaces:**
- Produces: pacote importável `samu_sim` com `__version__ = "0.1.0"`.

- [ ] **Step 1: Criar `pyproject.toml`**

```toml
[project]
name = "samu-sim"
version = "0.1.0"
description = "Simulador distribuido de despacho de ambulancias (Rio de Janeiro)"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
markers = ["integration: exige Docker/LocalStack"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["samu_sim*"]
```

- [ ] **Step 2: Criar `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
logs/
*.egg-info/
.terraform/
*.tfstate*
```

- [ ] **Step 3: Criar `samu_sim/__init__.py`**

```python
__version__ = "0.1.0"
```

Criar vazios: `samu_sim/core/__init__.py`, `samu_sim/infra/__init__.py`, `samu_sim/gerador/__init__.py`, `samu_sim/despachante/__init__.py`, `samu_sim/ambulancia/__init__.py`, `tests/__init__.py`.

- [ ] **Step 4: Escrever o teste `tests/test_pacote.py`**

```python
import samu_sim


def test_versao():
    assert samu_sim.__version__ == "0.1.0"
```

- [ ] **Step 5: Criar venv, instalar e rodar**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest -q
```
Esperado: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: esqueleto do pacote samu_sim

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Modelos de domínio

**Files:**
- Create: `samu_sim/core/modelos.py`
- Test: `tests/test_modelos.py`

**Interfaces:**
- Produces:
  - `StatusAmbulancia(StrEnum)`: `DISPONIVEL, RESERVADA, A_CAMINHO, NO_LOCAL, RETORNANDO`
  - `StatusChamado(StrEnum)`: `PENDENTE, DESPACHADO, ATENDIDO`
  - `@dataclass Base(id: str, nome: str, lat: float, lon: float)`
  - `@dataclass Ambulancia(id, base_id, lat, lon, worker_id, status=DISPONIVEL, versao=0, chamado_id=None, heartbeat_em=0.0)`
  - `@dataclass Chamado(id, lat, lon, bairro, zona, criado_em, status=PENDENTE, despachado_em=None, chegada_em=None, liberado_em=None, ambulancia_id=None, tentativas=0)`
  - `@dataclass Rodada(id, seed, politica, fator, n_ambulancias, roteador, inicio_real, inicio_sim, pausada=False)`
  - `TRANSICOES_VALIDAS: set[tuple[StatusAmbulancia, StatusAmbulancia]]`
  - `transicao_valida(de, para) -> bool`

- [ ] **Step 1: Escrever o teste**

```python
from samu_sim.core.modelos import (
    Ambulancia, Chamado, StatusAmbulancia as SA, StatusChamado as SC, transicao_valida,
)


def test_ambulancia_nasce_disponivel_versao_zero():
    a = Ambulancia(id="amb-1", base_id="base-1", lat=-22.9, lon=-43.2, worker_id="w1")
    assert a.status == SA.DISPONIVEL
    assert a.versao == 0
    assert a.chamado_id is None


def test_chamado_nasce_pendente():
    c = Chamado(id="ch-1", lat=-22.9, lon=-43.2, bairro="Centro", zona="Centro", criado_em=0.0)
    assert c.status == SC.PENDENTE
    assert c.tentativas == 0


def test_transicoes_validas():
    assert transicao_valida(SA.DISPONIVEL, SA.RESERVADA)
    assert transicao_valida(SA.RESERVADA, SA.A_CAMINHO)
    assert transicao_valida(SA.A_CAMINHO, SA.NO_LOCAL)
    assert transicao_valida(SA.NO_LOCAL, SA.RETORNANDO)
    assert transicao_valida(SA.NO_LOCAL, SA.DISPONIVEL)
    assert transicao_valida(SA.RETORNANDO, SA.DISPONIVEL)


def test_transicoes_invalidas():
    assert not transicao_valida(SA.DISPONIVEL, SA.A_CAMINHO)
    assert not transicao_valida(SA.A_CAMINHO, SA.RESERVADA)
    assert not transicao_valida(SA.A_CAMINHO, SA.A_CAMINHO)


def test_status_serializa_como_string():
    assert SA.A_CAMINHO == "a_caminho"
    assert str(SC.ATENDIDO) == "atendido"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_modelos.py -q`
Esperado: FAIL com `ModuleNotFoundError: samu_sim.core.modelos`.

- [ ] **Step 3: Implementar `samu_sim/core/modelos.py`**

```python
"""Modelos de dominio do samu-sim. Tempos sao segundos simulados (float)."""
from dataclasses import dataclass
from enum import StrEnum


class StatusAmbulancia(StrEnum):
    DISPONIVEL = "disponivel"
    RESERVADA = "reservada"
    A_CAMINHO = "a_caminho"
    NO_LOCAL = "no_local"
    RETORNANDO = "retornando"


class StatusChamado(StrEnum):
    PENDENTE = "pendente"
    DESPACHADO = "despachado"
    ATENDIDO = "atendido"


TRANSICOES_VALIDAS: set[tuple[StatusAmbulancia, StatusAmbulancia]] = {
    (StatusAmbulancia.DISPONIVEL, StatusAmbulancia.RESERVADA),
    (StatusAmbulancia.RESERVADA, StatusAmbulancia.A_CAMINHO),
    (StatusAmbulancia.A_CAMINHO, StatusAmbulancia.NO_LOCAL),
    (StatusAmbulancia.NO_LOCAL, StatusAmbulancia.RETORNANDO),
    (StatusAmbulancia.NO_LOCAL, StatusAmbulancia.DISPONIVEL),
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
    status: StatusChamado = StatusChamado.PENDENTE
    despachado_em: float | None = None
    chegada_em: float | None = None
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_modelos.py -q`
Esperado: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/core/modelos.py tests/test_modelos.py
git commit -m "feat(core): modelos de dominio e transicoes validas

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Geo (haversine)

**Files:**
- Create: `samu_sim/core/geo.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces:
  - `haversine_km(lat1, lon1, lat2, lon2) -> float`
  - `deslocar(lat, lon, dist_km, rumo_graus) -> tuple[float, float]` (ponto a `dist_km` na direção `rumo_graus`, 0 = norte)

- [ ] **Step 1: Escrever o teste**

```python
import pytest
from samu_sim.core.geo import haversine_km, deslocar

COPACABANA = (-22.9711, -43.1822)
CENTRO = (-22.9068, -43.1829)


def test_haversine_copacabana_centro_aprox_7km():
    d = haversine_km(*COPACABANA, *CENTRO)
    assert d == pytest.approx(7.15, abs=0.2)


def test_haversine_mesmo_ponto_zero():
    assert haversine_km(*CENTRO, *CENTRO) == 0.0


def test_deslocar_volta_distancia_pedida():
    lat, lon = deslocar(*CENTRO, dist_km=2.0, rumo_graus=90)
    assert haversine_km(*CENTRO, lat, lon) == pytest.approx(2.0, abs=0.01)
    assert lon > CENTRO[1]  # rumo 90 = leste
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_geo.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/core/geo.py`**

```python
import math

RAIO_TERRA_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAIO_TERRA_KM * math.asin(math.sqrt(a))


def deslocar(lat: float, lon: float, dist_km: float, rumo_graus: float) -> tuple[float, float]:
    """Ponto a dist_km de (lat, lon) na direcao rumo_graus (0 = norte, 90 = leste)."""
    d = dist_km / RAIO_TERRA_KM
    rumo = math.radians(rumo_graus)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(rumo))
    l2 = l1 + math.atan2(
        math.sin(rumo) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), math.degrees(l2)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_geo.py -q`
Esperado: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/core/geo.py tests/test_geo.py
git commit -m "feat(core): haversine e deslocamento geografico

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Relógio simulado

**Files:**
- Create: `samu_sim/core/relogio.py`
- Test: `tests/test_relogio.py`

**Interfaces:**
- Produces: `Relogio(fator=1.0, inicio_sim=0.0, agora_real=time.monotonic, dormir_real=time.sleep)` com:
  - `fator` (property), `agora_sim() -> float`, `definir_fator(novo: float) -> None`, `dormir_sim(segundos: float) -> None`
  - `checkpoint() -> tuple[float, float]` = `(inicio_real, inicio_sim)`

- [ ] **Step 1: Escrever o teste** (relógio real substituído por um fake controlável)

```python
import pytest
from samu_sim.core.relogio import Relogio


class RelogioFake:
    def __init__(self):
        self.t = 100.0
        self.dormidas = []

    def agora(self):
        return self.t

    def dormir(self, s):
        self.dormidas.append(s)
        self.t += s


def test_agora_sim_avanca_com_fator():
    f = RelogioFake()
    r = Relogio(fator=10, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 3.0
    assert r.agora_sim() == pytest.approx(30.0)


def test_definir_fator_nao_salta_o_tempo():
    f = RelogioFake()
    r = Relogio(fator=10, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 3.0  # sim = 30
    r.definir_fator(2)
    assert r.agora_sim() == pytest.approx(30.0)
    f.t += 5.0  # + 10 sim
    assert r.agora_sim() == pytest.approx(40.0)


def test_dormir_sim_divide_pelo_fator():
    f = RelogioFake()
    r = Relogio(fator=20, agora_real=f.agora, dormir_real=f.dormir)
    r.dormir_sim(60)
    assert r.agora_sim() == pytest.approx(60.0)
    assert sum(f.dormidas) == pytest.approx(3.0)


def test_dormir_sim_em_pedacos_respeita_mudanca_de_fator():
    f = RelogioFake()
    r = Relogio(fator=1, agora_real=f.agora, dormir_real=f.dormir)
    # troca o fator no meio: cada pedaco tem no maximo 0.5 s reais
    chamadas = {"n": 0}
    dormir_original = f.dormir

    def dormir_e_acelera(s):
        dormir_original(s)
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            r.definir_fator(100)

    r._dormir_real = dormir_e_acelera
    r.dormir_sim(10)
    assert r.agora_sim() == pytest.approx(10.0, abs=0.01)
    assert sum(f.dormidas) < 5.0  # acelerou apos o 2o pedaco
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_relogio.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/core/relogio.py`**

```python
"""Relogio simulado: agora_sim = inicio_sim + (agora_real - inicio_real) * fator.

Mudar o fator grava um novo checkpoint, entao o tempo simulado nunca salta.
dormir_sim dorme em pedacos de no maximo PEDACO_MAX_REAL segundos reais para
que uma mudanca de fator feita por outra thread seja respeitada.
"""
import threading
import time

PEDACO_MAX_REAL = 0.5


class Relogio:
    def __init__(self, fator: float = 1.0, inicio_sim: float = 0.0,
                 agora_real=time.monotonic, dormir_real=time.sleep):
        self._agora_real = agora_real
        self._dormir_real = dormir_real
        self._lock = threading.Lock()
        self._fator = float(fator)
        self._inicio_sim = float(inicio_sim)
        self._inicio_real = agora_real()

    @property
    def fator(self) -> float:
        return self._fator

    def checkpoint(self) -> tuple[float, float]:
        with self._lock:
            return self._inicio_real, self._inicio_sim

    def agora_sim(self) -> float:
        with self._lock:
            return self._inicio_sim + (self._agora_real() - self._inicio_real) * self._fator

    def definir_fator(self, novo: float) -> None:
        with self._lock:
            agora_real = self._agora_real()
            self._inicio_sim = self._inicio_sim + (agora_real - self._inicio_real) * self._fator
            self._inicio_real = agora_real
            self._fator = float(novo)

    def dormir_sim(self, segundos: float) -> None:
        alvo = self.agora_sim() + segundos
        while True:
            resta_sim = alvo - self.agora_sim()
            if resta_sim <= 0:
                return
            self._dormir_real(min(resta_sim / self._fator, PEDACO_MAX_REAL))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_relogio.py -q`
Esperado: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/core/relogio.py tests/test_relogio.py
git commit -m "feat(core): relogio simulado com fator ajustavel sem salto

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Fila em memória (semântica SQS)

**Files:**
- Create: `samu_sim/infra/fila.py`
- Test: `tests/test_fila.py`

**Interfaces:**
- Produces:
  - `@dataclass Mensagem(id: str, corpo: dict, handle: object = None)`
  - `class Fila(Protocol)`: `publicar(corpo: dict) -> None`, `receber(max_msgs: int = 10) -> list[Mensagem]`, `ack(msg: Mensagem) -> None`
  - `FilaMemoria(visibilidade_seg: float = 30.0, agora=time.monotonic)` — mensagens recebidas ficam invisíveis por `visibilidade_seg` segundos reais; sem `ack` voltam a ser entregues. `tamanho() -> int` conta visíveis + em voo.

- [ ] **Step 1: Escrever o teste**

```python
from samu_sim.infra.fila import FilaMemoria


class Tempo:
    t = 0.0

    def agora(self):
        return self.t


def test_publicar_receber_ack():
    f = FilaMemoria()
    f.publicar({"x": 1})
    msgs = f.receber()
    assert len(msgs) == 1 and msgs[0].corpo == {"x": 1}
    f.ack(msgs[0])
    assert f.receber() == []
    assert f.tamanho() == 0


def test_sem_ack_reentrega_apos_visibilidade():
    tempo = Tempo()
    f = FilaMemoria(visibilidade_seg=30, agora=tempo.agora)
    f.publicar({"x": 1})
    m1 = f.receber()[0]
    assert f.receber() == []          # invisivel
    tempo.t = 31
    m2 = f.receber()[0]               # reentregue
    assert m2.corpo == m1.corpo
    assert f.tamanho() == 1


def test_receber_respeita_max_e_ordem_fifo():
    f = FilaMemoria()
    for i in range(5):
        f.publicar({"i": i})
    lote = f.receber(max_msgs=3)
    assert [m.corpo["i"] for m in lote] == [0, 1, 2]


def test_ack_de_mensagem_ja_reentregue_nao_quebra():
    tempo = Tempo()
    f = FilaMemoria(visibilidade_seg=1, agora=tempo.agora)
    f.publicar({"x": 1})
    m1 = f.receber()[0]
    tempo.t = 2
    m2 = f.receber()[0]
    f.ack(m1)  # handle antigo: SQS ignoraria; aqui tambem remove (mesmo id)
    assert f.tamanho() == 0
    f.ack(m2)  # idempotente
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_fila.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/infra/fila.py`**

```python
"""Fila com semantica de SQS standard: at-least-once, visibility timeout, ack explicito."""
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Mensagem:
    id: str
    corpo: dict
    handle: object = None


class Fila(Protocol):
    def publicar(self, corpo: dict) -> None: ...
    def receber(self, max_msgs: int = 10) -> list[Mensagem]: ...
    def ack(self, msg: Mensagem) -> None: ...


@dataclass
class _Item:
    msg: Mensagem
    visivel_em: float = 0.0


class FilaMemoria:
    def __init__(self, visibilidade_seg: float = 30.0, agora=time.monotonic):
        self._visibilidade = visibilidade_seg
        self._agora = agora
        self._itens: list[_Item] = []
        self._lock = threading.Lock()

    def publicar(self, corpo: dict) -> None:
        with self._lock:
            self._itens.append(_Item(Mensagem(id=uuid.uuid4().hex, corpo=dict(corpo))))

    def receber(self, max_msgs: int = 10) -> list[Mensagem]:
        agora = self._agora()
        entregues: list[Mensagem] = []
        with self._lock:
            for item in self._itens:
                if len(entregues) >= max_msgs:
                    break
                if item.visivel_em <= agora:
                    item.visivel_em = agora + self._visibilidade
                    entregues.append(Mensagem(item.msg.id, dict(item.msg.corpo), handle=item.msg.id))
        return entregues

    def ack(self, msg: Mensagem) -> None:
        with self._lock:
            self._itens = [i for i in self._itens if i.msg.id != msg.id]

    def tamanho(self) -> int:
        with self._lock:
            return len(self._itens)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_fila.py -q`
Esperado: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/infra/fila.py tests/test_fila.py
git commit -m "feat(infra): fila em memoria com visibility timeout e ack

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Repositório em memória com lock otimista

**Files:**
- Create: `samu_sim/infra/repositorio.py`
- Test: `tests/test_repositorio.py`

**Interfaces:**
- Produces:
  - `class ConflitoVersao(Exception)`
  - `class Repositorio(Protocol)`:
    - `salvar_ambulancia(a: Ambulancia) -> None`
    - `obter_ambulancia(id: str) -> Ambulancia | None`
    - `listar_ambulancias(status: StatusAmbulancia | None = None) -> list[Ambulancia]`
    - `reservar_ambulancia(id: str, versao: int, chamado_id: str) -> Ambulancia` — condição `status == DISPONIVEL and versao == versao`; grava `RESERVADA`, `chamado_id`, `versao+1`.
    - `transicionar(id: str, de: StatusAmbulancia, para: StatusAmbulancia, versao: int, **campos) -> Ambulancia` — condição `status == de and versao == versao` e `transicao_valida(de, para)`; aplica `campos` (`lat`, `lon`, `chamado_id`, `heartbeat_em`); `versao+1`.
    - `salvar_chamado(c: Chamado) -> None`, `obter_chamado(id) -> Chamado | None`, `listar_chamados() -> list[Chamado]`
    - `salvar_rodada(r: Rodada) -> None`, `obter_rodada() -> Rodada | None`
  - `RepositorioMemoria()` — thread-safe; devolve cópias (nunca o objeto interno).

- [ ] **Step 1: Escrever o teste**

```python
import threading
import pytest
from samu_sim.core.modelos import Ambulancia, Chamado, StatusAmbulancia as SA
from samu_sim.infra.repositorio import RepositorioMemoria, ConflitoVersao


def amb(id="amb-1"):
    return Ambulancia(id=id, base_id="b1", lat=-22.9, lon=-43.2, worker_id="w1")


def test_salvar_e_obter_devolve_copia():
    r = RepositorioMemoria()
    a = amb()
    r.salvar_ambulancia(a)
    a.lat = 0.0
    assert r.obter_ambulancia("amb-1").lat == -22.9


def test_listar_por_status():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb("a"))
    b = amb("b"); b.status = SA.A_CAMINHO
    r.salvar_ambulancia(b)
    assert [x.id for x in r.listar_ambulancias(SA.DISPONIVEL)] == ["a"]
    assert len(r.listar_ambulancias()) == 2


def test_reservar_incrementa_versao_e_marca_chamado():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    a = r.reservar_ambulancia("amb-1", versao=0, chamado_id="ch-1")
    assert a.status == SA.RESERVADA and a.versao == 1 and a.chamado_id == "ch-1"


def test_reservar_com_versao_errada_conflita():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    r.reservar_ambulancia("amb-1", versao=0, chamado_id="ch-1")
    with pytest.raises(ConflitoVersao):
        r.reservar_ambulancia("amb-1", versao=0, chamado_id="ch-2")


def test_transicionar_valida_e_aplica_campos():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    a = r.reservar_ambulancia("amb-1", 0, "ch-1")
    a = r.transicionar("amb-1", SA.RESERVADA, SA.A_CAMINHO, a.versao)
    a = r.transicionar("amb-1", SA.A_CAMINHO, SA.NO_LOCAL, a.versao, lat=-23.0, lon=-43.3)
    assert a.status == SA.NO_LOCAL and a.lat == -23.0 and a.versao == 3


def test_transicionar_estado_errado_conflita():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    with pytest.raises(ConflitoVersao):
        r.transicionar("amb-1", SA.A_CAMINHO, SA.NO_LOCAL, 0)


def test_transicao_invalida_e_rejeitada_mesmo_com_versao_certa():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    with pytest.raises(ConflitoVersao):
        r.transicionar("amb-1", SA.DISPONIVEL, SA.A_CAMINHO, 0)


def test_dois_despachantes_so_um_reserva():
    """Lock otimista: 20 threads disputam a mesma ambulancia com a mesma versao."""
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    sucessos, conflitos = [], []
    barreira = threading.Barrier(20)

    def tenta(i):
        barreira.wait()
        try:
            r.reservar_ambulancia("amb-1", versao=0, chamado_id=f"ch-{i}")
            sucessos.append(i)
        except ConflitoVersao:
            conflitos.append(i)

    ts = [threading.Thread(target=tenta, args=(i,)) for i in range(20)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(sucessos) == 1 and len(conflitos) == 19


def test_chamado_e_rodada():
    from samu_sim.core.modelos import Rodada
    r = RepositorioMemoria()
    r.salvar_chamado(Chamado(id="ch-1", lat=0, lon=0, bairro="X", zona="Sul", criado_em=0))
    assert r.obter_chamado("ch-1").bairro == "X"
    assert r.obter_chamado("nao-existe") is None
    assert r.obter_rodada() is None
    r.salvar_rodada(Rodada("r1", 1, "mais_proxima", 10, 5, "haversine", 0, 0))
    assert r.obter_rodada().fator == 10
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_repositorio.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/infra/repositorio.py`**

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_repositorio.py -q`
Esperado: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/infra/repositorio.py tests/test_repositorio.py
git commit -m "feat(infra): repositorio em memoria com lock otimista por versao

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Roteador haversine

**Files:**
- Create: `samu_sim/roteador/__init__.py`
- Test: `tests/test_roteador.py`

**Interfaces:**
- Produces:
  - `Ponto = tuple[float, float]` (lat, lon)
  - `class Roteador(Protocol)`: `nome: str`; `eta(origem: Ponto, destino: Ponto) -> float` (segundos simulados)
  - `RoteadorHaversine(vel_kmh: float = 30.0)`, `nome = "haversine"`
  - `criar_roteador(nome: str) -> Roteador` (só `"haversine"` neste plano; outro nome → `ValueError`)

- [ ] **Step 1: Escrever o teste**

```python
import pytest
from samu_sim.roteador import RoteadorHaversine, criar_roteador

COPACABANA = (-22.9711, -43.1822)
CENTRO = (-22.9068, -43.1829)


def test_eta_a_30kmh():
    r = RoteadorHaversine(vel_kmh=30)
    # ~7.15 km a 30 km/h = ~858 s
    assert r.eta(COPACABANA, CENTRO) == pytest.approx(858, abs=30)


def test_eta_mesmo_ponto_zero():
    assert RoteadorHaversine().eta(CENTRO, CENTRO) == 0.0


def test_criar_roteador():
    assert criar_roteador("haversine").nome == "haversine"
    with pytest.raises(ValueError):
        criar_roteador("teletransporte")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_roteador.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/roteador/__init__.py`**

```python
"""Roteador: tempo estimado de viagem (segundos simulados) entre dois pontos."""
from typing import Protocol

from samu_sim.core.geo import haversine_km

Ponto = tuple[float, float]  # (lat, lon)


class Roteador(Protocol):
    nome: str

    def eta(self, origem: Ponto, destino: Ponto) -> float: ...


class RoteadorHaversine:
    nome = "haversine"

    def __init__(self, vel_kmh: float = 30.0):
        self._vel_kmh = vel_kmh

    def eta(self, origem: Ponto, destino: Ponto) -> float:
        km = haversine_km(origem[0], origem[1], destino[0], destino[1])
        return km / self._vel_kmh * 3600.0


def criar_roteador(nome: str) -> Roteador:
    if nome == "haversine":
        return RoteadorHaversine()
    raise ValueError(f"roteador desconhecido: {nome}")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_roteador.py -q`
Esperado: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/roteador/__init__.py tests/test_roteador.py
git commit -m "feat(roteador): interface Roteador e implementacao haversine

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Políticas de despacho

**Files:**
- Create: `samu_sim/politicas/__init__.py`
- Test: `tests/test_politicas.py`

**Interfaces:**
- Consumes: `Roteador.eta`, `haversine_km`, `Ambulancia`, `Chamado`.
- Produces:
  - `class Politica(Protocol)`: `nome: str`; `escolher(chamado: Chamado, disponiveis: list[Ambulancia], roteador: Roteador) -> list[Ambulancia]` (ordenada, melhor primeiro)
  - `MaisProxima` (`nome="mais_proxima"`, ordena por haversine sem consultar roteador)
  - `MenorEta` (`nome="menor_eta"`, ordena por `roteador.eta`)
  - `criar_politica(nome: str) -> Politica` (desconhecida → `ValueError`)

- [ ] **Step 1: Escrever o teste**

```python
import pytest
from samu_sim.core.modelos import Ambulancia, Chamado
from samu_sim.politicas import MaisProxima, MenorEta, criar_politica
from samu_sim.roteador import RoteadorHaversine


def amb(id, lat, lon):
    return Ambulancia(id=id, base_id="b", lat=lat, lon=lon, worker_id="w1")


CHAMADO = Chamado(id="ch", lat=-22.90, lon=-43.20, bairro="X", zona="Centro", criado_em=0)
LONGE = amb("longe", -23.00, -43.50)
PERTO = amb("perto", -22.91, -43.21)
MEDIA = amb("media", -22.95, -43.25)


def test_mais_proxima_ordena_por_distancia():
    ordem = MaisProxima().escolher(CHAMADO, [LONGE, PERTO, MEDIA], RoteadorHaversine())
    assert [a.id for a in ordem] == ["perto", "media", "longe"]


def test_menor_eta_usa_roteador():
    class RoteadorInvertido:
        nome = "invertido"
        def eta(self, o, d):
            # quanto mais longe, menor o "eta" -> inverte a ordem de proposito
            return -RoteadorHaversine().eta(o, d)

    ordem = MenorEta().escolher(CHAMADO, [LONGE, PERTO, MEDIA], RoteadorInvertido())
    assert [a.id for a in ordem] == ["longe", "media", "perto"]


def test_lista_vazia():
    assert MaisProxima().escolher(CHAMADO, [], RoteadorHaversine()) == []


def test_criar_politica():
    assert criar_politica("mais_proxima").nome == "mais_proxima"
    assert criar_politica("menor_eta").nome == "menor_eta"
    with pytest.raises(ValueError):
        criar_politica("aleatoria")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_politicas.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/politicas/__init__.py`**

```python
"""Politicas de despacho: dado um chamado e as ambulancias disponiveis,
devolvem as candidatas em ordem de preferencia. O despachante tenta reservar
na ordem; se perder a corrida para outro despachante, passa para a proxima."""
from typing import Protocol

from samu_sim.core.geo import haversine_km
from samu_sim.core.modelos import Ambulancia, Chamado
from samu_sim.roteador import Roteador


class Politica(Protocol):
    nome: str

    def escolher(self, chamado: Chamado, disponiveis: list[Ambulancia],
                 roteador: Roteador) -> list[Ambulancia]: ...


class MaisProxima:
    nome = "mais_proxima"

    def escolher(self, chamado, disponiveis, roteador):
        return sorted(disponiveis,
                      key=lambda a: haversine_km(a.lat, a.lon, chamado.lat, chamado.lon))


class MenorEta:
    nome = "menor_eta"

    def escolher(self, chamado, disponiveis, roteador):
        destino = (chamado.lat, chamado.lon)
        return sorted(disponiveis, key=lambda a: roteador.eta((a.lat, a.lon), destino))


_POLITICAS = {"mais_proxima": MaisProxima, "menor_eta": MenorEta}


def criar_politica(nome: str) -> Politica:
    try:
        return _POLITICAS[nome]()
    except KeyError:
        raise ValueError(f"politica desconhecida: {nome}") from None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_politicas.py -q`
Esperado: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/politicas/__init__.py tests/test_politicas.py
git commit -m "feat(politicas): mais_proxima e menor_eta

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Event log

**Files:**
- Create: `samu_sim/eventlog/__init__.py`
- Test: `tests/test_eventlog.py`

**Interfaces:**
- Consumes: `Relogio.agora_sim()`.
- Produces:
  - `class EventLog(Protocol)`: `registrar(tipo: str, **campos) -> None`
  - `EventLogMemoria(relogio, servico: str, rodada_id: str = "local")` com `.eventos: list[dict]` e `contar(tipo) -> int`
  - `EventLogJsonl(diretorio: str | Path, relogio, servico: str, rodada_id: str)` — escreve `<diretorio>/<rodada_id>/<servico>.jsonl`, uma linha por evento, flush a cada escrita, thread-safe.
  - Campos comuns em todo evento: `ts_sim, ts_real, rodada_id, servico, tipo`.

- [ ] **Step 1: Escrever o teste**

```python
import json
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria, EventLogJsonl


def test_memoria_registra_campos_comuns():
    r = Relogio(fator=1)
    log = EventLogMemoria(r, servico="teste", rodada_id="r1")
    log.registrar("chamado_criado", chamado_id="ch-1")
    e = log.eventos[0]
    assert e["tipo"] == "chamado_criado" and e["chamado_id"] == "ch-1"
    assert e["servico"] == "teste" and e["rodada_id"] == "r1"
    assert "ts_sim" in e and "ts_real" in e
    assert log.contar("chamado_criado") == 1 and log.contar("outro") == 0


def test_jsonl_escreve_uma_linha_por_evento(tmp_path):
    r = Relogio(fator=1)
    log = EventLogJsonl(tmp_path, r, servico="despachante", rodada_id="r9")
    log.registrar("despachada", chamado_id="ch-1", ambulancia_id="amb-2")
    log.registrar("reserva_falhou", chamado_id="ch-1", ambulancia_id="amb-3")
    arquivo = tmp_path / "r9" / "despachante.jsonl"
    linhas = arquivo.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[1])["tipo"] == "reserva_falhou"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_eventlog.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/eventlog/__init__.py`**

```python
"""Event log append-only: fonte unica de verdade para metricas e dataset futuro."""
import json
import threading
import time
from pathlib import Path
from typing import Protocol

from samu_sim.core.relogio import Relogio


class EventLog(Protocol):
    def registrar(self, tipo: str, **campos) -> None: ...


class _Base:
    def __init__(self, relogio: Relogio, servico: str, rodada_id: str):
        self._relogio = relogio
        self._servico = servico
        self._rodada_id = rodada_id

    def _montar(self, tipo: str, campos: dict) -> dict:
        return {
            "ts_sim": self._relogio.agora_sim(),
            "ts_real": time.time(),
            "rodada_id": self._rodada_id,
            "servico": self._servico,
            "tipo": tipo,
            **campos,
        }


class EventLogMemoria(_Base):
    def __init__(self, relogio: Relogio, servico: str, rodada_id: str = "local"):
        super().__init__(relogio, servico, rodada_id)
        self.eventos: list[dict] = []
        self._lock = threading.Lock()

    def registrar(self, tipo: str, **campos) -> None:
        with self._lock:
            self.eventos.append(self._montar(tipo, campos))

    def contar(self, tipo: str) -> int:
        with self._lock:
            return sum(1 for e in self.eventos if e["tipo"] == tipo)


class EventLogJsonl(_Base):
    def __init__(self, diretorio: str | Path, relogio: Relogio, servico: str, rodada_id: str):
        super().__init__(relogio, servico, rodada_id)
        pasta = Path(diretorio) / rodada_id
        pasta.mkdir(parents=True, exist_ok=True)
        self._arquivo = open(pasta / f"{servico}.jsonl", "a", encoding="utf-8")
        self._lock = threading.Lock()

    def registrar(self, tipo: str, **campos) -> None:
        linha = json.dumps(self._montar(tipo, campos), ensure_ascii=False, default=str)
        with self._lock:
            self._arquivo.write(linha + "\n")
            self._arquivo.flush()

    def fechar(self) -> None:
        with self._lock:
            self._arquivo.close()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_eventlog.py -q`
Esperado: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/eventlog/__init__.py tests/test_eventlog.py
git commit -m "feat(eventlog): log de eventos em memoria e JSONL

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Dados seed e gerador de demanda

**Files:**
- Create: `dados/bairros.csv`, `dados/bases.csv`, `samu_sim/gerador/demanda.py`
- Test: `tests/test_demanda.py`

**Interfaces:**
- Consumes: `Chamado`, `deslocar`.
- Produces:
  - `@dataclass Bairro(nome: str, zona: str, lat: float, lon: float, populacao: int)`
  - `carregar_bairros(caminho: str | Path) -> list[Bairro]`
  - `carregar_bases(caminho: str | Path) -> list[Base]`
  - `PESOS_HORA: list[float]` (24 valores)
  - `GeradorChamados(bairros, seed: int, chamados_por_dia: int = 300, raio_km: float = 1.5)` com `gerar_dia(dia: int = 0) -> list[Chamado]` ordenada por `criado_em`; ids `ch-{dia:02d}-{n:05d}`.

- [ ] **Step 1: Criar `dados/bairros.csv`** (centróides e população aproximados — IBGE 2010; D3 substitui pelo Data.Rio)

```csv
bairro,zona,lat,lon,populacao
Centro,Centro,-22.9068,-43.1829,41142
Copacabana,Sul,-22.9711,-43.1822,146392
Botafogo,Sul,-22.9519,-43.1846,82890
Flamengo,Sul,-22.9330,-43.1760,50043
Tijuca,Norte,-22.9251,-43.2372,163805
Vila Isabel,Norte,-22.9150,-43.2500,86018
Meier,Norte,-22.9026,-43.2790,49828
Madureira,Norte,-22.8731,-43.3371,50106
Iraja,Norte,-22.8330,-43.3280,96382
Penha,Norte,-22.8394,-43.2790,78678
Ilha do Governador,Norte,-22.8060,-43.1900,105000
Barra da Tijuca,Barra,-23.0003,-43.3651,135924
Jacarepagua,Barra,-22.9530,-43.3840,157000
Recreio dos Bandeirantes,Barra,-23.0203,-43.4720,82240
Realengo,Oeste,-22.8790,-43.4340,180123
Bangu,Oeste,-22.8792,-43.4650,243125
Campo Grande,Oeste,-22.9036,-43.5590,328370
Santa Cruz,Oeste,-22.9186,-43.6845,217333
Guaratiba,Oeste,-23.0130,-43.5960,110049
```

- [ ] **Step 2: Criar `dados/bases.csv`** (hospitais de emergência / UPAs — coordenadas aproximadas)

```csv
id,nome,lat,lon
base-01,Hospital Souza Aguiar (Centro),-22.9083,-43.1868
base-02,Hospital Miguel Couto (Gavea),-22.9741,-43.2298
base-03,Hospital Salgado Filho (Meier),-22.9012,-43.2820
base-04,Hospital Getulio Vargas (Penha),-22.8420,-43.2770
base-05,UPA Madureira,-22.8730,-43.3380
base-06,Hospital Evandro Freire (Ilha),-22.8060,-43.1900
base-07,Hospital Lourenco Jorge (Barra),-22.9987,-43.3651
base-08,Hospital Albert Schweitzer (Realengo),-22.8794,-43.4348
base-09,Hospital Rocha Faria (Campo Grande),-22.9040,-43.5610
base-10,Hospital Pedro II (Santa Cruz),-22.9195,-43.6862
```

- [ ] **Step 3: Escrever o teste**

```python
from collections import Counter
from samu_sim.core.geo import haversine_km
from samu_sim.gerador.demanda import carregar_bairros, carregar_bases, GeradorChamados, PESOS_HORA


def test_carrega_csvs():
    bairros = carregar_bairros("dados/bairros.csv")
    bases = carregar_bases("dados/bases.csv")
    assert len(bairros) == 19 and len(bases) == 10
    assert {b.zona for b in bairros} == {"Centro", "Sul", "Norte", "Oeste", "Barra"}
    assert bases[0].id == "base-01"


def test_pesos_hora_tem_24_valores_com_picos():
    assert len(PESOS_HORA) == 24
    assert PESOS_HORA[9] > PESOS_HORA[3] and PESOS_HORA[19] > PESOS_HORA[14]


def test_gerar_dia_e_deterministico_e_ordenado():
    bairros = carregar_bairros("dados/bairros.csv")
    g1 = GeradorChamados(bairros, seed=42, chamados_por_dia=100).gerar_dia()
    g2 = GeradorChamados(bairros, seed=42, chamados_por_dia=100).gerar_dia()
    assert [c.id for c in g1] == [c.id for c in g2]
    assert [(c.lat, c.criado_em) for c in g1] == [(c.lat, c.criado_em) for c in g2]
    assert len(g1) == 100
    assert all(0 <= c.criado_em < 86400 for c in g1)
    assert [c.criado_em for c in g1] == sorted(c.criado_em for c in g1)


def test_chamados_ficam_perto_do_centroide_e_seguem_populacao():
    bairros = carregar_bairros("dados/bairros.csv")
    por_nome = {b.nome: b for b in bairros}
    chamados = GeradorChamados(bairros, seed=1, chamados_por_dia=3000, raio_km=1.5).gerar_dia()
    for c in chamados[:200]:
        b = por_nome[c.bairro]
        assert haversine_km(b.lat, b.lon, c.lat, c.lon) <= 1.5 + 1e-6
        assert c.zona == b.zona
    contagem = Counter(c.bairro for c in chamados)
    assert contagem["Campo Grande"] > contagem["Centro"]  # 328k vs 41k habitantes


def test_dias_diferentes_ids_diferentes():
    bairros = carregar_bairros("dados/bairros.csv")
    g = GeradorChamados(bairros, seed=1, chamados_por_dia=10)
    assert g.gerar_dia(0)[0].id == "ch-00-00000"
    assert g.gerar_dia(1)[0].id == "ch-01-00000"
    assert g.gerar_dia(1)[0].criado_em >= 86400
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_demanda.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 5: Implementar `samu_sim/gerador/demanda.py`**

```python
"""Geracao sintetica de demanda: bairro proporcional a populacao, hora com picos."""
import csv
import random
from dataclasses import dataclass
from pathlib import Path

from samu_sim.core.geo import deslocar
from samu_sim.core.modelos import Base, Chamado

SEGUNDOS_DIA = 86400

# Peso relativo de cada hora do dia (picos 8-11h e 18-21h, vale de madrugada).
PESOS_HORA: list[float] = [
    0.4, 0.3, 0.3, 0.3, 0.4, 0.6,   # 0-5h
    0.8, 1.2, 2.0, 2.0, 2.0, 2.0,   # 6-11h
    1.4, 1.2, 1.2, 1.2, 1.3, 1.6,   # 12-17h
    2.0, 2.0, 2.0, 2.0, 1.2, 0.7,   # 18-23h
]


@dataclass
class Bairro:
    nome: str
    zona: str
    lat: float
    lon: float
    populacao: int


def carregar_bairros(caminho: str | Path) -> list[Bairro]:
    with open(caminho, encoding="utf-8", newline="") as f:
        return [Bairro(r["bairro"], r["zona"], float(r["lat"]), float(r["lon"]), int(r["populacao"]))
                for r in csv.DictReader(f)]


def carregar_bases(caminho: str | Path) -> list[Base]:
    with open(caminho, encoding="utf-8", newline="") as f:
        return [Base(r["id"], r["nome"], float(r["lat"]), float(r["lon"]))
                for r in csv.DictReader(f)]


class GeradorChamados:
    def __init__(self, bairros: list[Bairro], seed: int,
                 chamados_por_dia: int = 300, raio_km: float = 1.5):
        self._bairros = bairros
        self._pesos_bairro = [b.populacao for b in bairros]
        self._seed = seed
        self._n = chamados_por_dia
        self._raio = raio_km

    def gerar_dia(self, dia: int = 0) -> list[Chamado]:
        rng = random.Random(f"{self._seed}-{dia}")
        chamados: list[Chamado] = []
        for _ in range(self._n):
            b = rng.choices(self._bairros, weights=self._pesos_bairro, k=1)[0]
            hora = rng.choices(range(24), weights=PESOS_HORA, k=1)[0]
            ts = dia * SEGUNDOS_DIA + hora * 3600 + rng.uniform(0, 3600)
            lat, lon = deslocar(b.lat, b.lon, rng.uniform(0, self._raio), rng.uniform(0, 360))
            chamados.append(Chamado(id="", lat=lat, lon=lon, bairro=b.nome, zona=b.zona, criado_em=ts))
        chamados.sort(key=lambda c: c.criado_em)
        for n, c in enumerate(chamados):
            c.id = f"ch-{dia:02d}-{n:05d}"
        return chamados
```

- [ ] **Step 6: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_demanda.py -q`
Esperado: `5 passed`.

- [ ] **Step 7: Commit**

```bash
git add dados/ samu_sim/gerador/demanda.py tests/test_demanda.py
git commit -m "feat(gerador): dados seed do Rio e gerador de demanda deterministico

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Serviço gerador

**Files:**
- Create: `samu_sim/gerador/servico.py`
- Test: `tests/test_gerador_servico.py`

**Interfaces:**
- Consumes: `GeradorChamados.gerar_dia`, `Fila.publicar`, `Repositorio.salvar_chamado`, `Relogio`, `EventLog`.
- Produces: `ServicoGerador(chamados: list[Chamado], fila: Fila, repo: Repositorio, relogio: Relogio, eventlog: EventLog)` com `executar(parar: threading.Event) -> int` (publica cada chamado quando `agora_sim >= criado_em`, salva no repo antes de publicar, registra `chamado_criado`; retorna quantos publicou; para quando `parar` for setado ou a lista acabar). Corpo da mensagem: `{"chamado_id", "lat", "lon", "bairro", "zona", "criado_em"}`.

- [ ] **Step 1: Escrever o teste**

```python
import threading
from samu_sim.core.modelos import Chamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.gerador.servico import ServicoGerador
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria


def ch(n, ts):
    return Chamado(id=f"ch-{n}", lat=-22.9, lon=-43.2, bairro="Centro", zona="Centro", criado_em=ts)


def test_publica_na_ordem_e_salva_no_repo():
    relogio = Relogio(fator=100000)  # 1 s real = ~28 h sim
    fila, repo = FilaMemoria(), RepositorioMemoria()
    log = EventLogMemoria(relogio, "gerador")
    svc = ServicoGerador([ch(1, 10), ch(2, 20), ch(3, 30)], fila, repo, relogio, log)
    n = svc.executar(threading.Event())
    assert n == 3
    msgs = fila.receber()
    assert [m.corpo["chamado_id"] for m in msgs] == ["ch-1", "ch-2", "ch-3"]
    assert msgs[0].corpo["criado_em"] == 10
    assert repo.obter_chamado("ch-2") is not None
    assert log.contar("chamado_criado") == 3


def test_para_quando_evento_setado():
    relogio = Relogio(fator=1)
    fila, repo = FilaMemoria(), RepositorioMemoria()
    parar = threading.Event()
    svc = ServicoGerador([ch(1, 0), ch(2, 3600)], fila, repo, relogio, EventLogMemoria(relogio, "g"))
    t = threading.Thread(target=lambda: svc.executar(parar))
    t.start()
    parar.set()
    t.join(timeout=2)
    assert not t.is_alive()
    assert fila.tamanho() == 1  # so o primeiro (criado_em=0) saiu
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_gerador_servico.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/gerador/servico.py`**

```python
"""Servico gerador: publica os chamados de um dia no ritmo do relogio simulado."""
import threading

from samu_sim.core.modelos import Chamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio

ESPERA_MAX_SIM = 60.0  # dorme no maximo isso por vez para conseguir checar `parar`


class ServicoGerador:
    def __init__(self, chamados: list[Chamado], fila: Fila, repo: Repositorio,
                 relogio: Relogio, eventlog: EventLog):
        self._chamados = chamados
        self._fila = fila
        self._repo = repo
        self._relogio = relogio
        self._log = eventlog

    def executar(self, parar: threading.Event) -> int:
        publicados = 0
        for c in self._chamados:
            while not parar.is_set() and self._relogio.agora_sim() < c.criado_em:
                self._relogio.dormir_sim(min(ESPERA_MAX_SIM, c.criado_em - self._relogio.agora_sim()))
            if parar.is_set():
                break
            self._repo.salvar_chamado(c)
            self._fila.publicar({
                "chamado_id": c.id, "lat": c.lat, "lon": c.lon,
                "bairro": c.bairro, "zona": c.zona, "criado_em": c.criado_em,
            })
            self._log.registrar("chamado_criado", chamado_id=c.id, bairro=c.bairro, zona=c.zona)
            publicados += 1
        return publicados
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_gerador_servico.py -q`
Esperado: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/gerador/servico.py tests/test_gerador_servico.py
git commit -m "feat(gerador): servico que publica chamados no ritmo do relogio

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Despachante

**Files:**
- Create: `samu_sim/despachante/servico.py`
- Test: `tests/test_despachante.py`

**Interfaces:**
- Consumes: `Fila.receber/ack/publicar`, `Repositorio.listar_ambulancias/reservar_ambulancia/obter_chamado/salvar_chamado`, `ConflitoVersao`, `Politica.escolher`, `Roteador.eta`, `Relogio.agora_sim`, `EventLog.registrar`.
- Produces: `Despachante(fila_chamados: Fila, filas_eventos: dict[str, Fila], repo, politica, roteador, relogio, eventlog, cache_seg: float = 2.0)` com:
  - `processar_lote() -> int` — recebe até 10 mensagens e chama `processar(msg)` em cada; retorna quantas deu ack.
  - `processar(msg: Mensagem) -> bool` — `True` se deu ack.
  - Mensagem publicada em `filas_eventos[ambulancia.worker_id]`: `{"tipo": "despachada", "chamado_id", "ambulancia_id", "eta_seg", "ts_sim"}`.
  - Eventos: `despacho_tentado`, `reserva_falhou`, `despachada`, `sem_ambulancia`, `chamado_ja_despachado`.

- [ ] **Step 1: Escrever o teste**

```python
import threading
from samu_sim.core.modelos import Ambulancia, Chamado, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.core.relogio import Relogio
from samu_sim.despachante.servico import Despachante
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria
from samu_sim.politicas import MaisProxima
from samu_sim.roteador import RoteadorHaversine


def montar(n_amb=2):
    relogio = Relogio(fator=1)
    repo = RepositorioMemoria()
    for i in range(n_amb):
        repo.salvar_ambulancia(Ambulancia(id=f"amb-{i}", base_id="b", lat=-22.90 - i * 0.05,
                                          lon=-43.20, worker_id=f"w{i % 2}"))
    fila = FilaMemoria(visibilidade_seg=0.01)
    filas_ev = {"w0": FilaMemoria(), "w1": FilaMemoria()}
    log = EventLogMemoria(relogio, "despachante")
    d = Despachante(fila, filas_ev, repo, MaisProxima(), RoteadorHaversine(), relogio, log, cache_seg=0)
    return relogio, repo, fila, filas_ev, log, d


def publicar_chamado(fila, repo, id="ch-1", lat=-22.90, lon=-43.20):
    c = Chamado(id=id, lat=lat, lon=lon, bairro="Centro", zona="Centro", criado_em=0)
    repo.salvar_chamado(c)
    fila.publicar({"chamado_id": id, "lat": lat, "lon": lon, "bairro": "Centro", "zona": "Centro", "criado_em": 0})


def test_despacha_a_mais_proxima_e_publica_no_worker_dono():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    assert d.processar_lote() == 1
    a = repo.obter_ambulancia("amb-0")           # a mais proxima
    assert a.status == SA.RESERVADA and a.chamado_id == "ch-1"
    c = repo.obter_chamado("ch-1")
    assert c.status == SC.DESPACHADO and c.ambulancia_id == "amb-0" and c.despachado_em is not None
    ev = filas_ev["w0"].receber()[0].corpo
    assert ev["tipo"] == "despachada" and ev["ambulancia_id"] == "amb-0" and ev["eta_seg"] >= 0
    assert filas_ev["w1"].tamanho() == 0
    assert fila.tamanho() == 0                   # ack dado
    assert log.contar("despachada") == 1


def test_sem_ambulancia_nao_da_ack():
    relogio, repo, fila, filas_ev, log, d = montar(n_amb=0)
    publicar_chamado(fila, repo)
    assert d.processar_lote() == 0
    assert fila.tamanho() == 1
    assert log.contar("sem_ambulancia") == 1


def test_mensagem_duplicada_e_idempotente():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    d.processar_lote()
    publicar_chamado(fila, repo)  # "duplicata": mesmo chamado_id, chamado ja despachado no repo
    # repo ja tem ch-1 despachado; o segundo salvar_chamado acima sobrescreveria -> simular
    # a duplicata de verdade: republicar so a mensagem
    repo.salvar_chamado(repo.obter_chamado("ch-1"))
    assert d.processar_lote() == 1
    assert repo.obter_ambulancia("amb-1").status == SA.DISPONIVEL  # nao despachou de novo
    assert log.contar("chamado_ja_despachado") >= 1


def test_perde_a_corrida_e_tenta_a_proxima():
    relogio, repo, fila, filas_ev, log, d = montar()
    publicar_chamado(fila, repo)
    # outro despachante reservou a amb-0 no meio do caminho
    repo.reservar_ambulancia("amb-0", 0, "ch-outro")
    # o cache ja foi lido? cache_seg=0, entao o despachante le disponiveis agora e ve so amb-1.
    # Para forcar o conflito, injetamos um listar_ambulancias que devolve amb-0 como disponivel:
    original = repo.listar_ambulancias
    def listar_desatualizado(status=None):
        lista = original(status)
        a0 = repo.obter_ambulancia("amb-0"); a0.status = SA.DISPONIVEL; a0.versao = 0
        return [a0] + [a for a in lista if a.id != "amb-0"]
    repo.listar_ambulancias = listar_desatualizado
    assert d.processar_lote() == 1
    assert repo.obter_chamado("ch-1").ambulancia_id == "amb-1"
    assert log.contar("reserva_falhou") == 1


def test_dois_despachantes_concorrentes_nunca_duplicam():
    relogio, repo, fila, filas_ev, log, d1 = montar(n_amb=1)
    d2 = Despachante(fila, filas_ev, repo, MaisProxima(), RoteadorHaversine(), relogio, log, cache_seg=0)
    for i in range(10):
        publicar_chamado(fila, repo, id=f"ch-{i}")
    b = threading.Barrier(2)
    def roda(d):
        b.wait()
        for _ in range(20):
            d.processar_lote()
    ts = [threading.Thread(target=roda, args=(d,)) for d in (d1, d2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    despachados = [c for c in repo.listar_chamados() if c.status == SC.DESPACHADO]
    assert len(despachados) == 1                       # so 1 ambulancia
    assert filas_ev["w0"].tamanho() == 1               # 1 evento despachada, nao 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_despachante.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/despachante/servico.py`**

```python
"""Despachante: consome chamados, aplica a politica e reserva a ambulancia
com lock otimista. Idempotente por chamado (mensagens duplicadas sao ignoradas)."""
import time

from samu_sim.core.modelos import Ambulancia, StatusAmbulancia, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila, Mensagem
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio
from samu_sim.politicas import Politica
from samu_sim.roteador import Roteador


class Despachante:
    def __init__(self, fila_chamados: Fila, filas_eventos: dict[str, Fila], repo: Repositorio,
                 politica: Politica, roteador: Roteador, relogio: Relogio, eventlog: EventLog,
                 cache_seg: float = 2.0):
        self._fila = fila_chamados
        self._filas_eventos = filas_eventos
        self._repo = repo
        self._politica = politica
        self._roteador = roteador
        self._relogio = relogio
        self._log = eventlog
        self._cache_seg = cache_seg
        self._cache: tuple[float, list[Ambulancia]] | None = None

    def processar_lote(self) -> int:
        return sum(1 for msg in self._fila.receber() if self.processar(msg))

    def processar(self, msg: Mensagem) -> bool:
        chamado_id = msg.corpo["chamado_id"]
        chamado = self._repo.obter_chamado(chamado_id)
        if chamado is None:
            # gerador salva antes de publicar; se nao existe, mensagem invalida -> descarta
            self._log.registrar("chamado_desconhecido", chamado_id=chamado_id)
            self._fila.ack(msg)
            return True
        if chamado.status != StatusChamado.PENDENTE:
            self._log.registrar("chamado_ja_despachado", chamado_id=chamado_id)
            self._fila.ack(msg)
            return True

        destino = (chamado.lat, chamado.lon)
        candidatas = self._politica.escolher(chamado, self._disponiveis(), self._roteador)
        self._log.registrar("despacho_tentado", chamado_id=chamado_id, candidatas=len(candidatas))
        for amb in candidatas:
            try:
                reservada = self._repo.reservar_ambulancia(amb.id, amb.versao, chamado_id)
            except ConflitoVersao:
                self._log.registrar("reserva_falhou", chamado_id=chamado_id, ambulancia_id=amb.id)
                self._invalidar_cache()
                continue
            eta = self._roteador.eta((reservada.lat, reservada.lon), destino)
            agora = self._relogio.agora_sim()
            chamado.status = StatusChamado.DESPACHADO
            chamado.ambulancia_id = reservada.id
            chamado.despachado_em = agora
            self._repo.salvar_chamado(chamado)
            self._filas_eventos[reservada.worker_id].publicar({
                "tipo": "despachada", "chamado_id": chamado_id,
                "ambulancia_id": reservada.id, "eta_seg": eta, "ts_sim": agora,
            })
            self._log.registrar("despachada", chamado_id=chamado_id, ambulancia_id=reservada.id,
                                eta_seg=eta, espera_seg=agora - chamado.criado_em)
            self._invalidar_cache()
            self._fila.ack(msg)
            return True

        # nenhuma candidata reservavel: nao da ack; a fila reentrega apos o visibility timeout
        self._log.registrar("sem_ambulancia", chamado_id=chamado_id)
        return False

    def _disponiveis(self) -> list[Ambulancia]:
        agora = time.monotonic()
        if self._cache and agora - self._cache[0] < self._cache_seg:
            return self._cache[1]
        lista = self._repo.listar_ambulancias(StatusAmbulancia.DISPONIVEL)
        self._cache = (agora, lista)
        return lista

    def _invalidar_cache(self) -> None:
        self._cache = None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_despachante.py -q`
Esperado: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/despachante/servico.py tests/test_despachante.py
git commit -m "feat(despachante): despacho com politica, lock otimista e idempotencia

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Worker de ambulância

**Files:**
- Create: `samu_sim/ambulancia/servico.py`
- Test: `tests/test_ambulancia.py`

**Interfaces:**
- Consumes: `Fila`, `Repositorio.obter_ambulancia/transicionar/obter_chamado/salvar_chamado`, `ConflitoVersao`, `Relogio.dormir_sim/agora_sim`, `Roteador.eta`, `Base`, `EventLog`.
- Produces: `WorkerAmbulancia(worker_id: str, fila_eventos: Fila, repo, relogio, roteador, bases: dict[str, Base], eventlog, atendimento_seg: tuple[float, float] = (600, 1200), max_simultaneas: int = 50, seed: int = 0)` com:
  - `processar_lote() -> int` — recebe mensagens; para cada: transiciona `RESERVADA → A_CAMINHO` (conflito → evento `transicao_rejeitada`, ack); ack; submete `_ciclo` a um `ThreadPoolExecutor`.
  - `_ciclo(ambulancia_id, chamado_id, eta_seg)`: `dormir_sim(eta)` → `A_CAMINHO → NO_LOCAL` (lat/lon do chamado; `chamado.chegada_em`) → `dormir_sim(atendimento)` → `chamado.liberado_em`, `status=ATENDIDO` → `NO_LOCAL → RETORNANDO` → `dormir_sim(eta até a base)` → `RETORNANDO → DISPONIVEL` (lat/lon da base, `chamado_id=None`). Cada transição lê a versão atual do repo.
  - `aguardar_ciclos(timeout: float | None = None)` — espera os ciclos em voo terminarem (usado em testes e no desligamento).
  - Eventos: `chegou` (com `resposta_seg = chegada_em - criado_em`), `liberada`, `transicao_rejeitada`.

- [ ] **Step 1: Escrever o teste**

```python
from samu_sim.ambulancia.servico import WorkerAmbulancia
from samu_sim.core.modelos import Ambulancia, Base, Chamado, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria
from samu_sim.roteador import RoteadorHaversine

BASE = Base("b1", "Base 1", -22.90, -43.20)


def montar():
    relogio = Relogio(fator=100000)
    repo = RepositorioMemoria()
    repo.salvar_ambulancia(Ambulancia(id="amb-1", base_id="b1", lat=BASE.lat, lon=BASE.lon, worker_id="w1"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=-22.95, lon=-43.25, bairro="X", zona="Sul", criado_em=0))
    fila = FilaMemoria()
    log = EventLogMemoria(relogio, "ambulancia")
    w = WorkerAmbulancia("w1", fila, repo, relogio, RoteadorHaversine(), {"b1": BASE}, log,
                         atendimento_seg=(600, 600))
    return relogio, repo, fila, log, w


def despachar(repo, fila, eta=300.0):
    a = repo.reservar_ambulancia("amb-1", 0, "ch-1")
    c = repo.obter_chamado("ch-1"); c.status = SC.DESPACHADO; c.ambulancia_id = "amb-1"; c.despachado_em = 5.0
    repo.salvar_chamado(c)
    fila.publicar({"tipo": "despachada", "chamado_id": "ch-1", "ambulancia_id": "amb-1", "eta_seg": eta, "ts_sim": 5.0})
    return a


def test_ciclo_completo_volta_disponivel_na_base():
    relogio, repo, fila, log, w = montar()
    despachar(repo, fila)
    assert w.processar_lote() == 1
    w.aguardar_ciclos(timeout=5)
    a = repo.obter_ambulancia("amb-1")
    assert a.status == SA.DISPONIVEL and a.chamado_id is None
    assert (a.lat, a.lon) == (BASE.lat, BASE.lon)
    c = repo.obter_chamado("ch-1")
    assert c.status == SC.ATENDIDO
    assert c.chegada_em is not None and c.liberado_em is not None and c.liberado_em > c.chegada_em
    assert log.contar("chegou") == 1 and log.contar("liberada") == 1
    assert fila.tamanho() == 0


def test_mensagem_duplicada_e_rejeitada_pela_maquina_de_estados():
    relogio, repo, fila, log, w = montar()
    despachar(repo, fila)
    fila.publicar({"tipo": "despachada", "chamado_id": "ch-1", "ambulancia_id": "amb-1", "eta_seg": 300.0, "ts_sim": 5.0})
    assert w.processar_lote() == 2
    w.aguardar_ciclos(timeout=5)
    assert log.contar("transicao_rejeitada") == 1
    assert log.contar("chegou") == 1
    assert fila.tamanho() == 0


def test_tempo_de_resposta_registrado():
    relogio, repo, fila, log, w = montar()
    despachar(repo, fila, eta=300.0)
    w.processar_lote()
    w.aguardar_ciclos(timeout=5)
    chegou = next(e for e in log.eventos if e["tipo"] == "chegou")
    assert chegou["resposta_seg"] >= 300.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_ambulancia.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/ambulancia/servico.py`**

```python
"""Worker de ambulancias: consome eventos 'despachada' das suas ambulancias e
simula o ciclo a_caminho -> no_local -> retornando -> disponivel. Cada transicao
e condicional em (status, versao); duplicatas/atrasos sao rejeitados."""
import random
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait

from samu_sim.core.modelos import Base, StatusAmbulancia as SA, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio
from samu_sim.roteador import Roteador


class WorkerAmbulancia:
    def __init__(self, worker_id: str, fila_eventos: Fila, repo: Repositorio, relogio: Relogio,
                 roteador: Roteador, bases: dict[str, Base], eventlog: EventLog,
                 atendimento_seg: tuple[float, float] = (600, 1200),
                 max_simultaneas: int = 50, seed: int = 0):
        self.worker_id = worker_id
        self._fila = fila_eventos
        self._repo = repo
        self._relogio = relogio
        self._roteador = roteador
        self._bases = bases
        self._log = eventlog
        self._atendimento = atendimento_seg
        self._rng = random.Random(f"{seed}-{worker_id}")
        self._pool = ThreadPoolExecutor(max_workers=max_simultaneas, thread_name_prefix=worker_id)
        self._em_voo: set[Future] = set()
        self._lock = threading.Lock()

    def processar_lote(self) -> int:
        n = 0
        for msg in self._fila.receber():
            corpo = msg.corpo
            amb_id, ch_id, eta = corpo["ambulancia_id"], corpo["chamado_id"], float(corpo["eta_seg"])
            a = self._repo.obter_ambulancia(amb_id)
            try:
                if a is None:
                    raise ConflitoVersao("ambulancia inexistente")
                self._repo.transicionar(amb_id, SA.RESERVADA, SA.A_CAMINHO, a.versao,
                                        heartbeat_em=self._relogio.agora_sim())
            except ConflitoVersao as e:
                self._log.registrar("transicao_rejeitada", ambulancia_id=amb_id, chamado_id=ch_id,
                                    de="reservada", para="a_caminho", motivo=str(e))
                self._fila.ack(msg)
                n += 1
                continue
            self._fila.ack(msg)
            n += 1
            fut = self._pool.submit(self._ciclo, amb_id, ch_id, eta)
            with self._lock:
                self._em_voo.add(fut)
            fut.add_done_callback(self._concluido)
        return n

    def aguardar_ciclos(self, timeout: float | None = None) -> None:
        with self._lock:
            pendentes = set(self._em_voo)
        wait(pendentes, timeout=timeout)

    def encerrar(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _concluido(self, fut: Future) -> None:
        with self._lock:
            self._em_voo.discard(fut)
        exc = fut.exception()
        if exc:
            self._log.registrar("erro_ciclo", worker_id=self.worker_id, erro=repr(exc))

    def _transicionar(self, amb_id: str, de: SA, para: SA, **campos):
        a = self._repo.obter_ambulancia(amb_id)
        return self._repo.transicionar(amb_id, de, para, a.versao,
                                       heartbeat_em=self._relogio.agora_sim(), **campos)

    def _ciclo(self, amb_id: str, ch_id: str, eta: float) -> None:
        chamado = self._repo.obter_chamado(ch_id)
        self._relogio.dormir_sim(eta)

        agora = self._relogio.agora_sim()
        self._transicionar(amb_id, SA.A_CAMINHO, SA.NO_LOCAL, lat=chamado.lat, lon=chamado.lon)
        chamado.chegada_em = agora
        self._repo.salvar_chamado(chamado)
        self._log.registrar("chegou", ambulancia_id=amb_id, chamado_id=ch_id, zona=chamado.zona,
                            resposta_seg=agora - chamado.criado_em)

        self._relogio.dormir_sim(self._rng.uniform(*self._atendimento))

        agora = self._relogio.agora_sim()
        chamado.liberado_em = agora
        chamado.status = StatusChamado.ATENDIDO
        self._repo.salvar_chamado(chamado)
        a = self._transicionar(amb_id, SA.NO_LOCAL, SA.RETORNANDO)
        self._log.registrar("liberada", ambulancia_id=amb_id, chamado_id=ch_id)

        base = self._bases[a.base_id]
        self._relogio.dormir_sim(self._roteador.eta((a.lat, a.lon), (base.lat, base.lon)))
        self._transicionar(amb_id, SA.RETORNANDO, SA.DISPONIVEL,
                           lat=base.lat, lon=base.lon, chamado_id=None)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_ambulancia.py -q`
Esperado: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/ambulancia/servico.py tests/test_ambulancia.py
git commit -m "feat(ambulancia): worker com maquina de estados e ciclo simulado

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: Métricas

**Files:**
- Create: `samu_sim/core/metricas.py`
- Test: `tests/test_metricas.py`

**Interfaces:**
- Consumes: `Chamado`.
- Produces:
  - `percentil(valores: list[float], p: float) -> float | None` (interpolação linear; `None` se vazio)
  - `calcular(chamados: list[Chamado]) -> dict` com chaves: `total`, `atendidos`, `despachados`, `pendentes`, `resposta` = `{"p50", "p90", "media", "n"}` (sobre `chegada_em - criado_em` dos que chegaram), `por_zona` = `{zona: {"p50", "p90", "n"}}`, `espera_despacho` = `{"p50", "p90"}` (sobre `despachado_em - criado_em`).

- [ ] **Step 1: Escrever o teste**

```python
import pytest
from samu_sim.core.metricas import calcular, percentil
from samu_sim.core.modelos import Chamado, StatusChamado as SC


def ch(i, zona, criado, chegada=None, despachado=None):
    c = Chamado(id=f"ch-{i}", lat=0, lon=0, bairro="B", zona=zona, criado_em=criado)
    if despachado is not None:
        c.despachado_em = despachado; c.status = SC.DESPACHADO
    if chegada is not None:
        c.chegada_em = chegada; c.status = SC.ATENDIDO
    return c


def test_percentil():
    assert percentil([], 50) is None
    assert percentil([10], 90) == 10
    assert percentil([1, 2, 3, 4, 5], 50) == 3
    assert percentil([1, 2, 3, 4, 5], 90) == pytest.approx(4.6)


def test_calcular():
    chamados = [
        ch(1, "Sul", 0, chegada=300, despachado=10),
        ch(2, "Sul", 0, chegada=600, despachado=20),
        ch(3, "Oeste", 0, chegada=1500, despachado=30),
        ch(4, "Oeste", 0, despachado=40),   # despachado, ainda nao chegou
        ch(5, "Norte", 0),                  # pendente
    ]
    m = calcular(chamados)
    assert m["total"] == 5 and m["atendidos"] == 3 and m["despachados"] == 1 and m["pendentes"] == 1
    assert m["resposta"]["n"] == 3 and m["resposta"]["p50"] == 600
    assert m["resposta"]["media"] == pytest.approx(800)
    assert m["por_zona"]["Sul"]["p50"] == 450 and m["por_zona"]["Oeste"]["n"] == 1
    assert m["espera_despacho"]["p50"] == 25
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_metricas.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/core/metricas.py`**

```python
"""Metricas de tempo de resposta calculadas a partir dos chamados."""
from collections import defaultdict

from samu_sim.core.modelos import Chamado, StatusChamado


def percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * p / 100.0
    i = int(pos)
    frac = pos - i
    if i + 1 >= len(v):
        return v[-1]
    return v[i] + (v[i + 1] - v[i]) * frac


def _resumo(valores: list[float]) -> dict:
    return {"p50": percentil(valores, 50), "p90": percentil(valores, 90),
            "media": (sum(valores) / len(valores)) if valores else None, "n": len(valores)}


def calcular(chamados: list[Chamado]) -> dict:
    respostas: list[float] = []
    por_zona: dict[str, list[float]] = defaultdict(list)
    esperas: list[float] = []
    for c in chamados:
        if c.despachado_em is not None:
            esperas.append(c.despachado_em - c.criado_em)
        if c.chegada_em is not None:
            r = c.chegada_em - c.criado_em
            respostas.append(r)
            por_zona[c.zona].append(r)
    return {
        "total": len(chamados),
        "atendidos": sum(1 for c in chamados if c.status == StatusChamado.ATENDIDO),
        "despachados": sum(1 for c in chamados if c.status == StatusChamado.DESPACHADO),
        "pendentes": sum(1 for c in chamados if c.status == StatusChamado.PENDENTE),
        "resposta": _resumo(respostas),
        "por_zona": {z: {k: v for k, v in _resumo(vs).items() if k != "media"}
                     for z, vs in sorted(por_zona.items())},
        "espera_despacho": {"p50": percentil(esperas, 50), "p90": percentil(esperas, 90)},
    }
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_metricas.py -q`
Esperado: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/core/metricas.py tests/test_metricas.py
git commit -m "feat(core): metricas P50/P90 por zona

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 15: Runner local em-processo + teste de integração

**Files:**
- Create: `samu_sim/local.py`
- Test: `tests/test_integracao_local.py`

**Interfaces:**
- Consumes: tudo acima.
- Produces:
  - `montar_frota(bases: list[Base], n_ambulancias: int, n_workers: int) -> list[Ambulancia]` — round-robin por base e por worker; ids `amb-{i:03d}`, workers `w{k}`.
  - `rodar(fator: float, duracao_sim_seg: float, n_ambulancias: int = 50, politica: str = "mais_proxima", roteador: str = "haversine", seed: int = 42, chamados_por_dia: int = 300, n_despachantes: int = 2, n_workers: int = 2, visibilidade_seg: float = 30.0, log_dir: str | None = None) -> dict` — monta tudo em memória, roda threads até `agora_sim >= duracao_sim_seg`, para, aguarda ciclos em voo por até 5 s reais, e retorna `{"metricas": calcular(...), "eventos": {tipo: contagem}, "rodada": {...}}`.
  - CLI: `python -m samu_sim.local --fator 20 --duracao-sim 3600 --ambulancias 50 --politica mais_proxima` imprime o JSON do resultado.

- [ ] **Step 1: Escrever o teste de integração**

```python
from samu_sim.local import rodar, montar_frota
from samu_sim.gerador.demanda import carregar_bases


def test_montar_frota_distribui_por_base_e_worker():
    bases = carregar_bases("dados/bases.csv")
    frota = montar_frota(bases, n_ambulancias=25, n_workers=2)
    assert len(frota) == 25
    assert frota[0].id == "amb-000" and frota[0].base_id == "base-01" and frota[0].worker_id == "w0"
    assert frota[1].base_id == "base-02" and frota[1].worker_id == "w1"
    assert frota[10].base_id == "base-01"
    assert sum(1 for a in frota if a.worker_id == "w0") == 13


def test_fluxo_completo_em_memoria():
    """gerador -> 2 despachantes -> 2 workers, 6 h simuladas em poucos segundos reais."""
    r = rodar(fator=20000, duracao_sim_seg=6 * 3600, n_ambulancias=30,
              chamados_por_dia=400, seed=7, visibilidade_seg=0.05)
    m = r["metricas"]
    assert m["total"] >= 30                       # chamados publicados nas primeiras 6 h
    assert m["atendidos"] >= 0.6 * m["total"]     # a maioria concluiu o ciclo
    assert m["resposta"]["p90"] is not None and m["resposta"]["p90"] > 0
    # nenhum chamado despachado duas vezes: 1 evento 'despachada' por chamado despachado
    assert r["eventos"].get("despachada", 0) == m["atendidos"] + m["despachados"]
    # nenhuma ambulancia em estado inconsistente: chamado atendido tem chegada e liberacao
    assert r["eventos"].get("erro_ciclo", 0) == 0
    assert "Oeste" in m["por_zona"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_integracao_local.py -q`
Esperado: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/local.py`**

```python
"""Runner local: monta gerador, despachantes e workers em memoria e roda em threads.
Uso: python -m samu_sim.local --fator 20 --duracao-sim 3600"""
import argparse
import json
import threading
import time
import uuid
from collections import Counter

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

    def novo_log(servico: str):
        if log_dir:
            return EventLogJsonl(log_dir, relogio, servico, rodada_id)
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

    eventos = Counter()
    for log in logs_mem:
        eventos.update(e["tipo"] for e in log.eventos)
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python -m pytest tests/test_integracao_local.py -q`
Esperado: `2 passed` (o segundo leva ~2–5 s).

Se `atendidos` ficar abaixo de 60 %: com 30 ambulâncias e 400 chamados/dia nas primeiras 6 h (~85 chamados, ciclo ~30–40 min sim cada) a frota dá conta; se falhar, verificar se os workers estão recebendo (`eventos["despachada"]` > 0) antes de mexer nos números.

- [ ] **Step 5: Rodar a suíte inteira e o CLI**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m samu_sim.local --fator 2000 --duracao-sim 3600 --ambulancias 40
```
Esperado: todos os testes passam; o CLI imprime JSON com `metricas.resposta.p90` numérico e `eventos.despachada > 0`.

- [ ] **Step 6: Commit**

```bash
git add samu_sim/local.py tests/test_integracao_local.py
git commit -m "feat: runner local em memoria com gerador, despachantes e workers

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 16: README mínimo do D1

**Files:**
- Create: `README.md`

- [ ] **Step 1: Escrever `README.md`**

```markdown
# samu-sim

Simulador distribuído de despacho de ambulâncias no Rio de Janeiro. Chamados sintéticos
(proporcionais à população por bairro) são despachados por N despachantes concorrentes que
disputam ambulâncias com lock otimista; workers simulam o deslocamento em tempo acelerado.

Spec: `docs/superpowers/specs/2026-09-18-samu-sim-design.md`.

## Rodar (D1 — tudo em memória)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m samu_sim.local --fator 20 --duracao-sim 3600 --ambulancias 50 --politica mais_proxima
```

`--fator` acelera o tempo (1 s real = `fator` s simulados). `--log-dir logs` grava o event log JSONL.

## Estado

- [x] D1: núcleo em memória (relógio, fila, repositório com lock otimista, políticas, serviços, métricas)
- [ ] D2: docker compose + LocalStack (SQS/DynamoDB), reaper, análise de rodada
- [ ] D3: OSRM + política `menor_eta` real + matriz pré-computada
- [ ] D4: Terraform + EC2 + mapa
- [ ] D5: experimentos A (políticas) e B (frota)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README do D1

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review (feito ao escrever)

- **Cobertura do spec (parte D1):** relógio com checkpoint (§5.3) → Task 4; `Fila`/`Repositorio` com implementação em memória (§3.2) → Tasks 5–6; `reservar_ambulancia`/`transicionar` condicionais (§4.1, §5.2) → Task 6; roteador haversine (§ADR 3) → Task 7; políticas `mais_proxima`/`menor_eta` (§11-A parcial; `menor_eta_cobertura` fica para D3 junto com OSRM) → Task 8; event log JSONL com campos comuns (§4.3) → Task 9; demanda ∝ população com curva horária e seed (§9) → Task 10; fluxo do chamado com idempotência e sem-ack quando não há ambulância (§5.1) → Task 12; máquina de estados com rejeição de duplicata e `heartbeat_em` atualizado a cada transição (§5.2) → Task 13; métricas P50/P90 por zona (§7) → Task 14; teste de concorrência e integração em-processo (§8) → Tasks 6, 12, 15. Heartbeat periódico e reaper ficam para D2 (dependem da `api`).
- **Placeholders:** nenhum; todo passo tem código.
- **Consistência de tipos:** `Fila.receber()->list[Mensagem]`, `ack(Mensagem)`; `Repositorio.transicionar(id, de, para, versao, **campos)`; `Politica.escolher(chamado, disponiveis, roteador)`; `Roteador.eta(Ponto, Ponto)`; `EventLog.registrar(tipo, **campos)`; `WorkerAmbulancia.processar_lote()/aguardar_ciclos()/encerrar()`; `Despachante.processar_lote()/processar(msg)` — usados com as mesmas assinaturas nas Tasks 11–15.

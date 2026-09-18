# samu-sim — Plano D2: SQS/DynamoDB (LocalStack), containers, reaper, análise

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Os 4 serviços (gerador, despachante ×2, ambulância ×2, api) rodando em containers separados sobre SQS + DynamoDB (LocalStack), com relógio sincronizado entre processos, heartbeat + reaper recuperando ambulâncias de workers mortos, e `scripts/analisar_rodada.py` produzindo métricas a partir do event log.

**Architecture:** Mantém as interfaces do D1 (`Fila`, `Repositorio`, `EventLog`) e adiciona as implementações `FilaSQS` e `RepositorioDynamo` (boto3). O estado da rodada (`fator`, checkpoint do relógio, `pausada`) vive na tabela `rodada`; cada serviço tem uma thread que a relê a cada 10 s e chama `Relogio.sincronizar(...)`. A `api` (FastAPI) expõe `/estado`, `/metricas`, `/controle` e roda o reaper. Um serviço one-shot `bootstrap` cria filas/tabelas e semeia frota + rodada. Todos escrevem event log JSONL num volume `./logs`.

**Tech Stack:** Python 3.12, boto3, FastAPI + uvicorn, httpx (TestClient), LocalStack 3 (SQS, DynamoDB), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-18-samu-sim-design.md`

## Global Constraints

- Tudo do plano D1 continua valendo (nomes em português, TDD, commits pequenos com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`).
- Suíte unitária roda sem Docker. Testes que exigem LocalStack são `@pytest.mark.integration` e fazem `pytest.skip` se `AWS_ENDPOINT_URL` não responder.
- `heartbeat_em` passa a ser **tempo real (epoch, `time.time()`)** — liveness de worker é um conceito do mundo real, não do simulado. Reaper usa `timeout_seg=120` reais.
- Relógio distribuído: `inicio_real` do checkpoint é `time.time()` (wall-clock), nunca `monotonic`, porque é compartilhado entre containers.
- Nomes de recursos AWS: fila `samu-chamados`, filas `samu-eventos-w{k}`, tabelas `samu-ambulancias`, `samu-chamados`, `samu-rodada`. Item único da rodada tem `id = "atual"`.
- Variáveis de ambiente (todas com default) em `samu_sim/core/config.py`; nenhum serviço lê `os.environ` diretamente fora dali.
- Rodar testes: `.venv/Scripts/python -m pytest -q` (unitários) e `.venv/Scripts/python -m pytest -q -m integration` (com LocalStack de pé).

---

## Estrutura de arquivos deste plano

```
samu_sim/core/config.py          Config (env -> dataclass)
samu_sim/core/relogio.py         + sincronizar(); fator 0 = pausado
samu_sim/core/modelos.py         (sem mudança de campos; heartbeat_em passa a ser epoch real)
samu_sim/core/runtime.py         montar_infra(cfg), SincronizadorRelogio, configurar_logging()
samu_sim/infra/repositorio.py    + atualizar_heartbeat, listar_ambulancias(worker_id=), liberar_ambulancia
samu_sim/infra/aws.py            FilaSQS, RepositorioDynamo, clientes boto3, (de|para)_item
samu_sim/infra/bootstrap.py      cria filas/tabelas, semeia frota e rodada; `python -m samu_sim.infra.bootstrap`
samu_sim/ambulancia/servico.py   + thread de heartbeat
samu_sim/ambulancia/__main__.py  entrypoint
samu_sim/gerador/__main__.py     entrypoint
samu_sim/despachante/__main__.py entrypoint
samu_sim/api/__init__.py         criar_app(...) FastAPI
samu_sim/api/reaper.py           Reaper
samu_sim/api/__main__.py         entrypoint (uvicorn + thread do reaper)
scripts/analisar_rodada.py       métricas a partir do event log JSONL
Dockerfile, docker-compose.yml
tests/test_config.py, tests/test_relogio.py (+), tests/test_repositorio.py (+),
tests/test_ambulancia.py (+), tests/test_reaper.py, tests/test_aws_serializacao.py,
tests/test_aws_integracao.py (@integration), tests/test_api.py, tests/test_analisar_rodada.py
```

---

### Task 1: Dependências e `Config`

**Files:**
- Modify: `pyproject.toml`
- Create: `samu_sim/core/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) Config` com campos e defaults:
  `aws_endpoint_url: str | None = None`, `aws_region: str = "us-east-1"`,
  `fila_chamados: str = "samu-chamados"`, `prefixo_fila_eventos: str = "samu-eventos-"`,
  `prefixo_tabela: str = "samu-"`, `n_workers: int = 2`, `worker_id: str = "w0"`,
  `fator: float = 20.0`, `politica: str = "mais_proxima"`, `roteador: str = "haversine"`,
  `seed: int = 42`, `n_ambulancias: int = 50`, `chamados_por_dia: int = 300`,
  `log_dir: str = "logs"`, `dados_dir: str = "dados"`, `rodada_id: str = "local"`,
  `heartbeat_seg: float = 30.0`, `reaper_timeout_seg: float = 120.0`, `reaper_intervalo_seg: float = 60.0`,
  `sync_relogio_seg: float = 10.0`, `api_porta: int = 8000`.
  Métodos: `Config.do_ambiente(env: Mapping[str, str] = os.environ) -> Config` (chaves = nome do campo em MAIÚSCULAS, ex.: `AWS_ENDPOINT_URL`, `N_WORKERS`), `fila_eventos(worker_id) -> str`, `tabela(nome) -> str`.

- [ ] **Step 1: Adicionar dependências em `pyproject.toml`**

Trocar `dependencies = []` por:
```toml
dependencies = [
    "boto3>=1.34",
    "fastapi>=0.110",
    "uvicorn>=0.29",
]
```
e `dev = ["pytest>=8"]` por `dev = ["pytest>=8", "httpx>=0.27"]`. Instalar: `.venv/Scripts/python -m pip install -e ".[dev]"`.

- [ ] **Step 2: Escrever `tests/test_config.py`**

```python
from samu_sim.core.config import Config


def test_defaults():
    c = Config.do_ambiente({})
    assert c.aws_endpoint_url is None and c.n_workers == 2 and c.fator == 20.0
    assert c.fila_eventos("w1") == "samu-eventos-w1"
    assert c.tabela("ambulancias") == "samu-ambulancias"


def test_le_do_ambiente_com_tipos():
    c = Config.do_ambiente({"AWS_ENDPOINT_URL": "http://localstack:4566", "N_WORKERS": "3",
                            "FATOR": "5", "WORKER_ID": "w2", "SEED": "9"})
    assert c.aws_endpoint_url == "http://localstack:4566"
    assert c.n_workers == 3 and c.fator == 5.0 and c.worker_id == "w2" and c.seed == 9
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -q` → FAIL `ModuleNotFoundError`.

- [ ] **Step 4: Implementar `samu_sim/core/config.py`**

```python
"""Configuracao por variaveis de ambiente. Unico lugar que le os.environ."""
import os
from dataclasses import dataclass, fields
from typing import Mapping


@dataclass(frozen=True)
class Config:
    aws_endpoint_url: str | None = None
    aws_region: str = "us-east-1"
    fila_chamados: str = "samu-chamados"
    prefixo_fila_eventos: str = "samu-eventos-"
    prefixo_tabela: str = "samu-"
    n_workers: int = 2
    worker_id: str = "w0"
    fator: float = 20.0
    politica: str = "mais_proxima"
    roteador: str = "haversine"
    seed: int = 42
    n_ambulancias: int = 50
    chamados_por_dia: int = 300
    log_dir: str = "logs"
    dados_dir: str = "dados"
    rodada_id: str = "local"
    heartbeat_seg: float = 30.0
    reaper_timeout_seg: float = 120.0
    reaper_intervalo_seg: float = 60.0
    sync_relogio_seg: float = 10.0
    api_porta: int = 8000

    @classmethod
    def do_ambiente(cls, env: Mapping[str, str] = os.environ) -> "Config":
        valores = {}
        for f in fields(cls):
            bruto = env.get(f.name.upper())
            if bruto is None or bruto == "":
                continue
            tipo = f.type if isinstance(f.type, type) else str
            if f.name == "aws_endpoint_url":
                valores[f.name] = bruto
            elif tipo is int:
                valores[f.name] = int(bruto)
            elif tipo is float:
                valores[f.name] = float(bruto)
            else:
                valores[f.name] = bruto
        return cls(**valores)

    def fila_eventos(self, worker_id: str) -> str:
        return f"{self.prefixo_fila_eventos}{worker_id}"

    def tabela(self, nome: str) -> str:
        return f"{self.prefixo_tabela}{nome}"
```

- [ ] **Step 5: Rodar e ver passar** → `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml samu_sim/core/config.py tests/test_config.py
git commit -m "feat(core): Config por variaveis de ambiente e dependencias do D2

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Relógio sincronizável e repositório com heartbeat/liberação

**Files:**
- Modify: `samu_sim/core/relogio.py`, `samu_sim/infra/repositorio.py`
- Test: `tests/test_relogio.py` (adicionar), `tests/test_repositorio.py` (adicionar)

**Interfaces:**
- Produces:
  - `Relogio.sincronizar(inicio_real: float, inicio_sim: float, fator: float) -> None` — substitui o checkpoint (usado pelos serviços ao reler a rodada). `Relogio.pausado -> bool` (`fator == 0`). Com `fator == 0`, `agora_sim()` congela e `dormir_sim` dorme `PEDACO_MAX_REAL` reais por iteração sem dividir por zero.
  - `Repositorio.listar_ambulancias(status=None, worker_id=None)`.
  - `Repositorio.atualizar_heartbeat(id: str, ts: float) -> None` — grava só `heartbeat_em`, **sem** mexer em `versao`.
  - `Repositorio.liberar_ambulancia(id: str, versao: int, lat: float, lon: float) -> Ambulancia` — condicional só em `versao`; grava `status=DISPONIVEL, chamado_id=None, lat, lon, versao+1` (usado pelo reaper; ignora `TRANSICOES_VALIDAS`).

- [ ] **Step 1: Adicionar testes em `tests/test_relogio.py`**

```python
def test_sincronizar_substitui_checkpoint():
    f = RelogioFake()
    r = Relogio(fator=1, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 10                       # sim = 10
    r.sincronizar(inicio_real=f.t - 2, inicio_sim=1000, fator=5)
    assert r.agora_sim() == pytest.approx(1010)   # 1000 + 2*5
    assert r.fator == 5


def test_fator_zero_pausa_sem_dividir_por_zero():
    f = RelogioFake()
    r = Relogio(fator=10, agora_real=f.agora, dormir_real=f.dormir)
    f.t += 1                        # sim = 10
    r.definir_fator(0)
    f.t += 100
    assert r.agora_sim() == pytest.approx(10) and r.pausado
    # dormir_sim nao trava para sempre: despausamos apos 3 pedacos
    n = {"i": 0}
    def dormir(s):
        f.dormir(s); n["i"] += 1
        if n["i"] == 3:
            r.definir_fator(10)
    r._dormir_real = dormir
    r.dormir_sim(20)
    assert r.agora_sim() == pytest.approx(30, abs=0.01)
```

- [ ] **Step 2: Adicionar testes em `tests/test_repositorio.py`**

```python
def test_listar_por_worker():
    r = RepositorioMemoria()
    a = amb("a"); a.worker_id = "w0"; r.salvar_ambulancia(a)
    b = amb("b"); b.worker_id = "w1"; r.salvar_ambulancia(b)
    assert [x.id for x in r.listar_ambulancias(worker_id="w1")] == ["b"]
    assert [x.id for x in r.listar_ambulancias(SA.DISPONIVEL, worker_id="w0")] == ["a"]


def test_atualizar_heartbeat_nao_mexe_na_versao():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    a = r.reservar_ambulancia("amb-1", 0, "ch-1")
    r.atualizar_heartbeat("amb-1", 1234.5)
    b = r.obter_ambulancia("amb-1")
    assert b.heartbeat_em == 1234.5 and b.versao == a.versao == 1
    # a transicao em voo continua valida com a versao antiga
    r.transicionar("amb-1", SA.RESERVADA, SA.A_CAMINHO, a.versao)


def test_liberar_ambulancia_forca_disponivel_de_qualquer_estado():
    r = RepositorioMemoria()
    r.salvar_ambulancia(amb())
    a = r.reservar_ambulancia("amb-1", 0, "ch-1")
    a = r.transicionar("amb-1", SA.RESERVADA, SA.A_CAMINHO, a.versao)
    b = r.liberar_ambulancia("amb-1", a.versao, lat=-1.0, lon=-2.0)
    assert b.status == SA.DISPONIVEL and b.chamado_id is None and (b.lat, b.lon) == (-1.0, -2.0)
    assert b.versao == a.versao + 1
    with pytest.raises(ConflitoVersao):
        r.liberar_ambulancia("amb-1", a.versao, lat=0, lon=0)
```

- [ ] **Step 3: Rodar e ver falhar** → `5 failed` (AttributeError/TypeError).

- [ ] **Step 4: Implementar em `samu_sim/core/relogio.py`**

Adicionar:
```python
    @property
    def pausado(self) -> bool:
        return self._fator == 0

    def sincronizar(self, inicio_real: float, inicio_sim: float, fator: float) -> None:
        with self._lock:
            self._inicio_real = float(inicio_real)
            self._inicio_sim = float(inicio_sim)
            self._fator = float(fator)
```
E trocar o corpo de `dormir_sim` por:
```python
    def dormir_sim(self, segundos: float) -> None:
        alvo = self.agora_sim() + segundos
        while True:
            resta_sim = alvo - self.agora_sim()
            if resta_sim <= 0:
                return
            fator = self._fator
            if fator <= 0:
                self._dormir_real(PEDACO_MAX_REAL)
                continue
            self._dormir_real(min(resta_sim / fator, PEDACO_MAX_REAL))
```

- [ ] **Step 5: Implementar em `samu_sim/infra/repositorio.py`**

No `Protocol`, trocar a assinatura de `listar_ambulancias` e adicionar dois métodos:
```python
    def listar_ambulancias(self, status: StatusAmbulancia | None = None,
                           worker_id: str | None = None) -> list[Ambulancia]: ...
    def atualizar_heartbeat(self, id: str, ts: float) -> None: ...
    def liberar_ambulancia(self, id: str, versao: int, lat: float, lon: float) -> Ambulancia: ...
```
Em `RepositorioMemoria`:
```python
    def listar_ambulancias(self, status: StatusAmbulancia | None = None,
                           worker_id: str | None = None) -> list[Ambulancia]:
        with self._lock:
            return [replace(a) for a in self._amb.values()
                    if (status is None or a.status == status)
                    and (worker_id is None or a.worker_id == worker_id)]

    def atualizar_heartbeat(self, id: str, ts: float) -> None:
        with self._lock:
            a = self._amb.get(id)
            if a is not None:
                self._amb[id] = replace(a, heartbeat_em=ts)

    def liberar_ambulancia(self, id: str, versao: int, lat: float, lon: float) -> Ambulancia:
        with self._lock:
            a = self._amb.get(id)
            if a is None or a.versao != versao:
                raise ConflitoVersao(f"{id}: esperado v{versao}, atual v{a.versao if a else None}")
            novo = replace(a, status=StatusAmbulancia.DISPONIVEL, chamado_id=None,
                           lat=lat, lon=lon, versao=versao + 1)
            self._amb[id] = novo
            return replace(novo)
```

- [ ] **Step 6: Rodar tudo** → `.venv/Scripts/python -m pytest -q` → todos passam (D1 + 5 novos).

- [ ] **Step 7: Commit**

```bash
git add samu_sim/core/relogio.py samu_sim/infra/repositorio.py tests/test_relogio.py tests/test_repositorio.py
git commit -m "feat: relogio sincronizavel/pausavel e repositorio com heartbeat e liberacao forcada

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Heartbeat no worker (tempo real)

**Files:**
- Modify: `samu_sim/ambulancia/servico.py`
- Test: `tests/test_ambulancia.py` (adicionar)

**Interfaces:**
- Produces: `WorkerAmbulancia(..., agora_real=time.time)` (novo kwarg); `bater_heartbeat() -> int` (atualiza `heartbeat_em = agora_real()` de todas as ambulâncias com `worker_id == self.worker_id` e `status != DISPONIVEL`; retorna quantas); `iniciar_heartbeat(intervalo_seg: float, parar: threading.Event) -> threading.Thread` (thread daemon que chama `bater_heartbeat` a cada `intervalo_seg` reais). Todas as transições passam a gravar `heartbeat_em=agora_real()` em vez de tempo simulado.

- [ ] **Step 1: Adicionar teste**

```python
def test_heartbeat_so_nas_ambulancias_ativas_do_worker():
    relogio, repo, fila, log, w = montar()
    repo.salvar_ambulancia(Ambulancia(id="amb-2", base_id="b1", lat=0, lon=0, worker_id="w1"))     # disponivel
    repo.salvar_ambulancia(Ambulancia(id="amb-9", base_id="b1", lat=0, lon=0, worker_id="w9"))     # outro worker
    repo.reservar_ambulancia("amb-9", 0, "ch-x")
    despachar(repo, fila)                      # amb-1 reservada pelo w1
    w._agora_real = lambda: 777.0
    assert w.bater_heartbeat() == 1
    assert repo.obter_ambulancia("amb-1").heartbeat_em == 777.0
    assert repo.obter_ambulancia("amb-2").heartbeat_em == 0.0
    assert repo.obter_ambulancia("amb-9").heartbeat_em == 0.0


def test_thread_de_heartbeat_roda_e_para():
    import threading, time
    relogio, repo, fila, log, w = montar()
    despachar(repo, fila)
    parar = threading.Event()
    t = w.iniciar_heartbeat(intervalo_seg=0.02, parar=parar)
    time.sleep(0.1)
    parar.set(); t.join(timeout=1)
    assert not t.is_alive()
    assert repo.obter_ambulancia("amb-1").heartbeat_em > 0
```

- [ ] **Step 2: Rodar e ver falhar** → AttributeError.

- [ ] **Step 3: Implementar**

No `__init__` adicionar parâmetro `agora_real=time.time` (importar `time`) e `self._agora_real = agora_real`. Em `processar_lote` e `_transicionar`, trocar `heartbeat_em=self._relogio.agora_sim()` por `heartbeat_em=self._agora_real()`. Adicionar:

```python
    def bater_heartbeat(self) -> int:
        ts = self._agora_real()
        n = 0
        for a in self._repo.listar_ambulancias(worker_id=self.worker_id):
            if a.status != SA.DISPONIVEL:
                self._repo.atualizar_heartbeat(a.id, ts)
                n += 1
        return n

    def iniciar_heartbeat(self, intervalo_seg: float, parar: threading.Event) -> threading.Thread:
        def loop():
            while not parar.wait(intervalo_seg):
                try:
                    self.bater_heartbeat()
                except Exception as e:  # noqa: BLE001 - heartbeat nunca derruba o worker
                    self._log.registrar("erro_heartbeat", worker_id=self.worker_id, erro=repr(e))
        t = threading.Thread(target=loop, name=f"heartbeat-{self.worker_id}", daemon=True)
        t.start()
        return t
```

- [ ] **Step 4: Rodar** `.venv/Scripts/python -m pytest tests/test_ambulancia.py -q` → `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/ambulancia/servico.py tests/test_ambulancia.py
git commit -m "feat(ambulancia): heartbeat em tempo real por worker

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Reaper

**Files:**
- Create: `samu_sim/api/__init__.py` (vazio por enquanto), `samu_sim/api/reaper.py`
- Test: `tests/test_reaper.py`

**Interfaces:**
- Consumes: `Repositorio.listar_ambulancias/liberar_ambulancia/obter_chamado/salvar_chamado`, `Fila.publicar`, `Base`, `EventLog`.
- Produces: `Reaper(repo, fila_chamados, bases: dict[str, Base], eventlog, timeout_seg: float = 120.0, agora_real=time.time)` com `executar_uma_vez() -> int` (quantas liberou). Regra: ambulância com `status != DISPONIVEL` e `agora_real() - heartbeat_em > timeout_seg` → `liberar_ambulancia(id, versao, lat_base, lon_base)`; se tinha `chamado_id` e o chamado não está `ATENDIDO`: `status=PENDENTE, ambulancia_id=None, despachado_em=None, tentativas+1`, salva e republica na fila `chamados` (mesmo corpo do gerador). Evento `reaper_liberou {ambulancia_id, chamado_id, worker_id, idade_seg}`. `ConflitoVersao` → ignora (alguém mexeu; próxima rodada).

- [ ] **Step 1: Escrever `tests/test_reaper.py`**

```python
from samu_sim.api.reaper import Reaper
from samu_sim.core.modelos import Ambulancia, Base, Chamado, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria

BASE = Base("b1", "Base", -22.9, -43.2)


def montar():
    repo, fila = RepositorioMemoria(), FilaMemoria()
    log = EventLogMemoria(Relogio(), "api")
    reaper = Reaper(repo, fila, {"b1": BASE}, log, timeout_seg=120, agora_real=lambda: 1000.0)
    return repo, fila, log, reaper


def amb(id, status, heartbeat, chamado_id=None):
    a = Ambulancia(id=id, base_id="b1", lat=0, lon=0, worker_id="w0", status=status,
                   heartbeat_em=heartbeat, chamado_id=chamado_id, versao=3)
    return a


def test_libera_travada_e_devolve_chamado_para_fila():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("amb-1", SA.A_CAMINHO, heartbeat=800.0, chamado_id="ch-1"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50,
                                status=SC.DESPACHADO, ambulancia_id="amb-1", despachado_em=60))
    assert reaper.executar_uma_vez() == 1
    a = repo.obter_ambulancia("amb-1")
    assert a.status == SA.DISPONIVEL and a.chamado_id is None and (a.lat, a.lon) == (BASE.lat, BASE.lon)
    c = repo.obter_chamado("ch-1")
    assert c.status == SC.PENDENTE and c.ambulancia_id is None and c.tentativas == 1
    msg = fila.receber()[0].corpo
    assert msg["chamado_id"] == "ch-1" and msg["zona"] == "Sul"
    assert log.contar("reaper_liberou") == 1


def test_ignora_saudaveis_e_disponiveis():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("ok", SA.A_CAMINHO, heartbeat=950.0, chamado_id="ch-1"))   # 50 s atras
    repo.salvar_ambulancia(amb("livre", SA.DISPONIVEL, heartbeat=0.0))
    assert reaper.executar_uma_vez() == 0
    assert fila.tamanho() == 0


def test_chamado_ja_atendido_nao_volta_para_fila():
    repo, fila, log, reaper = montar()
    repo.salvar_ambulancia(amb("amb-1", SA.RETORNANDO, heartbeat=100.0, chamado_id="ch-1"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=50,
                                status=SC.ATENDIDO, ambulancia_id="amb-1"))
    assert reaper.executar_uma_vez() == 1
    assert fila.tamanho() == 0
    assert repo.obter_chamado("ch-1").status == SC.ATENDIDO
```

- [ ] **Step 2: Rodar e ver falhar** → `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/api/reaper.py`** (e criar `samu_sim/api/__init__.py` vazio)

```python
"""Reaper: libera ambulancias cujo worker parou de bater heartbeat e devolve o
chamado (se nao atendido) para a fila. Roda periodicamente dentro da api."""
import time

from samu_sim.core.modelos import Base, StatusAmbulancia, StatusChamado
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import ConflitoVersao, Repositorio


class Reaper:
    def __init__(self, repo: Repositorio, fila_chamados: Fila, bases: dict[str, Base],
                 eventlog: EventLog, timeout_seg: float = 120.0, agora_real=time.time):
        self._repo = repo
        self._fila = fila_chamados
        self._bases = bases
        self._log = eventlog
        self._timeout = timeout_seg
        self._agora_real = agora_real

    def executar_uma_vez(self) -> int:
        agora = self._agora_real()
        liberadas = 0
        for a in self._repo.listar_ambulancias():
            if a.status == StatusAmbulancia.DISPONIVEL:
                continue
            idade = agora - a.heartbeat_em
            if idade <= self._timeout:
                continue
            base = self._bases[a.base_id]
            try:
                self._repo.liberar_ambulancia(a.id, a.versao, base.lat, base.lon)
            except ConflitoVersao:
                continue
            liberadas += 1
            self._log.registrar("reaper_liberou", ambulancia_id=a.id, chamado_id=a.chamado_id,
                                worker_id=a.worker_id, idade_seg=idade, status_anterior=str(a.status))
            if a.chamado_id:
                self._devolver_chamado(a.chamado_id)
        return liberadas

    def _devolver_chamado(self, chamado_id: str) -> None:
        c = self._repo.obter_chamado(chamado_id)
        if c is None or c.status == StatusChamado.ATENDIDO:
            return
        c.status = StatusChamado.PENDENTE
        c.ambulancia_id = None
        c.despachado_em = None
        c.tentativas += 1
        self._repo.salvar_chamado(c)
        self._fila.publicar({"chamado_id": c.id, "lat": c.lat, "lon": c.lon,
                             "bairro": c.bairro, "zona": c.zona, "criado_em": c.criado_em})
```

- [ ] **Step 4: Rodar** → `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/api/__init__.py samu_sim/api/reaper.py tests/test_reaper.py
git commit -m "feat(api): reaper libera ambulancias sem heartbeat e devolve chamados

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `FilaSQS` e `RepositorioDynamo`

**Files:**
- Create: `samu_sim/infra/aws.py`
- Test: `tests/test_aws_serializacao.py` (unitário), `tests/test_aws_integracao.py` (`@integration`)

**Interfaces:**
- Produces:
  - `cliente_sqs(cfg: Config)`, `recurso_dynamo(cfg: Config)` — boto3 com `endpoint_url=cfg.aws_endpoint_url`, `region_name=cfg.aws_region`.
  - `para_item(obj) -> dict` (dataclass → dict com `float`→`Decimal`, `StrEnum`→`str`, `None` mantido) e `de_item(cls, item) -> obj` (inverso, usando as anotações de tipo do dataclass: `float`, `int`, `str`, `float | None`, `str | None`, enums).
  - `FilaSQS(sqs, url: str, espera_seg: int = 1)` implementa `Fila`; `Mensagem.handle` = `ReceiptHandle`; `tamanho()` via `ApproximateNumberOfMessages + NotVisible`.
  - `RepositorioDynamo(dynamo, cfg: Config)` implementa `Repositorio` (todas as operações do Protocol, incluindo Task 2) sobre as tabelas `cfg.tabela("ambulancias"|"chamados"|"rodada")`. `transicionar`/`reservar_ambulancia`/`liberar_ambulancia` usam `ConditionExpression`; `ConditionalCheckFailedException` → `ConflitoVersao`.
  - `ambulancia_do_item`, `chamado_do_item` helpers via `de_item`.

- [ ] **Step 1: Escrever `tests/test_aws_serializacao.py`**

```python
from decimal import Decimal
from samu_sim.core.modelos import Ambulancia, Chamado, Rodada, StatusAmbulancia as SA, StatusChamado as SC
from samu_sim.infra.aws import para_item, de_item


def test_ambulancia_ida_e_volta():
    a = Ambulancia(id="amb-1", base_id="b", lat=-22.9, lon=-43.2, worker_id="w0",
                   status=SA.A_CAMINHO, versao=4, chamado_id="ch-1", heartbeat_em=1.5)
    item = para_item(a)
    assert item["lat"] == Decimal("-22.9") and item["status"] == "a_caminho" and item["versao"] == 4
    b = de_item(Ambulancia, item)
    assert b == a and isinstance(b.lat, float) and isinstance(b.versao, int) and b.status is SA.A_CAMINHO


def test_chamado_com_nones():
    c = Chamado(id="ch-1", lat=1.0, lon=2.0, bairro="B", zona="Sul", criado_em=10.0)
    item = para_item(c)
    assert item["chegada_em"] is None and item["status"] == "pendente"
    d = de_item(Chamado, item)
    assert d == c and d.status is SC.PENDENTE


def test_rodada():
    r = Rodada("atual", 42, "mais_proxima", 20.0, 50, "haversine", 1700000000.5, 0.0, False)
    assert de_item(Rodada, para_item(r)) == r
```

- [ ] **Step 2: Escrever `tests/test_aws_integracao.py`**

```python
"""Exige LocalStack: AWS_ENDPOINT_URL=http://localhost:4566 e docker compose up localstack."""
import os
import uuid
import pytest
import urllib.request

from samu_sim.core.config import Config
from samu_sim.core.modelos import Ambulancia, Chamado, Rodada, StatusAmbulancia as SA
from samu_sim.infra.aws import FilaSQS, RepositorioDynamo, cliente_sqs, recurso_dynamo
from samu_sim.infra.bootstrap import criar_recursos, apagar_recursos
from samu_sim.infra.repositorio import ConflitoVersao

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cfg():
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    try:
        urllib.request.urlopen(endpoint + "/_localstack/health", timeout=2)
    except Exception:
        pytest.skip("LocalStack nao esta acessivel")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    c = Config(aws_endpoint_url=endpoint, prefixo_tabela=f"t{uuid.uuid4().hex[:6]}-",
               prefixo_fila_eventos=f"q{uuid.uuid4().hex[:6]}-", fila_chamados=f"c{uuid.uuid4().hex[:6]}",
               n_workers=1)
    criar_recursos(c)
    yield c
    apagar_recursos(c)


def test_fila_sqs_publica_recebe_ack(cfg):
    sqs = cliente_sqs(cfg)
    url = sqs.get_queue_url(QueueName=cfg.fila_chamados)["QueueUrl"]
    f = FilaSQS(sqs, url)
    f.publicar({"chamado_id": "ch-1", "x": 1.5})
    msgs = f.receber()
    assert len(msgs) == 1 and msgs[0].corpo == {"chamado_id": "ch-1", "x": 1.5}
    f.ack(msgs[0])
    assert f.receber() == []


def test_dynamo_reserva_condicional(cfg):
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)
    repo.salvar_ambulancia(Ambulancia(id="amb-1", base_id="b", lat=-22.9, lon=-43.2, worker_id="w0"))
    a = repo.reservar_ambulancia("amb-1", 0, "ch-1")
    assert a.status == SA.RESERVADA and a.versao == 1
    with pytest.raises(ConflitoVersao):
        repo.reservar_ambulancia("amb-1", 0, "ch-2")
    a = repo.transicionar("amb-1", SA.RESERVADA, SA.A_CAMINHO, 1, heartbeat_em=5.0)
    assert a.versao == 2 and a.heartbeat_em == 5.0
    repo.atualizar_heartbeat("amb-1", 9.0)
    assert repo.obter_ambulancia("amb-1").versao == 2
    assert [x.id for x in repo.listar_ambulancias(SA.A_CAMINHO, worker_id="w0")] == ["amb-1"]
    b = repo.liberar_ambulancia("amb-1", 2, lat=0.0, lon=0.0)
    assert b.status == SA.DISPONIVEL and b.chamado_id is None


def test_dynamo_chamado_e_rodada(cfg):
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)
    repo.salvar_chamado(Chamado(id="ch-1", lat=1.0, lon=2.0, bairro="B", zona="Sul", criado_em=3.0))
    c = repo.obter_chamado("ch-1")
    assert c.zona == "Sul" and c.chegada_em is None
    assert repo.obter_chamado("nao") is None
    assert any(x.id == "ch-1" for x in repo.listar_chamados())
    repo.salvar_rodada(Rodada("atual", 1, "mais_proxima", 20.0, 5, "haversine", 100.0, 0.0))
    assert repo.obter_rodada().fator == 20.0
```

- [ ] **Step 3: Rodar unitário e ver falhar** → `.venv/Scripts/python -m pytest tests/test_aws_serializacao.py -q` → `ModuleNotFoundError`.

- [ ] **Step 4: Implementar `samu_sim/infra/aws.py`**

```python
"""Implementacoes AWS de Fila (SQS) e Repositorio (DynamoDB), via boto3.
Funcionam contra LocalStack (endpoint_url) e contra a AWS real (endpoint None)."""
import json
import types
import typing
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum

import boto3
from botocore.exceptions import ClientError

from samu_sim.core.config import Config
from samu_sim.core.modelos import (
    Ambulancia, Chamado, Rodada, StatusAmbulancia, transicao_valida,
)
from samu_sim.infra.fila import Mensagem
from samu_sim.infra.repositorio import ConflitoVersao

RODADA_ID = "atual"


# ---------- clientes ----------
def cliente_sqs(cfg: Config):
    return boto3.client("sqs", region_name=cfg.aws_region, endpoint_url=cfg.aws_endpoint_url)


def recurso_dynamo(cfg: Config):
    return boto3.resource("dynamodb", region_name=cfg.aws_region, endpoint_url=cfg.aws_endpoint_url)


# ---------- serializacao ----------
def para_item(obj) -> dict:
    item = {}
    for f in fields(obj):
        v = getattr(obj, f.name)
        if isinstance(v, Enum):
            v = v.value
        elif isinstance(v, float):
            v = Decimal(repr(v))
        item[f.name] = v
    return item


def _tipo_base(anot):
    """float | None -> float; StrEnum -> a enum; str -> str."""
    if isinstance(anot, str):
        anot = eval(anot, vars(__import__("samu_sim.core.modelos", fromlist=["x"])))  # noqa: S307
    if isinstance(anot, types.UnionType) or typing.get_origin(anot) is typing.Union:
        args = [a for a in typing.get_args(anot) if a is not type(None)]
        return args[0]
    return anot


def de_item(cls, item: dict):
    valores = {}
    for f in fields(cls):
        v = item.get(f.name)
        tipo = _tipo_base(f.type)
        if v is None:
            valores[f.name] = None
        elif isinstance(tipo, type) and issubclass(tipo, Enum):
            valores[f.name] = tipo(v)
        elif tipo is float:
            valores[f.name] = float(v)
        elif tipo is int:
            valores[f.name] = int(v)
        elif tipo is bool:
            valores[f.name] = bool(v)
        else:
            valores[f.name] = v
    return cls(**valores)


# ---------- SQS ----------
class FilaSQS:
    def __init__(self, sqs, url: str, espera_seg: int = 1):
        self._sqs = sqs
        self._url = url
        self._espera = espera_seg

    def publicar(self, corpo: dict) -> None:
        self._sqs.send_message(QueueUrl=self._url, MessageBody=json.dumps(corpo))

    def receber(self, max_msgs: int = 10) -> list[Mensagem]:
        r = self._sqs.receive_message(QueueUrl=self._url, MaxNumberOfMessages=min(max_msgs, 10),
                                      WaitTimeSeconds=self._espera)
        return [Mensagem(id=m["MessageId"], corpo=json.loads(m["Body"]), handle=m["ReceiptHandle"])
                for m in r.get("Messages", [])]

    def ack(self, msg: Mensagem) -> None:
        try:
            self._sqs.delete_message(QueueUrl=self._url, ReceiptHandle=msg.handle)
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("ReceiptHandleIsInvalid", "InvalidParameterValue"):
                raise

    def tamanho(self) -> int:
        attrs = self._sqs.get_queue_attributes(
            QueueUrl=self._url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
        return int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"])


# ---------- DynamoDB ----------
def _conflito(e: ClientError) -> bool:
    return e.response["Error"]["Code"] == "ConditionalCheckFailedException"


def _scan_tudo(tabela, **kw) -> list[dict]:
    itens, r = [], tabela.scan(**kw)
    itens.extend(r.get("Items", []))
    while "LastEvaluatedKey" in r:
        r = tabela.scan(ExclusiveStartKey=r["LastEvaluatedKey"], **kw)
        itens.extend(r.get("Items", []))
    return itens


class RepositorioDynamo:
    def __init__(self, dynamo, cfg: Config):
        self._amb = dynamo.Table(cfg.tabela("ambulancias"))
        self._ch = dynamo.Table(cfg.tabela("chamados"))
        self._rod = dynamo.Table(cfg.tabela("rodada"))

    # --- ambulancias ---
    def salvar_ambulancia(self, a: Ambulancia) -> None:
        self._amb.put_item(Item=para_item(a))

    def obter_ambulancia(self, id: str) -> Ambulancia | None:
        item = self._amb.get_item(Key={"id": id}, ConsistentRead=True).get("Item")
        return de_item(Ambulancia, item) if item else None

    def listar_ambulancias(self, status: StatusAmbulancia | None = None,
                           worker_id: str | None = None) -> list[Ambulancia]:
        from boto3.dynamodb.conditions import Attr
        cond = None
        if status is not None:
            cond = Attr("status").eq(str(status))
        if worker_id is not None:
            c2 = Attr("worker_id").eq(worker_id)
            cond = c2 if cond is None else cond & c2
        kw = {"ConsistentRead": True}
        if cond is not None:
            kw["FilterExpression"] = cond
        return [de_item(Ambulancia, i) for i in _scan_tudo(self._amb, **kw)]

    def reservar_ambulancia(self, id: str, versao: int, chamado_id: str) -> Ambulancia:
        return self.transicionar(id, StatusAmbulancia.DISPONIVEL, StatusAmbulancia.RESERVADA,
                                 versao, chamado_id=chamado_id)

    def transicionar(self, id: str, de: StatusAmbulancia, para: StatusAmbulancia,
                     versao: int, **campos) -> Ambulancia:
        if not transicao_valida(de, para):
            raise ConflitoVersao(f"transicao invalida {de}->{para}")
        return self._update_condicional(
            id, campos | {"status": str(para)},
            cond="#status = :de AND versao = :v", valores={":de": str(de), ":v": versao}, versao=versao)

    def liberar_ambulancia(self, id: str, versao: int, lat: float, lon: float) -> Ambulancia:
        return self._update_condicional(
            id, {"status": str(StatusAmbulancia.DISPONIVEL), "chamado_id": None, "lat": lat, "lon": lon},
            cond="versao = :v", valores={":v": versao}, versao=versao)

    def _update_condicional(self, id: str, campos: dict, cond: str, valores: dict, versao: int) -> Ambulancia:
        nomes = {"#status": "status"}
        sets = ["versao = :nv"]
        vals = dict(valores) | {":nv": versao + 1}
        for k, v in campos.items():
            nomes[f"#{k}"] = k
            sets.append(f"#{k} = :{k}")
            vals[f":{k}"] = Decimal(repr(v)) if isinstance(v, float) else v
        try:
            r = self._amb.update_item(
                Key={"id": id}, UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression=cond, ExpressionAttributeNames=nomes,
                ExpressionAttributeValues=vals, ReturnValues="ALL_NEW")
        except ClientError as e:
            if _conflito(e):
                raise ConflitoVersao(f"{id}: condicao falhou ({cond})") from None
            raise
        return de_item(Ambulancia, r["Attributes"])

    def atualizar_heartbeat(self, id: str, ts: float) -> None:
        self._amb.update_item(Key={"id": id}, UpdateExpression="SET heartbeat_em = :t",
                              ExpressionAttributeValues={":t": Decimal(repr(ts))})

    # --- chamados ---
    def salvar_chamado(self, c: Chamado) -> None:
        self._ch.put_item(Item=para_item(c))

    def obter_chamado(self, id: str) -> Chamado | None:
        item = self._ch.get_item(Key={"id": id}, ConsistentRead=True).get("Item")
        return de_item(Chamado, item) if item else None

    def listar_chamados(self) -> list[Chamado]:
        return [de_item(Chamado, i) for i in _scan_tudo(self._ch, ConsistentRead=True)]

    # --- rodada ---
    def salvar_rodada(self, r: Rodada) -> None:
        item = para_item(r)
        item["id"] = RODADA_ID
        self._rod.put_item(Item=item)

    def obter_rodada(self) -> Rodada | None:
        item = self._rod.get_item(Key={"id": RODADA_ID}, ConsistentRead=True).get("Item")
        return de_item(Rodada, item) if item else None
```

Nota: `_tipo_base` cobre anotações como `float | None` (Python 3.12 guarda o objeto `types.UnionType` quando não há `from __future__ import annotations`; se as anotações vierem como string, o `eval` no namespace de `modelos` resolve). Mantenha `modelos.py` **sem** `from __future__ import annotations`.

- [ ] **Step 5: Rodar unitário** → `3 passed`. O de integração espera a Task 6 (bootstrap) e o LocalStack.

- [ ] **Step 6: Commit**

```bash
git add samu_sim/infra/aws.py tests/test_aws_serializacao.py tests/test_aws_integracao.py
git commit -m "feat(infra): FilaSQS e RepositorioDynamo com atualizacoes condicionais

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Bootstrap (filas, tabelas, frota, rodada) + teste de integração

**Files:**
- Create: `samu_sim/infra/bootstrap.py`
- Test: `tests/test_aws_integracao.py` (já escrito na Task 5)

**Interfaces:**
- Produces:
  - `criar_recursos(cfg) -> None` — idempotente: cria fila `cfg.fila_chamados` e `cfg.fila_eventos(f"w{k}")` para `k < cfg.n_workers` (`VisibilityTimeout=30`), tabelas `ambulancias`, `chamados`, `rodada` (PK `id` string, `PAY_PER_REQUEST`), esperando `table_exists`.
  - `apagar_recursos(cfg) -> None` — apaga tudo (ignora inexistentes).
  - `semear(cfg, repo, agora_real=time.time) -> Rodada` — apaga e recria as tabelas (rodada limpa), purga filas, grava frota via `montar_frota(bases, cfg.n_ambulancias, cfg.n_workers)` e a `Rodada(id="atual", seed, politica, fator, n_ambulancias, roteador, inicio_real=agora_real(), inicio_sim=0.0)`.
  - `main()` — `python -m samu_sim.infra.bootstrap`: `criar_recursos` + `semear`, imprime resumo. Usa `Config.do_ambiente()`.

- [ ] **Step 1: Implementar `samu_sim/infra/bootstrap.py`**

```python
"""Cria filas SQS e tabelas DynamoDB (LocalStack ou AWS) e semeia frota + rodada.
Uso: python -m samu_sim.infra.bootstrap"""
import time
from pathlib import Path

from botocore.exceptions import ClientError

from samu_sim.core.config import Config
from samu_sim.core.modelos import Rodada
from samu_sim.gerador.demanda import carregar_bases
from samu_sim.infra.aws import RODADA_ID, RepositorioDynamo, cliente_sqs, recurso_dynamo
from samu_sim.local import montar_frota

TABELAS = ("ambulancias", "chamados", "rodada")


def _nomes_filas(cfg: Config) -> list[str]:
    return [cfg.fila_chamados] + [cfg.fila_eventos(f"w{k}") for k in range(cfg.n_workers)]


def _criar_tabela(dynamo, nome: str) -> None:
    try:
        t = dynamo.create_table(TableName=nome, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                                AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                                BillingMode="PAY_PER_REQUEST")
        t.wait_until_exists()
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise


def _apagar_tabela(dynamo, nome: str) -> None:
    try:
        t = dynamo.Table(nome)
        t.delete()
        t.wait_until_not_exists()
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise


def criar_recursos(cfg: Config) -> None:
    sqs, dynamo = cliente_sqs(cfg), recurso_dynamo(cfg)
    for nome in _nomes_filas(cfg):
        sqs.create_queue(QueueName=nome, Attributes={"VisibilityTimeout": "30"})
    for t in TABELAS:
        _criar_tabela(dynamo, cfg.tabela(t))


def apagar_recursos(cfg: Config) -> None:
    sqs, dynamo = cliente_sqs(cfg), recurso_dynamo(cfg)
    for nome in _nomes_filas(cfg):
        try:
            sqs.delete_queue(QueueUrl=sqs.get_queue_url(QueueName=nome)["QueueUrl"])
        except ClientError:
            pass
    for t in TABELAS:
        _apagar_tabela(dynamo, cfg.tabela(t))


def semear(cfg: Config, repo: RepositorioDynamo | None = None, agora_real=time.time) -> Rodada:
    sqs, dynamo = cliente_sqs(cfg), recurso_dynamo(cfg)
    for t in TABELAS:
        _apagar_tabela(dynamo, cfg.tabela(t))
        _criar_tabela(dynamo, cfg.tabela(t))
    for nome in _nomes_filas(cfg):
        try:
            sqs.purge_queue(QueueUrl=sqs.get_queue_url(QueueName=nome)["QueueUrl"])
        except ClientError as e:
            if e.response["Error"]["Code"] != "AWS.SimpleQueueService.PurgeQueueInProgress":
                raise
    repo = repo or RepositorioDynamo(dynamo, cfg)
    bases = carregar_bases(Path(cfg.dados_dir) / "bases.csv")
    for a in montar_frota(bases, cfg.n_ambulancias, cfg.n_workers):
        repo.salvar_ambulancia(a)
    rodada = Rodada(RODADA_ID, cfg.seed, cfg.politica, cfg.fator, cfg.n_ambulancias, cfg.roteador,
                    inicio_real=agora_real(), inicio_sim=0.0)
    repo.salvar_rodada(rodada)
    return rodada


def main() -> None:
    cfg = Config.do_ambiente()
    criar_recursos(cfg)
    r = semear(cfg)
    print(f"bootstrap ok: {cfg.n_ambulancias} ambulancias, {cfg.n_workers} workers, "
          f"fator {r.fator}, politica {r.politica}, endpoint {cfg.aws_endpoint_url}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Subir o LocalStack e rodar integração**

Criar `docker-compose.yml` mínimo agora (a Task 9 completa):
```yaml
services:
  localstack:
    image: localstack/localstack:3
    ports: ["4566:4566"]
    environment:
      - SERVICES=sqs,dynamodb
      - EAGER_SERVICE_LOADING=1
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:4566/_localstack/health"]
      interval: 5s
      timeout: 3s
      retries: 20
```
```bash
docker compose up -d localstack
set AWS_ENDPOINT_URL=http://localhost:4566 && set AWS_ACCESS_KEY_ID=test && set AWS_SECRET_ACCESS_KEY=test && .venv/Scripts/python -m pytest -q -m integration
```
Esperado: `3 passed`. (No Git Bash: `AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test .venv/Scripts/python -m pytest -q -m integration`.)

- [ ] **Step 3: Rodar o bootstrap de verdade**

```bash
AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test .venv/Scripts/python -m samu_sim.infra.bootstrap
```
Esperado: `bootstrap ok: 50 ambulancias, 2 workers, fator 20.0, ...`.

- [ ] **Step 4: Commit**

```bash
git add samu_sim/infra/bootstrap.py docker-compose.yml
git commit -m "feat(infra): bootstrap de filas, tabelas, frota e rodada

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Runtime compartilhado e entrypoints dos serviços

**Files:**
- Create: `samu_sim/core/runtime.py`, `samu_sim/gerador/__main__.py`, `samu_sim/despachante/__main__.py`, `samu_sim/ambulancia/__main__.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Produces (em `runtime.py`):
  - `configurar_logging(servico: str) -> None` — `logging` JSON em stdout (`{"ts", "nivel", "servico", "msg"}`).
  - `montar_infra(cfg) -> Infra` com `Infra(repo: Repositorio, fila_chamados: Fila, filas_eventos: dict[str, Fila], bases: dict[str, Base], bairros: list[Bairro])`.
  - `relogio_da_rodada(repo, agora_real=time.time) -> Relogio` — lê `obter_rodada()` (espera até 60 s aparecer), cria `Relogio(agora_real=agora_real)` e chama `sincronizar`.
  - `SincronizadorRelogio(relogio, repo, intervalo_seg, parar: threading.Event, ao_mudar=None)` com `sincronizar_uma_vez() -> bool` (True se mudou algo) e `iniciar() -> threading.Thread`. Re-sincroniza `inicio_real, inicio_sim, fator` quando qualquer um difere do último visto.
  - `loop_servico(processar, parar, ocioso_seg=0.05)` — igual ao `loop` do `local.py`.
  - `instalar_sinais(parar)` — SIGINT/SIGTERM setam `parar`.

- [ ] **Step 1: Escrever `tests/test_runtime.py`**

```python
import threading
from samu_sim.core.modelos import Rodada
from samu_sim.core.relogio import Relogio
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
```

- [ ] **Step 2: Rodar e ver falhar** → `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `samu_sim/core/runtime.py`**

```python
"""Plumbing comum aos servicos: logging JSON, montagem da infra a partir da Config,
relogio sincronizado com a tabela rodada, loop de servico e sinais."""
import json
import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from samu_sim.core.config import Config
from samu_sim.core.modelos import Base, Rodada
from samu_sim.core.relogio import Relogio
from samu_sim.gerador.demanda import Bairro, carregar_bairros, carregar_bases
from samu_sim.infra.aws import FilaSQS, RepositorioDynamo, cliente_sqs, recurso_dynamo
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio


class _FormatadorJson(logging.Formatter):
    def __init__(self, servico: str):
        super().__init__()
        self._servico = servico

    def format(self, r: logging.LogRecord) -> str:
        return json.dumps({"ts": time.time(), "nivel": r.levelname, "servico": self._servico,
                           "msg": r.getMessage()}, ensure_ascii=False)


def configurar_logging(servico: str) -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_FormatadorJson(servico))
    logging.basicConfig(level=logging.INFO, handlers=[h], force=True)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@dataclass
class Infra:
    repo: Repositorio
    fila_chamados: Fila
    filas_eventos: dict[str, Fila]
    bases: dict[str, Base]
    bairros: list[Bairro]


def montar_infra(cfg: Config) -> Infra:
    sqs = cliente_sqs(cfg)
    repo = RepositorioDynamo(recurso_dynamo(cfg), cfg)

    def fila(nome: str) -> FilaSQS:
        return FilaSQS(sqs, sqs.get_queue_url(QueueName=nome)["QueueUrl"])

    filas_eventos = {f"w{k}": fila(cfg.fila_eventos(f"w{k}")) for k in range(cfg.n_workers)}
    dados = Path(cfg.dados_dir)
    bases = {b.id: b for b in carregar_bases(dados / "bases.csv")}
    return Infra(repo, fila(cfg.fila_chamados), filas_eventos, bases, carregar_bairros(dados / "bairros.csv"))


def relogio_da_rodada(repo: Repositorio, agora_real=time.time, espera_max_seg: float = 60.0) -> Relogio:
    fim = time.monotonic() + espera_max_seg
    while True:
        rodada = repo.obter_rodada()
        if rodada is not None:
            break
        if time.monotonic() > fim:
            raise RuntimeError("tabela rodada vazia: rode o bootstrap")
        time.sleep(1)
    r = Relogio(agora_real=agora_real)
    r.sincronizar(rodada.inicio_real, rodada.inicio_sim, rodada.fator)
    return r


class SincronizadorRelogio:
    def __init__(self, relogio: Relogio, repo: Repositorio, intervalo_seg: float,
                 parar: threading.Event, ao_mudar=None):
        self._relogio = relogio
        self._repo = repo
        self._intervalo = intervalo_seg
        self._parar = parar
        self._ao_mudar = ao_mudar
        self._ultimo: tuple[float, float, float] | None = None

    def sincronizar_uma_vez(self) -> bool:
        rodada = self._repo.obter_rodada()
        if rodada is None:
            return False
        chave = (rodada.inicio_real, rodada.inicio_sim, rodada.fator)
        if self._ultimo is None:
            self._ultimo = chave
            return False
        if chave == self._ultimo:
            return False
        self._ultimo = chave
        self._relogio.sincronizar(*chave)
        logging.info(f"relogio sincronizado: fator={rodada.fator} inicio_sim={rodada.inicio_sim:.0f}")
        if self._ao_mudar:
            self._ao_mudar(rodada)
        return True

    def iniciar(self) -> threading.Thread:
        def loop():
            self.sincronizar_uma_vez()
            while not self._parar.wait(self._intervalo):
                try:
                    self.sincronizar_uma_vez()
                except Exception as e:  # noqa: BLE001
                    logging.warning(f"falha ao sincronizar relogio: {e!r}")
        t = threading.Thread(target=loop, name="sync-relogio", daemon=True)
        t.start()
        return t


def loop_servico(processar, parar: threading.Event, ocioso_seg: float = 0.05) -> None:
    while not parar.is_set():
        try:
            if processar() == 0:
                time.sleep(ocioso_seg)
        except Exception as e:  # noqa: BLE001 - loga e continua; a fila reentrega
            logging.exception(f"erro no loop de servico: {e!r}")
            time.sleep(1)


def instalar_sinais(parar: threading.Event) -> None:
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, lambda *_: parar.set())
        except ValueError:
            pass  # fora da main thread (testes)
```

- [ ] **Step 4: Rodar** `tests/test_runtime.py` → `2 passed`.

- [ ] **Step 5: Escrever os entrypoints**

`samu_sim/gerador/__main__.py`:
```python
import logging
import threading

from samu_sim.core.config import Config
from samu_sim.core.runtime import (SincronizadorRelogio, configurar_logging, instalar_sinais,
                                   montar_infra, relogio_da_rodada)
from samu_sim.eventlog import EventLogJsonl
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
    logging.info(f"gerador encerrou: {n} publicados")


if __name__ == "__main__":
    main()
```

`samu_sim/despachante/__main__.py`:
```python
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
    d = Despachante(infra.fila_chamados, infra.filas_eventos, infra.repo,
                    criar_politica(rodada.politica), criar_roteador(rodada.roteador), relogio, log)

    def trocar_politica(rod):
        d._politica = criar_politica(rod.politica)

    SincronizadorRelogio(relogio, infra.repo, cfg.sync_relogio_seg, parar, ao_mudar=trocar_politica).iniciar()
    logging.info(f"{nome}: politica={rodada.politica} roteador={rodada.roteador}")
    loop_servico(d.processar_lote, parar, ocioso_seg=0.0)  # FilaSQS ja faz long polling de 1 s
    log.fechar()


if __name__ == "__main__":
    main()
```

`samu_sim/ambulancia/__main__.py`:
```python
import logging
import threading

from samu_sim.ambulancia.servico import WorkerAmbulancia
from samu_sim.core.config import Config
from samu_sim.core.runtime import (SincronizadorRelogio, configurar_logging, instalar_sinais,
                                   loop_servico, montar_infra, relogio_da_rodada)
from samu_sim.eventlog import EventLogJsonl
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
                         criar_roteador(rodada.roteador), infra.bases, log, seed=rodada.seed)
    w.iniciar_heartbeat(cfg.heartbeat_seg, parar)
    logging.info(f"{nome}: pronto (heartbeat a cada {cfg.heartbeat_seg}s)")
    loop_servico(w.processar_lote, parar, ocioso_seg=0.0)
    w.aguardar_ciclos(timeout=5)
    w.encerrar()
    log.fechar()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Smoke test local contra LocalStack (sem Docker para os serviços)**

Em 3 terminais Git Bash (ou em background com `&`), com `AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test FATOR=200`:
```bash
.venv/Scripts/python -m samu_sim.infra.bootstrap
.venv/Scripts/python -m samu_sim.ambulancia &   # WORKER_ID=w0
WORKER_ID=w1 .venv/Scripts/python -m samu_sim.ambulancia &
.venv/Scripts/python -m samu_sim.despachante &
.venv/Scripts/python -m samu_sim.gerador &
sleep 60; ls logs/local/; grep -c '"chegou"' logs/local/ambulancia-w0.jsonl
```
Esperado: 4 arquivos JSONL, e `chegou` > 0 depois de ~1 min (fator 200 → 1 min real = 3,3 h sim). Matar tudo com `kill %1 %2 %3 %4`.

- [ ] **Step 7: Commit**

```bash
git add samu_sim/core/runtime.py samu_sim/gerador/__main__.py samu_sim/despachante/__main__.py samu_sim/ambulancia/__main__.py tests/test_runtime.py
git commit -m "feat: runtime compartilhado e entrypoints dos servicos sobre SQS/DynamoDB

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: API (FastAPI) com `/estado`, `/metricas`, `/controle` e reaper

**Files:**
- Modify: `samu_sim/api/__init__.py`
- Create: `samu_sim/api/__main__.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `criar_app(repo, fila_chamados, bases, relogio, eventlog, agora_real=time.time) -> FastAPI` com:
  - `GET /estado` → `{"agora_sim", "fator", "pausada", "rodada": {...}, "ambulancias": [{id, lat, lon, status, base_id, chamado_id, worker_id}], "chamados_abertos": [{id, lat, lon, zona, status, criado_em}]}` (abertos = pendente ou despachado).
  - `GET /metricas` → `calcular(listar_chamados())` + `{"agora_sim", "fila": {"pendentes", "idade_max_seg"}}` (idade do pendente mais antigo em tempo simulado).
  - `POST /controle` body `{"fator"?: float, "pausada"?: bool, "politica"?: str}` → atualiza a rodada: novo checkpoint `inicio_real=agora_real(), inicio_sim=relogio.agora_sim()`, `fator = 0 se pausada else fator`; sincroniza o próprio relógio; registra `fator_alterado`; retorna a rodada. `fator` inválido (`< 0`) → 422.
  - `GET /saude` → `{"ok": true}`.
  - `app.state.reaper` = `Reaper(...)`; `__main__` roda a thread do reaper a cada `cfg.reaper_intervalo_seg` e o `SincronizadorRelogio`.

- [ ] **Step 1: Escrever `tests/test_api.py`**

```python
from fastapi.testclient import TestClient
from samu_sim.api import criar_app
from samu_sim.core.modelos import Ambulancia, Base, Chamado, Rodada, StatusChamado as SC
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLogMemoria
from samu_sim.infra.fila import FilaMemoria
from samu_sim.infra.repositorio import RepositorioMemoria


def montar():
    repo = RepositorioMemoria()
    t = {"v": 1000.0}
    relogio = Relogio(fator=10, agora_real=lambda: t["v"])
    repo.salvar_rodada(Rodada("atual", 1, "mais_proxima", 10, 2, "haversine", 1000.0, 0.0))
    repo.salvar_ambulancia(Ambulancia(id="amb-1", base_id="b1", lat=-22.9, lon=-43.2, worker_id="w0"))
    repo.salvar_chamado(Chamado(id="ch-1", lat=1, lon=2, bairro="B", zona="Sul", criado_em=0.0))
    app = criar_app(repo, FilaMemoria(), {"b1": Base("b1", "B", -22.9, -43.2)}, relogio,
                    EventLogMemoria(relogio, "api"), agora_real=lambda: t["v"])
    return TestClient(app), repo, relogio, t


def test_estado():
    c, repo, relogio, t = montar()
    t["v"] = 1003.0
    r = c.get("/estado").json()
    assert r["agora_sim"] == 30.0 and r["fator"] == 10 and r["pausada"] is False
    assert r["ambulancias"][0]["id"] == "amb-1" and r["chamados_abertos"][0]["id"] == "ch-1"


def test_metricas_inclui_fila():
    c, repo, relogio, t = montar()
    t["v"] = 1006.0  # sim = 60
    r = c.get("/metricas").json()
    assert r["total"] == 1 and r["fila"]["pendentes"] == 1 and r["fila"]["idade_max_seg"] == 60.0


def test_controle_muda_fator_sem_saltar_o_tempo():
    c, repo, relogio, t = montar()
    t["v"] = 1003.0  # sim = 30
    r = c.post("/controle", json={"fator": 2}).json()
    assert r["fator"] == 2 and r["inicio_sim"] == 30.0 and r["inicio_real"] == 1003.0
    t["v"] = 1008.0
    assert c.get("/estado").json()["agora_sim"] == 40.0
    assert repo.obter_rodada().fator == 2


def test_controle_pausa_e_despausa():
    c, repo, relogio, t = montar()
    c.post("/controle", json={"pausada": True})
    t["v"] = 1100.0
    assert c.get("/estado").json()["agora_sim"] == 0.0
    assert c.get("/estado").json()["pausada"] is True
    r = c.post("/controle", json={"pausada": False}).json()
    assert r["fator"] == 10 and r["pausada"] is False


def test_controle_rejeita_fator_negativo():
    c, *_ = montar()
    assert c.post("/controle", json={"fator": -1}).status_code == 422
```

- [ ] **Step 2: Rodar e ver falhar** → `ImportError: cannot import name 'criar_app'`.

- [ ] **Step 3: Implementar `samu_sim/api/__init__.py`**

```python
"""API de observacao e controle da simulacao."""
import time
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from samu_sim.api.reaper import Reaper
from samu_sim.core.metricas import calcular
from samu_sim.core.modelos import Base, StatusChamado
from samu_sim.core.relogio import Relogio
from samu_sim.eventlog import EventLog
from samu_sim.infra.fila import Fila
from samu_sim.infra.repositorio import Repositorio


class Controle(BaseModel):
    fator: float | None = Field(default=None, ge=0)
    pausada: bool | None = None
    politica: str | None = None


def criar_app(repo: Repositorio, fila_chamados: Fila, bases: dict[str, Base], relogio: Relogio,
              eventlog: EventLog, agora_real=time.time, reaper_timeout_seg: float = 120.0) -> FastAPI:
    app = FastAPI(title="samu-sim")
    app.state.reaper = Reaper(repo, fila_chamados, bases, eventlog, reaper_timeout_seg, agora_real)
    app.state.relogio = relogio

    def snapshot() -> dict:
        rodada = repo.obter_rodada()
        agora = relogio.agora_sim()
        abertos = [c for c in repo.listar_chamados() if c.status != StatusChamado.ATENDIDO]
        return {
            "agora_sim": agora,
            "fator": rodada.fator if rodada else relogio.fator,
            "pausada": bool(rodada.pausada) if rodada else relogio.pausado,
            "rodada": asdict(rodada) if rodada else None,
            "ambulancias": [{"id": a.id, "lat": a.lat, "lon": a.lon, "status": str(a.status),
                             "base_id": a.base_id, "chamado_id": a.chamado_id, "worker_id": a.worker_id}
                            for a in repo.listar_ambulancias()],
            "chamados_abertos": [{"id": c.id, "lat": c.lat, "lon": c.lon, "zona": c.zona,
                                  "status": str(c.status), "criado_em": c.criado_em} for c in abertos],
        }

    app.state.snapshot = snapshot

    @app.get("/saude")
    def saude():
        return {"ok": True}

    @app.get("/estado")
    def estado():
        return snapshot()

    @app.get("/metricas")
    def metricas():
        chamados = repo.listar_chamados()
        agora = relogio.agora_sim()
        pendentes = [c for c in chamados if c.status == StatusChamado.PENDENTE]
        idade = max((agora - c.criado_em for c in pendentes), default=0.0)
        return calcular(chamados) | {"agora_sim": agora,
                                     "fila": {"pendentes": len(pendentes), "idade_max_seg": idade}}

    @app.post("/controle")
    def controle(cmd: Controle):
        rodada = repo.obter_rodada()
        if rodada is None:
            raise HTTPException(status_code=409, detail="rodada nao inicializada; rode o bootstrap")
        fator_ativo = rodada.fator if rodada.fator > 0 else relogio.fator
        if cmd.fator is not None:
            fator_ativo = cmd.fator
        if cmd.pausada is not None:
            rodada.pausada = cmd.pausada
        if cmd.politica is not None:
            rodada.politica = cmd.politica
        app.state.fator_ativo = fator_ativo if fator_ativo > 0 else app.state.__dict__.get("fator_ativo", 1.0)
        novo_fator = 0.0 if rodada.pausada else app.state.fator_ativo
        rodada.inicio_sim = relogio.agora_sim()
        rodada.inicio_real = agora_real()
        rodada.fator = novo_fator
        repo.salvar_rodada(rodada)
        relogio.sincronizar(rodada.inicio_real, rodada.inicio_sim, rodada.fator)
        eventlog.registrar("fator_alterado", fator=rodada.fator, pausada=rodada.pausada,
                           politica=rodada.politica)
        return asdict(rodada)

    return app
```

Observação sobre pausa: enquanto pausada, a rodada guarda `fator=0` (assim todos os serviços congelam via `sincronizar`) e a API lembra o último fator ativo em `app.state.fator_ativo` para restaurar no despause. Se a API reiniciar pausada, o despause volta a `1.0` — aceitável; documentar no README.

- [ ] **Step 4: Rodar** `tests/test_api.py` → `5 passed`. Se `test_controle_pausa_e_despausa` falhar no `fator == 10` após despause, verifique que `app.state.fator_ativo` foi definido no primeiro `POST` (o `montar()` cria app novo por teste).

- [ ] **Step 5: Implementar `samu_sim/api/__main__.py`**

```python
import logging
import threading

import uvicorn

from samu_sim.api import criar_app
from samu_sim.core.config import Config
from samu_sim.core.runtime import (SincronizadorRelogio, configurar_logging, montar_infra,
                                   relogio_da_rodada)
from samu_sim.eventlog import EventLogJsonl


def main() -> None:
    cfg = Config.do_ambiente()
    configurar_logging("api")
    infra = montar_infra(cfg)
    relogio = relogio_da_rodada(infra.repo)
    parar = threading.Event()
    SincronizadorRelogio(relogio, infra.repo, cfg.sync_relogio_seg, parar).iniciar()
    log = EventLogJsonl(cfg.log_dir, relogio, "api", cfg.rodada_id)
    app = criar_app(infra.repo, infra.fila_chamados, infra.bases, relogio, log,
                    reaper_timeout_seg=cfg.reaper_timeout_seg)

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


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add samu_sim/api tests/test_api.py
git commit -m "feat(api): endpoints de estado, metricas e controle com reaper periodico

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Dockerfile, docker compose completo e teste de caos

**Files:**
- Create: `Dockerfile`, `.dockerignore`
- Modify: `docker-compose.yml`

- [ ] **Step 1: `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY samu_sim ./samu_sim
COPY dados ./dados
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "samu_sim.api"]
```

`.dockerignore`:
```
.venv
venv
logs
.git
.pytest_cache
__pycache__
docs
tests
```

- [ ] **Step 2: `docker-compose.yml` completo**

```yaml
x-servico: &servico
  build: .
  environment: &env
    AWS_ENDPOINT_URL: http://localstack:4566
    AWS_ACCESS_KEY_ID: test
    AWS_SECRET_ACCESS_KEY: test
    AWS_REGION: us-east-1
    N_WORKERS: "2"
    LOG_DIR: /logs
    FATOR: ${FATOR:-20}
    POLITICA: ${POLITICA:-mais_proxima}
    N_AMBULANCIAS: ${N_AMBULANCIAS:-50}
    CHAMADOS_POR_DIA: ${CHAMADOS_POR_DIA:-300}
    SEED: ${SEED:-42}
    RODADA_ID: ${RODADA_ID:-local}
  volumes:
    - ./logs:/logs
  depends_on:
    bootstrap:
      condition: service_completed_successfully

services:
  localstack:
    image: localstack/localstack:3
    ports: ["4566:4566"]
    environment:
      - SERVICES=sqs,dynamodb
      - EAGER_SERVICE_LOADING=1
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:4566/_localstack/health"]
      interval: 5s
      timeout: 3s
      retries: 20

  bootstrap:
    build: .
    environment: *env
    command: python -m samu_sim.infra.bootstrap
    depends_on:
      localstack:
        condition: service_healthy

  gerador:
    <<: *servico
    command: python -m samu_sim.gerador

  despachante:
    <<: *servico
    command: python -m samu_sim.despachante
    deploy:
      replicas: 2

  ambulancia-w0:
    <<: *servico
    command: python -m samu_sim.ambulancia
    environment:
      <<: *env
      WORKER_ID: w0

  ambulancia-w1:
    <<: *servico
    command: python -m samu_sim.ambulancia
    environment:
      <<: *env
      WORKER_ID: w1

  api:
    <<: *servico
    command: python -m samu_sim.api
    ports: ["8000:8000"]
```

- [ ] **Step 3: Subir tudo e verificar**

```bash
rm -rf logs && FATOR=60 docker compose up --build -d
sleep 90
curl -s localhost:8000/metricas | .venv/Scripts/python -m json.tool | head -30
docker compose ps
```
Esperado: `atendidos > 0`, 2 réplicas de `despachante` rodando, `logs/local/` com 6 JSONL (gerador, 2 despachantes com hostname, ambulancia-w0/w1, api).

- [ ] **Step 4: Teste de caos — matar um worker**

```bash
curl -s -X POST localhost:8000/controle -H 'content-type: application/json' -d '{"fator": 200}'
sleep 20
docker compose kill ambulancia-w1
sleep 150      # > reaper_timeout (120 s) + intervalo (60 s) no pior caso
grep -c reaper_liberou logs/local/api.jsonl
docker compose start ambulancia-w1
```
Esperado: `reaper_liberou` ≥ 1; após restart, o w1 volta a atender (novos `chegou` em `ambulancia-w1.jsonl`).

- [ ] **Step 5: Teste de caos — duplicar mensagem / matar despachante**

```bash
docker compose kill despachante   # mata as 2 réplicas
sleep 5; docker compose start despachante
sleep 60
grep -c chamado_ja_despachado logs/local/despachante-*.jsonl
grep -c despachada logs/local/despachante-*.jsonl
```
Esperado: nenhum `despachada` duplicado por `chamado_id` (verificar com `analisar_rodada.py` na Task 10, que checa isso).

- [ ] **Step 6: Derrubar e commitar**

```bash
docker compose down -v
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "feat: docker compose com LocalStack e os 4 servicos em containers

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: `scripts/analisar_rodada.py`

**Files:**
- Create: `scripts/__init__.py` (vazio), `scripts/analisar_rodada.py`
- Test: `tests/test_analisar_rodada.py`

**Interfaces:**
- Produces: `carregar_eventos(pasta: Path) -> list[dict]` (todos os JSONL da pasta, ordenados por `ts_sim`); `analisar(eventos: list[dict]) -> dict` com `{"resposta": {p50, p90, media, n}, "por_zona": {zona: {p50, p90, n}}, "espera_despacho": {p50, p90}, "contagens": {tipo: n}, "despachos_duplicados": [chamado_id...], "chamados_criados", "chamados_atendidos"}`; `main()` — `python scripts/analisar_rodada.py logs/local [--json]` imprime tabela ou JSON.

- [ ] **Step 1: Escrever `tests/test_analisar_rodada.py`**

```python
import json
from scripts.analisar_rodada import analisar, carregar_eventos


def ev(tipo, ts, **k):
    return {"ts_sim": ts, "ts_real": 0, "rodada_id": "r", "servico": "s", "tipo": tipo, **k}


def test_analisar_calcula_metricas_e_detecta_duplicatas():
    eventos = [
        ev("chamado_criado", 0, chamado_id="a", zona="Sul"),
        ev("chamado_criado", 0, chamado_id="b", zona="Oeste"),
        ev("despachada", 10, chamado_id="a", ambulancia_id="1", espera_seg=10),
        ev("despachada", 20, chamado_id="b", ambulancia_id="2", espera_seg=20),
        ev("despachada", 25, chamado_id="b", ambulancia_id="3", espera_seg=25),   # duplicata!
        ev("chegou", 300, chamado_id="a", zona="Sul", resposta_seg=300),
        ev("chegou", 900, chamado_id="b", zona="Oeste", resposta_seg=900),
        ev("reaper_liberou", 950, ambulancia_id="9"),
    ]
    r = analisar(eventos)
    assert r["resposta"]["n"] == 2 and r["resposta"]["p50"] == 600
    assert r["por_zona"]["Oeste"]["p90"] == 900
    assert r["espera_despacho"]["p50"] == 20
    assert r["contagens"]["reaper_liberou"] == 1
    assert r["despachos_duplicados"] == ["b"]
    assert r["chamados_criados"] == 2 and r["chamados_atendidos"] == 2


def test_carregar_eventos_ordena_por_ts_sim(tmp_path):
    (tmp_path / "a.jsonl").write_text(json.dumps(ev("x", 5)) + "\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(json.dumps(ev("y", 1)) + "\n\n", encoding="utf-8")
    assert [e["tipo"] for e in carregar_eventos(tmp_path)] == ["y", "x"]
```

- [ ] **Step 2: Rodar e ver falhar** → `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `scripts/analisar_rodada.py`** (e `scripts/__init__.py` vazio)

```python
"""Metricas de uma rodada a partir do event log JSONL.
Uso: python scripts/analisar_rodada.py logs/local [--json]"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.core.metricas import percentil  # noqa: E402


def carregar_eventos(pasta: Path) -> list[dict]:
    eventos = []
    for arquivo in sorted(Path(pasta).glob("*.jsonl")):
        with open(arquivo, encoding="utf-8") as f:
            eventos.extend(json.loads(l) for l in f if l.strip())
    eventos.sort(key=lambda e: e["ts_sim"])
    return eventos


def _resumo(v):
    return {"p50": percentil(v, 50), "p90": percentil(v, 90),
            "media": sum(v) / len(v) if v else None, "n": len(v)}


def analisar(eventos: list[dict]) -> dict:
    contagens = Counter(e["tipo"] for e in eventos)
    respostas, esperas = [], []
    por_zona = defaultdict(list)
    despachos = Counter()
    for e in eventos:
        t = e["tipo"]
        if t == "chegou":
            respostas.append(e["resposta_seg"])
            por_zona[e.get("zona", "?")].append(e["resposta_seg"])
        elif t == "despachada":
            esperas.append(e["espera_seg"])
            despachos[e["chamado_id"]] += 1
    return {
        "resposta": _resumo(respostas),
        "por_zona": {z: {k: v for k, v in _resumo(vs).items() if k != "media"}
                     for z, vs in sorted(por_zona.items())},
        "espera_despacho": {"p50": percentil(esperas, 50), "p90": percentil(esperas, 90)},
        "contagens": dict(contagens),
        "despachos_duplicados": sorted(c for c, n in despachos.items() if n > 1),
        "chamados_criados": contagens.get("chamado_criado", 0),
        "chamados_atendidos": contagens.get("chegou", 0),
    }


def _min(s):
    return "-" if s is None else f"{s / 60:6.1f} min"


def imprimir(r: dict) -> None:
    print(f"chamados criados: {r['chamados_criados']}   atendidos: {r['chamados_atendidos']}")
    print(f"resposta  P50 {_min(r['resposta']['p50'])}   P90 {_min(r['resposta']['p90'])}   n={r['resposta']['n']}")
    print(f"espera despacho  P50 {_min(r['espera_despacho']['p50'])}   P90 {_min(r['espera_despacho']['p90'])}")
    print("por zona:")
    for z, m in r["por_zona"].items():
        print(f"  {z:8s} P50 {_min(m['p50'])}  P90 {_min(m['p90'])}  n={m['n']}")
    print("eventos:", ", ".join(f"{k}={v}" for k, v in sorted(r["contagens"].items())))
    if r["despachos_duplicados"]:
        print("ATENCAO despachos duplicados:", r["despachos_duplicados"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("pasta", help="pasta com os JSONL da rodada, ex.: logs/local")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    r = analisar(carregar_eventos(Path(a.pasta)))
    print(json.dumps(r, indent=2, ensure_ascii=False)) if a.json else imprimir(r)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar** `tests/test_analisar_rodada.py` → `2 passed`; suíte inteira verde.

- [ ] **Step 5: Commit**

```bash
git add scripts tests/test_analisar_rodada.py
git commit -m "feat: analisar_rodada calcula metricas e detecta despachos duplicados a partir do event log

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: README do D2

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Substituir a seção "Rodar" e marcar D2 no "Estado"**

Adicionar após a seção do D1:

```markdown
## Rodar em containers (D2 — SQS + DynamoDB via LocalStack)

```bash
FATOR=60 docker compose up --build -d      # localstack, bootstrap, gerador, 2 despachantes, 2 workers, api
curl localhost:8000/metricas               # P50/P90 ao vivo + tamanho da fila
curl -X POST localhost:8000/controle -H 'content-type: application/json' -d '{"fator": 200}'
curl -X POST localhost:8000/controle -H 'content-type: application/json' -d '{"pausada": true}'
python scripts/analisar_rodada.py logs/local   # métricas a partir do event log
docker compose down -v
```

Variáveis: `FATOR`, `POLITICA`, `N_AMBULANCIAS`, `CHAMADOS_POR_DIA`, `SEED`, `RODADA_ID`.

### Testes de caos

| Falha | Como provocar | O que observar |
|---|---|---|
| Worker morre | `docker compose kill ambulancia-w1` | após ~2–3 min, `reaper_liberou` em `logs/local/api.jsonl`; chamado volta pra fila |
| Despachante morre com msg em mãos | `docker compose kill despachante && docker compose start despachante` | `chamado_ja_despachado` nos logs; `analisar_rodada.py` sem `despachos_duplicados` |
| Corrida entre despachantes | 2 réplicas + `FATOR=200` | `reserva_falhou` > 0 nos logs, nunca 2 `despachada` pro mesmo chamado |

### Testes de integração (exigem LocalStack)

```bash
docker compose up -d localstack
AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test python -m pytest -q -m integration
```
```

E no "Estado", marcar `- [x] D2`.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README do D2 (containers, controle, caos)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

- **Cobertura do spec (parte D2):** `FilaSQS`/`RepositorioDynamo` com condicionais (§3.2, ADR 2, ADR 10) → Task 5; uma fila por worker (ADR 8) → Tasks 5–6; tabela `rodada` com checkpoint e releitura a cada 10 s (§4.1, §5.3) → Tasks 2, 7; `POST /controle` (fator, pausa, política) (§3.2) → Task 8; heartbeat 30 s + reaper 60 s / 120 s (§3.2, §6) → Tasks 3–4, 8; `GET /estado` e `/metricas` com idade da fila (§3.2, §7) → Task 8; logs JSON estruturados (§7) → Task 7; event log JSONL por serviço/rodada em volume (§4.3) → Tasks 7, 9; `analisar_rodada.py` (§7) → Task 10; testes de contrato `@integration` (§8) → Tasks 5–6; docker compose com 4 serviços + LocalStack (§3) → Task 9; testes de caos documentados (§6) → Tasks 9, 11. Fica para D4: `/ws/estado` e o mapa; para D3: OSRM/matriz/`menor_eta_cobertura`.
- **Placeholders:** nenhum.
- **Consistência:** `Repositorio.listar_ambulancias(status, worker_id)`, `atualizar_heartbeat(id, ts)`, `liberar_ambulancia(id, versao, lat, lon)` usados igual em Tasks 2–5, 8; `Relogio.sincronizar(inicio_real, inicio_sim, fator)` em Tasks 2, 7, 8; `criar_recursos/apagar_recursos/semear` em Tasks 5–6; `Config.fila_eventos/tabela` em Tasks 1, 5–7; `montar_frota` importado de `samu_sim.local` na Task 6.

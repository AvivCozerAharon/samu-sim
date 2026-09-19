# D9 — Cenários com intervalo de confiança + Experimento D (onde abrir a próxima base)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** transformar o simulador de "demo" em "instrumento": qualquer comparação entre dois cenários sai com intervalo de confiança, e o sistema responde à pergunta que a prefeitura faz de verdade — onde abrir a próxima base do SAMU.

**Architecture:** (1) `samu_sim/estatistica.py` faz bootstrap sobre as métricas por seed (IC da média e IC da diferença **pareada por seed** — mesmas seeds nos dois cenários = variância menor). (2) `samu_sim/cenarios.py` descreve um cenário (frota, política, alocação, bases extras, trânsito, reposicionamento), roda N seeds via `local.rodar` e compara dois cenários; `GerenciadorCenarios` enfileira jobs numa thread e a API expõe `POST/GET /cenarios`. (3) `samu_sim/expansao.py` gera candidatas a base nova (centróides de bairros a > 5 km de qualquer base, ordenados por demanda descoberta), e `scripts/experimento_d.py` faz triagem barata (1 seed, 12 h) e confirma as melhores com IC. Saída: JSON + mapa de calor + seção no README + seção "Cenários" no console.

**Tech Stack:** Python 3.12, `random`/`statistics` (bootstrap sem numpy), FastAPI, matplotlib, pytest.

**Spec:** conversa de 2026-09-19 (itens 1 e 2 da lista "o que evoluir"); design em `docs/superpowers/specs/2026-09-18-samu-sim-design.md` continua valendo.

## Global Constraints

- Sem dependências novas (bootstrap em Python puro).
- Tudo determinístico por seed (`random.Random(seed)`), inclusive o bootstrap.
- `local.rodar` continua compatível: `bases_extra` é opcional e default `None`.
- Tempo: uma rodada 24 h em memória a fator 2000 ≈ 45 s; o experimento D tem modo `--rapido` e triagem em dois estágios para caber em < 40 min.
- Commits pequenos em PT, suíte verde antes de cada commit (`.venv/Scripts/python -m pytest -q -m "not integration"`).

---

### Task 1: Estatística — IC bootstrap e diferença pareada

**Files:**
- Create: `samu_sim/estatistica.py`
- Test: `tests/test_estatistica.py`

**Interfaces:**
- Produces: `ic_bootstrap(valores: list[float], nivel=0.95, n_reamostras=2000, seed=0) -> dict` com `media, baixo, alto, n`; `diferenca_pareada(a: list[float], b: list[float], ...) -> dict` com `media, baixo, alto, n, significativo` (IC de `b - a` não contém 0).

- [ ] **Step 1: teste**

```python
# tests/test_estatistica.py
import pytest
from samu_sim.estatistica import diferenca_pareada, ic_bootstrap


def test_ic_bootstrap_contem_media_e_estreita_com_mais_dados():
    r = ic_bootstrap([10, 12, 11, 13, 9, 10, 12, 11], seed=1)
    assert r["baixo"] <= r["media"] <= r["alto"]
    assert r["n"] == 8
    largo = ic_bootstrap([10, 14], seed=1)
    assert (largo["alto"] - largo["baixo"]) > (r["alto"] - r["baixo"])


def test_ic_bootstrap_vazio_e_um_valor():
    assert ic_bootstrap([])["media"] is None
    r = ic_bootstrap([5.0])
    assert r["media"] == r["baixo"] == r["alto"] == 5.0


def test_ic_bootstrap_ignora_none():
    assert ic_bootstrap([1, None, 3])["n"] == 2


def test_diferenca_pareada_detecta_ganho_consistente():
    a = [100, 110, 105, 120, 98, 107]
    b = [x - 8 for x in a]          # sempre 8 melhor
    r = diferenca_pareada(a, b, seed=1)
    assert r["media"] == pytest.approx(-8)
    assert r["significativo"] is True and r["alto"] < 0


def test_diferenca_pareada_ruido_nao_significativo():
    a = [100, 110, 105, 120, 98, 107]
    b = [101, 108, 106, 119, 99, 106]
    r = diferenca_pareada(a, b, seed=1)
    assert r["significativo"] is False


def test_diferenca_pareada_exige_mesmo_tamanho():
    with pytest.raises(ValueError):
        diferenca_pareada([1, 2], [1])
```

- [ ] **Step 2: rodar, ver falhar** — `pytest tests/test_estatistica.py -q` → ModuleNotFoundError.

- [ ] **Step 3: implementar**

```python
# samu_sim/estatistica.py
"""Intervalos de confianca por bootstrap (Python puro, deterministico por seed).

Bootstrap percentil sobre a media: reamostra os valores com reposicao n_reamostras vezes e
toma os percentis (1-nivel)/2 e 1-(1-nivel)/2 das medias. Com poucos valores (seeds) o IC e
largo - e isso e informacao, nao defeito.

`diferenca_pareada` compara dois cenarios rodados com AS MESMAS seeds (common random numbers):
a diferenca por seed cancela a variancia comum ao gerador de chamados, entao o IC fica bem mais
estreito do que comparar duas medias independentes.
"""
import random
import statistics


def _limpar(valores) -> list[float]:
    return [float(v) for v in valores if v is not None]


def ic_bootstrap(valores, nivel: float = 0.95, n_reamostras: int = 2000, seed: int = 0) -> dict:
    v = _limpar(valores)
    if not v:
        return {"media": None, "baixo": None, "alto": None, "n": 0}
    if len(v) == 1:
        return {"media": v[0], "baixo": v[0], "alto": v[0], "n": 1}
    rng = random.Random(seed)
    n = len(v)
    medias = sorted(statistics.fmean(rng.choices(v, k=n)) for _ in range(n_reamostras))
    alfa = (1 - nivel) / 2
    return {"media": statistics.fmean(v), "baixo": medias[int(alfa * n_reamostras)],
            "alto": medias[min(n_reamostras - 1, int((1 - alfa) * n_reamostras))], "n": n}


def diferenca_pareada(a, b, nivel: float = 0.95, n_reamostras: int = 2000, seed: int = 0) -> dict:
    """IC de (b - a) pareado por posicao (mesma seed). Pares com None sao descartados."""
    if len(a) != len(b):
        raise ValueError(f"listas de tamanhos diferentes: {len(a)} e {len(b)}")
    difs = [float(y) - float(x) for x, y in zip(a, b) if x is not None and y is not None]
    r = ic_bootstrap(difs, nivel, n_reamostras, seed)
    r["significativo"] = bool(r["n"] >= 2 and (r["alto"] < 0 or r["baixo"] > 0))
    return r
```

- [ ] **Step 4: rodar, ver passar.**
- [ ] **Step 5: commit** — `git add samu_sim/estatistica.py tests/test_estatistica.py && git commit -m "feat(d9): IC bootstrap e diferenca pareada por seed"`

---

### Task 2: `local.rodar` aceita bases extras

**Files:**
- Modify: `samu_sim/local.py` (assinatura de `rodar`, carregamento de bases)
- Test: `tests/test_integracao_local.py`

**Interfaces:**
- Produces: `rodar(..., bases_extra: list[Base] | None = None)`; as bases extras entram em `bases` antes de `montar_frota` (então uma `alocacao` pode referenciá-las) e aparecem no snapshot/estado.

- [ ] **Step 1: teste**

```python
def test_rodar_com_base_extra_recebe_ambulancias():
    from samu_sim.core.modelos import Base
    from samu_sim.gerador.demanda import carregar_bases
    nova = Base("cand-teste", "Candidata teste", -22.90, -43.60, "candidata")
    aloc = {b.id: 0 for b in carregar_bases("dados/bases.csv")}
    aloc[nova.id] = 2
    r = local.rodar(fator=5000, duracao_sim_seg=600, n_ambulancias=2, roteador="haversine",
                    seed=1, chamados_por_dia=50, visibilidade_seg=0.2, alocacao=aloc, bases_extra=[nova])
    assert all(a["base_id"] == "cand-teste" for a in r["ambulancias"])
```

(zeros na alocação são válidos: `montar_frota` só exige soma = n.)

- [ ] **Step 2: rodar, ver falhar** (TypeError: bases_extra).
- [ ] **Step 3: implementar** — em `rodar`: parâmetro `bases_extra: list[Base] | None = None`; após `bases = carregar_bases(...)`: `bases = bases + list(bases_extra or [])`; em `"rodada"` do retorno acrescentar `"bases_extra": [b.id for b in (bases_extra or [])]`. Import `Base` já existe em `local.py`? Conferir; senão `from samu_sim.core.modelos import Base`.
- [ ] **Step 4: rodar, passar.**
- [ ] **Step 5: commit** — `feat(d9): local.rodar aceita bases extras`

---

### Task 3: Cenários — descrição, execução por seeds, comparação pareada

**Files:**
- Create: `samu_sim/cenarios.py`
- Test: `tests/test_cenarios.py`

**Interfaces:**
- Consumes: `ic_bootstrap`, `diferenca_pareada` (Task 1); `local.rodar` (Task 2) via callable injetado.
- Produces:
  - `Cenario(nome, n_ambulancias=73, politica="menor_eta", alocacao=None, bases_extra=(), transito=False, reposicionamento=False)` dataclass frozen, `.para_dict()`, `Cenario.de_dict(d)`.
  - `METRICAS = ("p90", "p50", "p90_vermelho", "pendentes", "Centro", "Sul", "Norte", "Barra", "Oeste")` (zonas = P90 da zona).
  - `extrair(resultado_rodar: dict) -> dict[str, float|None]` (uma linha por seed).
  - `executar(cenario, seeds, duracao_sim_seg, fator, rodar_fn, chamados_por_dia=600) -> dict` = `{"cenario", "seeds", "por_seed": [linha...], "resumo": {metrica: ic_bootstrap}}`.
  - `comparar(base: dict, alt: dict) -> dict[str, dict]` diferenças pareadas por métrica (exige mesmas seeds).
  - `GerenciadorCenarios(executar_fn)` com `submeter(cenario, seeds, duracao, fator) -> id`, `listar()`, `obter(id)`; roda numa `threading.Thread` única (fila FIFO); status `na_fila | rodando | concluido | erro`.

- [ ] **Step 1: testes (com rodar_fn fake, sem simulação real)**

```python
# tests/test_cenarios.py
import time

from samu_sim.cenarios import Cenario, GerenciadorCenarios, comparar, executar, extrair


def fake_rodar(**kw):
    seed, n = kw["seed"], kw["n_ambulancias"]
    p90 = 1200 - 10 * n + seed          # mais frota = melhor, seed = ruido
    return {"metricas": {"total": 100, "atendidos": 95, "pendentes": 5 if n < 80 else 0,
                         "resposta": {"p50": p90 / 2, "p90": p90, "media": p90 / 1.5},
                         "por_zona": {"Oeste": {"p90": p90 + 100}},
                         "por_prioridade": {"vermelho": {"p90": p90 - 50}},
                         "espera_despacho": {"p90": 30}},
            "eventos": {}, "ambulancias": [], "alocacao": {}}


def test_extrair_linha_por_seed():
    linha = extrair(fake_rodar(seed=1, n_ambulancias=73))
    assert linha["p90"] == 471 and linha["Oeste"] == 571 and linha["Barra"] is None
    assert linha["pendentes"] == 5


def test_executar_resume_com_ic():
    r = executar(Cenario("base"), [1, 2, 3], 3600, 100, fake_rodar)
    assert r["seeds"] == [1, 2, 3] and len(r["por_seed"]) == 3
    assert r["resumo"]["p90"]["n"] == 3
    assert r["resumo"]["p90"]["baixo"] <= r["resumo"]["p90"]["media"] <= r["resumo"]["p90"]["alto"]
    assert r["cenario"]["nome"] == "base"


def test_comparar_pareado_detecta_ganho_de_frota():
    a = executar(Cenario("73"), [1, 2, 3, 4], 3600, 100, fake_rodar)
    b = executar(Cenario("80", n_ambulancias=80), [1, 2, 3, 4], 3600, 100, fake_rodar)
    d = comparar(a, b)
    assert d["p90"]["media"] == -70 and d["p90"]["significativo"] is True
    assert d["pendentes"]["media"] == -5


def test_comparar_exige_mesmas_seeds():
    import pytest
    a = executar(Cenario("a"), [1, 2], 3600, 100, fake_rodar)
    b = executar(Cenario("b"), [1, 3], 3600, 100, fake_rodar)
    with pytest.raises(ValueError):
        comparar(a, b)


def test_cenario_serializa_ida_e_volta():
    c = Cenario("x", n_ambulancias=75, alocacao={"b1": 75}, bases_extra=({"id": "cand-1", "nome": "C", "lat": -22.9, "lon": -43.6},))
    assert Cenario.de_dict(c.para_dict()) == c


def test_gerenciador_roda_em_ordem_e_expoe_status():
    g = GerenciadorCenarios(lambda c, seeds, dur, fator: executar(c, seeds, dur, fator, fake_rodar))
    i1 = g.submeter(Cenario("um"), [1, 2], 3600, 100)
    i2 = g.submeter(Cenario("dois", n_ambulancias=80), [1, 2], 3600, 100)
    for _ in range(100):
        if all(g.obter(i)["status"] == "concluido" for i in (i1, i2)):
            break
        time.sleep(0.02)
    assert g.obter(i1)["resultado"]["resumo"]["p90"]["media"] > g.obter(i2)["resultado"]["resumo"]["p90"]["media"]
    assert [j["id"] for j in g.listar()] == [i1, i2]
    g.encerrar()


def test_gerenciador_registra_erro():
    def explode(*a):
        raise RuntimeError("boom")
    g = GerenciadorCenarios(explode)
    i = g.submeter(Cenario("x"), [1], 10, 1)
    for _ in range(100):
        if g.obter(i)["status"] == "erro":
            break
        time.sleep(0.02)
    assert "boom" in g.obter(i)["erro"]
    g.encerrar()
```

- [ ] **Step 2: rodar, ver falhar.**
- [ ] **Step 3: implementar**

```python
# samu_sim/cenarios.py
"""Cenarios comparaveis: a mesma pergunta ("e se...?") rodada com N seeds e resumida com IC.

Um cenario descreve a frota, a politica, a alocacao por base, bases extras (candidatas do
experimento D) e as chaves de realismo. `executar` roda uma vez por seed e devolve as
metricas por seed + IC bootstrap; `comparar` faz a diferenca pareada por seed entre dois
cenarios (por isso exige as mesmas seeds). `GerenciadorCenarios` e a fila de jobs da API.
"""
import queue
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field

from samu_sim.core.modelos import Base
from samu_sim.estatistica import diferenca_pareada, ic_bootstrap

ZONAS = ("Centro", "Sul", "Norte", "Barra", "Oeste")
METRICAS = ("p90", "p50", "p90_vermelho", "pendentes") + ZONAS


@dataclass(frozen=True)
class Cenario:
    nome: str
    n_ambulancias: int = 73
    politica: str = "menor_eta"
    alocacao: dict | None = None
    bases_extra: tuple = ()          # tuplas de dicts {id, nome, lat, lon}
    transito: bool = False
    reposicionamento: bool = False

    def para_dict(self) -> dict:
        d = asdict(self)
        d["bases_extra"] = [dict(b) for b in self.bases_extra]
        return d

    @classmethod
    def de_dict(cls, d: dict) -> "Cenario":
        d = dict(d)
        d["bases_extra"] = tuple(dict(b) for b in d.get("bases_extra") or ())
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def objetos_bases_extra(self) -> list[Base]:
        return [Base(b["id"], b["nome"], float(b["lat"]), float(b["lon"]), "candidata") for b in self.bases_extra]


def extrair(r: dict) -> dict:
    m = r["metricas"]
    linha = {"p90": m["resposta"]["p90"], "p50": m["resposta"]["p50"], "pendentes": m["pendentes"],
             "p90_vermelho": (m.get("por_prioridade", {}).get("vermelho") or {}).get("p90"),
             "atendidos": m["atendidos"], "total": m["total"]}
    for z in ZONAS:
        linha[z] = (m.get("por_zona", {}).get(z) or {}).get("p90")
    return linha


def executar(cenario: Cenario, seeds: list[int], duracao_sim_seg: float, fator: float, rodar_fn,
             chamados_por_dia: int = 600, roteador: str = "matriz") -> dict:
    inicio = time.time()
    por_seed = []
    for s in seeds:
        r = rodar_fn(fator=fator, duracao_sim_seg=duracao_sim_seg, n_ambulancias=cenario.n_ambulancias,
                     politica=cenario.politica, roteador=roteador, seed=s, chamados_por_dia=chamados_por_dia,
                     visibilidade_seg=0.2, alocacao=cenario.alocacao, bases_extra=cenario.objetos_bases_extra(),
                     transito=cenario.transito, reposicionamento=cenario.reposicionamento)
        por_seed.append({"seed": s, **extrair(r)})
    resumo = {k: ic_bootstrap([l[k] for l in por_seed]) for k in METRICAS}
    return {"cenario": cenario.para_dict(), "seeds": list(seeds), "duracao_sim_seg": duracao_sim_seg,
            "chamados_por_dia": chamados_por_dia, "por_seed": por_seed, "resumo": resumo,
            "tempo_real_seg": round(time.time() - inicio, 1)}


def comparar(base: dict, alt: dict) -> dict:
    if base["seeds"] != alt["seeds"]:
        raise ValueError(f"seeds diferentes: {base['seeds']} vs {alt['seeds']}")
    return {k: diferenca_pareada([l[k] for l in base["por_seed"]], [l[k] for l in alt["por_seed"]])
            for k in METRICAS}


class GerenciadorCenarios:
    """Fila FIFO de cenarios rodando numa unica thread (uma simulacao em memoria por vez)."""

    def __init__(self, executar_fn):
        self._executar = executar_fn            # (cenario, seeds, duracao, fator) -> resultado
        self._jobs: dict[str, dict] = {}
        self._ordem: list[str] = []
        self._fila: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submeter(self, cenario: Cenario, seeds: list[int], duracao_sim_seg: float, fator: float) -> str:
        jid = uuid.uuid4().hex[:8]
        with self._lock:
            self._jobs[jid] = {"id": jid, "status": "na_fila", "cenario": cenario.para_dict(), "seeds": list(seeds),
                               "duracao_sim_seg": duracao_sim_seg, "fator": fator, "criado_em": time.time(),
                               "resultado": None, "erro": None}
            self._ordem.append(jid)
        self._fila.put((jid, cenario, list(seeds), duracao_sim_seg, fator))
        return jid

    def obter(self, jid: str) -> dict | None:
        with self._lock:
            return dict(self._jobs[jid]) if jid in self._jobs else None

    def listar(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in self._jobs[j].items() if k != "resultado"} for j in self._ordem]

    def encerrar(self) -> None:
        self._fila.put(None)

    def _loop(self) -> None:
        while True:
            item = self._fila.get()
            if item is None:
                return
            jid, cenario, seeds, dur, fator = item
            with self._lock:
                self._jobs[jid]["status"] = "rodando"
            try:
                res = self._executar(cenario, seeds, dur, fator)
                with self._lock:
                    self._jobs[jid].update(status="concluido", resultado=res)
            except Exception as e:  # noqa: BLE001 - o job registra qualquer falha
                with self._lock:
                    self._jobs[jid].update(status="erro", erro=f"{e}\n{traceback.format_exc()}")
```

- [ ] **Step 4: rodar, passar.**
- [ ] **Step 5: commit** — `feat(d9): cenarios com IC e comparacao pareada por seed`

---

### Task 4: API `POST /cenarios`, `GET /cenarios`, `GET /cenarios/{id}`, `GET /cenarios/{a}/comparar/{b}`

**Files:**
- Modify: `samu_sim/api/__init__.py` (`criar_app(..., gerenciador_cenarios=None)`), `samu_sim/api/__main__.py` (cria o gerenciador com `local.rodar` + roteador matriz), `scripts/dev_api.py` (idem).
- Test: `tests/test_api.py`

**Interfaces:**
- `POST /cenarios` body: `{"cenario": {...Cenario}, "seeds": [..] (default [42,7,2024]), "duracao_sim_seg": 86400, "fator": 2000}` → `{"id"}` 202. Limites: até 20 seeds, duração ≤ 7 dias; sem gerenciador → 503.
- `GET /cenarios` → lista sem resultado; `GET /cenarios/{id}` → job completo (404 se não existe).
- `GET /cenarios/{a}/comparar/{b}` → `comparar(resA, resB)` (409 se algum não concluído).

- [ ] **Step 1: teste** (em `tests/test_api.py`, seguindo o padrão de fixture do arquivo — conferir como `criar_app` é montado lá):

```python
def test_cenarios_fluxo(app_cliente_factory):  # adaptar ao fixture existente
    from samu_sim.cenarios import GerenciadorCenarios, executar
    from tests.test_cenarios import fake_rodar
    g = GerenciadorCenarios(lambda c, s, d, f: executar(c, s, d, f, fake_rodar))
    cli = app_cliente_factory(gerenciador_cenarios=g)
    r1 = cli.post("/cenarios", json={"cenario": {"nome": "73"}, "seeds": [1, 2]})
    r2 = cli.post("/cenarios", json={"cenario": {"nome": "80", "n_ambulancias": 80}, "seeds": [1, 2]})
    assert r1.status_code == 202
    a, b = r1.json()["id"], r2.json()["id"]
    import time
    for _ in range(100):
        if cli.get(f"/cenarios/{b}").json()["status"] == "concluido":
            break
        time.sleep(0.02)
    assert cli.get("/cenarios").json()[0]["id"] == a
    d = cli.get(f"/cenarios/{a}/comparar/{b}").json()
    assert d["p90"]["media"] == -70
    assert cli.get("/cenarios/nao-existe").status_code == 404
    g.encerrar()


def test_cenarios_sem_gerenciador_503(cliente):
    assert cliente.post("/cenarios", json={"cenario": {"nome": "x"}}).status_code == 503
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar** nos handlers da API:

```python
    @app.post("/cenarios", status_code=202)
    def submeter_cenario(corpo: dict):
        if gerenciador_cenarios is None:
            raise HTTPException(503, "cenarios desligados nesta instancia")
        try:
            c = Cenario.de_dict(corpo.get("cenario") or {})
        except TypeError as e:
            raise HTTPException(422, str(e))
        seeds = [int(s) for s in (corpo.get("seeds") or [42, 7, 2024])][:20]
        dur = min(float(corpo.get("duracao_sim_seg") or 86400), 7 * 86400)
        fator = float(corpo.get("fator") or 2000)
        return {"id": gerenciador_cenarios.submeter(c, seeds, dur, fator)}

    @app.get("/cenarios")
    def listar_cenarios():
        return gerenciador_cenarios.listar() if gerenciador_cenarios else []

    @app.get("/cenarios/{jid}")
    def obter_cenario(jid: str):
        j = gerenciador_cenarios.obter(jid) if gerenciador_cenarios else None
        if j is None:
            raise HTTPException(404, "cenario nao encontrado")
        return j

    @app.get("/cenarios/{a}/comparar/{b}")
    def comparar_cenarios(a: str, b: str):
        ja, jb = (gerenciador_cenarios.obter(a), gerenciador_cenarios.obter(b)) if gerenciador_cenarios else (None, None)
        if ja is None or jb is None:
            raise HTTPException(404, "cenario nao encontrado")
        if ja["status"] != "concluido" or jb["status"] != "concluido":
            raise HTTPException(409, "os dois cenarios precisam estar concluidos")
        try:
            return comparar(ja["resultado"], jb["resultado"])
        except ValueError as e:
            raise HTTPException(409, str(e))
```

Em `api/__main__.py` e `scripts/dev_api.py`:

```python
from samu_sim import local as runner
from samu_sim.cenarios import GerenciadorCenarios, executar
gerenciador = GerenciadorCenarios(lambda c, s, d, f: executar(c, s, d, f, runner.rodar))
```

(a API já importa `local`? Se não, o import é seguro — `local` só monta objetos em `rodar`). Nota: `runner.INTERVALO_OCIOSO_REAL = 0.005` para os jobs não dormirem 20 ms por polling.

- [ ] **Step 4: passar.**
- [ ] **Step 5: commit** — `feat(d9): endpoints /cenarios com fila de jobs`

---

### Task 5: Expansão — candidatas a base nova

**Files:**
- Create: `samu_sim/expansao.py`
- Test: `tests/test_expansao.py`

**Interfaces:**
- `demanda_descoberta(bairro, bases, raio_km) -> float` = `bairro.peso` se nenhum base a ≤ raio, senão 0.
- `candidatas(bairros, bases, raio_km=5.0, max_n=12) -> list[dict]` ordenadas por demanda descoberta desc: `{"id": "cand-<slug>", "nome": "Nova base — <bairro>", "lat", "lon", "zona", "bairro", "dist_base_mais_proxima_km", "demanda_descoberta"}`; só bairros com `demanda_descoberta > 0`. Slug: minúsculas, sem acento, espaços → `-`.
- `cenario_candidata(cand: dict, alocacao_base: dict, extra: int = 2, **flags) -> Cenario` = alocação atual + `extra` na candidata, `n_ambulancias = soma`.

- [ ] **Step 1: teste**

```python
# tests/test_expansao.py
from samu_sim.cenarios import Cenario
from samu_sim.core.modelos import Base
from samu_sim.expansao import candidatas, cenario_candidata, demanda_descoberta
from samu_sim.gerador.demanda import Bairro, carregar_bairros, carregar_bases

B = Base("b1", "Base 1", -22.90, -43.20)


def test_demanda_descoberta_zero_quando_coberto():
    perto = Bairro("Perto", "Centro", -22.905, -43.205, 10000, 1.0)
    longe = Bairro("Longe", "Oeste", -22.90, -43.60, 10000, 1.0)
    assert demanda_descoberta(perto, [B], 5.0) == 0
    assert demanda_descoberta(longe, [B], 5.0) == longe.peso


def test_candidatas_ordenadas_e_com_slug():
    bairros = [Bairro("Santa Cruz", "Oeste", -22.92, -43.68, 200000, 1.0),
               Bairro("Guaratiba", "Oeste", -23.00, -43.60, 50000, 1.0),
               Bairro("Centro", "Centro", -22.905, -43.205, 40000, 9.5)]
    c = candidatas(bairros, [B], raio_km=5.0, max_n=5)
    assert [x["bairro"] for x in c] == ["Santa Cruz", "Guaratiba"]
    assert c[0]["id"] == "cand-santa-cruz" and c[0]["dist_base_mais_proxima_km"] > 40


def test_candidatas_com_dados_reais_tem_barra_ou_oeste():
    c = candidatas(carregar_bairros("dados/bairros.csv"), carregar_bases("dados/bases.csv"))
    assert 1 <= len(c) <= 12
    assert any(x["zona"] in ("Barra", "Oeste") for x in c)


def test_cenario_candidata_soma_frota():
    cand = {"id": "cand-x", "nome": "Nova base — X", "lat": -22.9, "lon": -43.6}
    c = cenario_candidata(cand, {"b1": 70, "b2": 3}, extra=2)
    assert isinstance(c, Cenario) and c.n_ambulancias == 75
    assert c.alocacao["cand-x"] == 2 and c.bases_extra[0]["id"] == "cand-x"
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar**

```python
# samu_sim/expansao.py
"""Experimento D: onde abrir a proxima base.

Heuristica barata primeiro (demanda populacional descoberta a > raio_km de qualquer base) para
escolher poucas candidatas; a simulacao cara (cenarios com IC) confirma qual delas reduz mais
o P90. Cada candidata vira um Cenario: alocacao atual + `extra` ambulancias na base nova.
"""
import unicodedata

from samu_sim.cenarios import Cenario
from samu_sim.core.geo import haversine_km
from samu_sim.core.modelos import Base
from samu_sim.gerador.demanda import Bairro

RAIO_COBERTURA_KM = 5.0


def _slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return "-".join(p for p in s.replace("'", " ").split() if p)


def _dist_mais_proxima(bairro: Bairro, bases: list[Base]) -> float:
    return min(haversine_km(bairro.lat, bairro.lon, b.lat, b.lon) for b in bases)


def demanda_descoberta(bairro: Bairro, bases: list[Base], raio_km: float = RAIO_COBERTURA_KM) -> float:
    return bairro.peso if _dist_mais_proxima(bairro, bases) > raio_km else 0.0


def candidatas(bairros: list[Bairro], bases: list[Base], raio_km: float = RAIO_COBERTURA_KM,
               max_n: int = 12) -> list[dict]:
    lista = []
    for b in bairros:
        d = demanda_descoberta(b, bases, raio_km)
        if d <= 0:
            continue
        lista.append({"id": f"cand-{_slug(b.nome)}", "nome": f"Nova base — {b.nome}", "lat": b.lat, "lon": b.lon,
                      "zona": b.zona, "bairro": b.nome,
                      "dist_base_mais_proxima_km": round(_dist_mais_proxima(b, bases), 1),
                      "demanda_descoberta": round(d, 1)})
    lista.sort(key=lambda c: -c["demanda_descoberta"])
    return lista[:max_n]


def cenario_candidata(cand: dict, alocacao_base: dict, extra: int = 2, **flags) -> Cenario:
    aloc = dict(alocacao_base)
    aloc[cand["id"]] = aloc.get(cand["id"], 0) + extra
    base = {k: cand[k] for k in ("id", "nome", "lat", "lon")}
    return Cenario(cand["nome"], n_ambulancias=sum(aloc.values()), alocacao=aloc, bases_extra=(base,), **flags)
```

Conferir o nome do atributo `peso` em `Bairro` (é property) e a ordem dos campos do construtor (`nome, zona, lat, lon, populacao, fator_demanda`).

- [ ] **Step 4: passar.**
- [ ] **Step 5: commit** — `feat(d9): candidatas a base nova por demanda descoberta`

---

### Task 6: `scripts/experimento_d.py` + gráfico D + `scripts/cenarios.py`

**Files:**
- Create: `scripts/experimento_d.py`, `scripts/cenarios.py`
- Modify: `scripts/graficos.py` (`grafico_d`, chamada no `main`)
- Test: `tests/test_experimento_d.py` (só a parte pura: seleção de finalistas e montagem do JSON com `fake_rodar`)

**Interfaces:**
- `experimento_d.executar(rodar_fn, bairros, bases, alocacao_base, seeds_triagem, seeds_final, duracao_triagem, duracao_final, fator, extra=2, max_candidatas=12, n_finalistas=4, flags) -> dict`:
  1. `baseline` = `Cenario("atual (73)", alocacao=alocacao_base)`; `controle` = `+extra` na base existente com maior `demanda_coberta` (usar `samu_sim.otimizador.demanda_coberta` — conferir assinatura `demanda_coberta(base, bairros)`).
  2. **Triagem**: cada candidata com `seeds_triagem`/`duracao_triagem`; ganho = `P90 candidata − P90 baseline` (mesma triagem). Escolhe `n_finalistas` com menor P90 (desempate por P90 da pior zona).
  3. **Final**: baseline, controle e finalistas com `seeds_final`/`duracao_final`; `comparar(baseline, x)` para cada.
  4. Retorna `{"config", "baseline", "controle", "triagem": [{cand, p90, ganho_seg}], "finalistas": [{cand, resultado, vs_baseline, vs_controle}]}`, finalistas ordenados por `vs_baseline["p90"]["media"]`.
- CLI: `--rapido` (triagem 1 seed 6 h, final 2 seeds 12 h, 6 candidatas, 2 finalistas), default (triagem 1 seed 12 h; final 5 seeds 24 h; 12 candidatas; 4 finalistas), `--seeds-final N`, `--extra 2`, `--transito`, `--reposicionamento`, `--saida docs/experimentos/expansao.json`.
- `grafico_d(res, saida)`: mapa lat/lon (sem tiles) — bases existentes em cinza, candidatas triadas como círculos com tamanho ∝ demanda descoberta e cor = ganho de P90 (verde = melhora), finalistas com anel e rótulo "−X,X min [IC]"; controle anotado na legenda. Estilo via `estilo()` existente.
- `scripts/cenarios.py`: CLI `python scripts/cenarios.py --base '{"nome":"73"}' --alt '{"nome":"80","n_ambulancias":80}' --seeds 42 7 2024 --duracao-sim 86400` → imprime tabela métrica | base [IC] | alt [IC] | diferença [IC] ✓/–.

- [ ] **Step 1: teste**

```python
# tests/test_experimento_d.py
from scripts import experimento_d
from samu_sim.core.modelos import Base
from samu_sim.gerador.demanda import Bairro
from tests.test_cenarios import fake_rodar


def test_experimento_d_escolhe_finalistas_e_compara():
    bases = [Base("b1", "Base 1", -22.90, -43.20), Base("b2", "Base 2", -22.95, -43.35)]
    bairros = [Bairro("Santa Cruz", "Oeste", -22.92, -43.68, 200000, 1.0),
               Bairro("Guaratiba", "Oeste", -23.00, -43.60, 50000, 1.0),
               Bairro("Centro", "Centro", -22.905, -43.205, 40000, 9.5)]
    res = experimento_d.executar(fake_rodar, bairros, bases, {"b1": 40, "b2": 33}, [1], [1, 2], 3600, 7200, 100,
                                 extra=2, max_candidatas=2, n_finalistas=1)
    assert len(res["triagem"]) == 2 and len(res["finalistas"]) == 1
    f = res["finalistas"][0]
    assert f["resultado"]["cenario"]["n_ambulancias"] == 75
    assert f["vs_baseline"]["p90"]["media"] == -20      # fake: -10 s por ambulancia
    assert res["controle"]["cenario"]["n_ambulancias"] == 75
```

- [ ] **Step 2: ver falhar.** (`scripts/__init__.py` já existe, então `from scripts import experimento_d` funciona.)
- [ ] **Step 3: implementar** `scripts/experimento_d.py`:

```python
"""Experimento D: onde abrir a proxima base do SAMU.
Uso: python scripts/experimento_d.py [--rapido] [--extra 2] [--transito] [--reposicionamento]"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim import local as runner  # noqa: E402
from samu_sim.cenarios import Cenario, comparar, executar as executar_cenario  # noqa: E402
from samu_sim.expansao import candidatas, cenario_candidata  # noqa: E402
from samu_sim.gerador.demanda import carregar_bairros, carregar_bases  # noqa: E402
from samu_sim.otimizador import demanda_coberta  # noqa: E402

ZONAS = ("Centro", "Sul", "Norte", "Barra", "Oeste")


def _pior_zona(resumo: dict) -> float:
    return max((resumo[z]["media"] or 0) for z in ZONAS)


def executar(rodar_fn, bairros, bases, alocacao_base, seeds_triagem, seeds_final, duracao_triagem,
             duracao_final, fator, extra=2, max_candidatas=12, n_finalistas=4, flags=None, log=print) -> dict:
    flags = flags or {}
    n_base = sum(alocacao_base.values())
    baseline = Cenario(f"atual ({n_base})", n_ambulancias=n_base, alocacao=alocacao_base, **flags)
    mais_carregada = max(bases, key=lambda b: demanda_coberta(b, bairros) / (alocacao_base.get(b.id, 0) + 1))
    aloc_ctrl = dict(alocacao_base); aloc_ctrl[mais_carregada.id] = aloc_ctrl.get(mais_carregada.id, 0) + extra
    controle = Cenario(f"+{extra} em {mais_carregada.nome}", n_ambulancias=n_base + extra, alocacao=aloc_ctrl, **flags)
    cands = candidatas(bairros, bases, max_n=max_candidatas)

    def rodar(c, seeds, dur):
        return executar_cenario(c, seeds, dur, fator, rodar_fn)

    log(f"triagem: {len(cands)} candidatas, {len(seeds_triagem)} seed(s), {duracao_triagem/3600:.0f} h")
    base_tri = rodar(baseline, seeds_triagem, duracao_triagem)
    triagem = []
    for c in cands:
        r = rodar(cenario_candidata(c, alocacao_base, extra, **flags), seeds_triagem, duracao_triagem)
        ganho = r["resumo"]["p90"]["media"] - base_tri["resumo"]["p90"]["media"]
        triagem.append({"cand": c, "p90": r["resumo"]["p90"]["media"], "ganho_seg": ganho,
                        "pior_zona": _pior_zona(r["resumo"])})
        log(f"  {c['bairro']:22s} P90 {r['resumo']['p90']['media']/60:5.1f} min  ganho {ganho/60:+5.1f} min")
    triagem.sort(key=lambda t: (t["p90"], t["pior_zona"]))
    finalistas_c = [t["cand"] for t in triagem[:n_finalistas]]

    log(f"final: baseline, controle e {len(finalistas_c)} finalistas, {len(seeds_final)} seeds, {duracao_final/3600:.0f} h")
    base_fin = rodar(baseline, seeds_final, duracao_final)
    ctrl_fin = rodar(controle, seeds_final, duracao_final)
    finalistas = []
    for c in finalistas_c:
        r = rodar(cenario_candidata(c, alocacao_base, extra, **flags), seeds_final, duracao_final)
        finalistas.append({"cand": c, "resultado": r, "vs_baseline": comparar(base_fin, r),
                           "vs_controle": comparar(ctrl_fin, r)})
        d = finalistas[-1]["vs_baseline"]["p90"]
        log(f"  {c['bairro']:22s} P90 {r['resumo']['p90']['media']/60:5.1f}  vs atual {d['media']/60:+5.1f} "
            f"[{d['baixo']/60:+.1f}, {d['alto']/60:+.1f}] {'sig' if d['significativo'] else 'n.s.'}")
    finalistas.sort(key=lambda f: f["vs_baseline"]["p90"]["media"])
    return {"config": {"extra": extra, "seeds_triagem": seeds_triagem, "seeds_final": seeds_final,
                       "duracao_triagem": duracao_triagem, "duracao_final": duracao_final, "fator": fator,
                       "flags": flags, "n_base": n_base},
            "baseline": base_fin, "controle": ctrl_fin, "triagem": triagem, "finalistas": finalistas}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rapido", action="store_true")
    p.add_argument("--extra", type=int, default=2)
    p.add_argument("--seeds-final", type=int, default=None)
    p.add_argument("--fator", type=float, default=2000)
    p.add_argument("--transito", action="store_true")
    p.add_argument("--reposicionamento", action="store_true")
    p.add_argument("--alocacao", default="dados/alocacao.json")
    p.add_argument("--saida", default="docs/experimentos/expansao.json")
    a = p.parse_args()
    runner.INTERVALO_OCIOSO_REAL = 0.005
    seeds = [42, 7, 2024, 11, 99, 5, 23, 77, 31, 8]
    if a.rapido:
        cfg = dict(seeds_triagem=[42], seeds_final=[42, 7], duracao_triagem=6 * 3600, duracao_final=12 * 3600,
                   max_candidatas=6, n_finalistas=2)
    else:
        cfg = dict(seeds_triagem=[42], seeds_final=seeds[:a.seeds_final or 5], duracao_triagem=12 * 3600,
                   duracao_final=24 * 3600, max_candidatas=12, n_finalistas=4)
    alocacao = {k: int(v) for k, v in json.loads(Path(a.alocacao).read_text(encoding="utf-8")).items()}
    inicio = time.time()
    res = executar(runner.rodar, carregar_bairros("dados/bairros.csv"), carregar_bases("dados/bases.csv"), alocacao,
                   fator=a.fator, extra=a.extra, flags={"transito": a.transito, "reposicionamento": a.reposicionamento}, **cfg)
    res["config"]["tempo_real_seg"] = round(time.time() - inicio)
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.saida).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"gravado em {a.saida} ({res['config']['tempo_real_seg']} s)")


if __name__ == "__main__":
    main()
```

Conferir formato de `dados/alocacao.json` (dict base_id → n? ou `{"alocacao": {...}}`) antes de ler. `grafico_d` e `scripts/cenarios.py` conforme as interfaces acima.

- [ ] **Step 4: passar; rodar `python scripts/experimento_d.py --rapido` de ponta a ponta e `python scripts/graficos.py`.**
- [ ] **Step 5: commit** — `feat(d9): experimento D (onde abrir a proxima base) + grafico + CLI de cenarios`

---

### Task 7: Console — seção "Cenários"

**Files:**
- Modify: `samu_sim/api/static/mapa.html`

- Seção na sidebar abaixo de "Turnos": formulário compacto (frota `number`, política `select`, seeds `number` 1–10, duração `select` 6h/12h/24h, "trânsito" e "reposicionamento" checkboxes) + botão "Simular cenário"; lista de jobs (nome, status com spinner textual, P90 [IC] quando concluído); ao selecionar dois concluídos, mostra a diferença pareada de P90/P90 vermelho/pendentes com ✓ quando significativa. Polling de `/cenarios` a cada 5 s só quando há job não concluído. Se `POST` devolver 503, a seção mostra "cenários desligados nesta instância".
- Se `docs/experimentos/expansao.json` existir, `GET /expansao` (adicionar handler simples em `criar_app` que lê `expansao_path`, 404 se não existe) e o mapa mostra as candidatas finalistas como marcadores verdes com "−X,X min" ao ligar o toggle "Onde abrir a próxima base".
- Verificar no browser (`scripts/dev_api.py`) e commitar: `feat(d9): secao Cenarios e camada de expansao no console`.

---

### Task 8: Rodar o experimento D real, README, memória, merge, redeploy

- [ ] Rodar `python scripts/experimento_d.py` (default; ≈ 12 triagens × 22 s + 6 × 5 × 45 s ≈ 30 min) em background; enquanto roda, escrever README.
- [ ] `python scripts/graficos.py` → `docs/img/d_expansao.png`.
- [ ] README: seção "Onde abrir a próxima base (D9)" com: método (triagem barata → IC), tabela finalistas (P90 atual → novo, diferença [IC], vs controle "+2 na base existente"), a frase-conclusão, o gráfico; seção "Cenários com IC" (API + CLI, por que pareado por seed); atualizar "Estado" (D9) e "próximos passos" (remover 1 e 2).
- [ ] Atualizar `docs/experimentos/` + memória `samu-sim-entrevista-mckinsey.md`.
- [ ] Suíte verde, commit `docs(d9): resultados do experimento D`, `git push`, `scripts/atualizar_ec2.sh` (API nova com /cenarios), checar `http://98.81.151.45:8000/cenarios`.

## Self-review

- Cobertura: item 1 (IC + comparação + `POST /cenarios`) = Tasks 1, 3, 4, 7; item 2 (base nova) = Tasks 2, 5, 6, 8. ✔
- Tipos: `Cenario.bases_extra` é tupla de dicts em todo lugar; `executar(cenario, seeds, duracao, fator, rodar_fn)` mesma ordem nas Tasks 3/4/6; `comparar(base, alt)` devolve `{metrica: diferenca_pareada}`. ✔
- Riscos: tempo do experimento D (mitigado por triagem + `--rapido`); t3.micro rodando cenário + simulação ao vivo (um job por vez; documentar).

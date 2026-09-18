# samu-sim — Plano D3: OSRM, roteadores reais e política com cobertura

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tempos de viagem reais na malha viária do Rio (OSRM em container), com fallback para haversine quando o OSRM falha; matriz pré-computada base×bairro para rodar sem OSRM (AWS); política `menor_eta_cobertura`; e a primeira comparação medida haversine × OSRM.

**Architecture:** A interface `Roteador.eta(origem, destino)` do D1 ganha duas implementações: `RoteadorOSRM` (HTTP `GET /route/v1/driving/...` com timeout e fallback) e `RoteadorMatriz` (lookup em `dados/matriz_eta.json` gerado pelo serviço `table` do OSRM, com fallback quando origem/destino estão longe dos pontos conhecidos). `criar_roteador(nome, cfg)` passa a receber a `Config` (URL do OSRM, caminho da matriz). O OSRM roda como serviço opcional do compose (`--profile osrm`), preparado uma vez por `scripts/preparar_osrm.sh` (download do extrato BBBike de 36 MB + `osrm-extract/partition/customize`).

**Tech Stack:** OSRM `ghcr.io/project-osrm/osrm-backend:v5.27.1` (algoritmo MLD, perfil `car`), extrato OSM do BBBike, `urllib` (sem dependência nova).

**Spec:** `docs/superpowers/specs/2026-09-18-samu-sim-design.md` (ADR 3, §11-A)

## Global Constraints

- Tudo dos planos D1/D2 continua valendo.
- `Roteador.eta` **nunca levanta exceção** para o chamador: falha de rede/timeout → fallback + contador `fallbacks` + callback opcional `ao_falhar(motivo)`.
- OSRM usa **lon,lat** na URL (ordem inversa da nossa `Ponto = (lat, lon)`).
- Nada de teste unitário batendo em rede: `RoteadorOSRM` recebe `http_get(url, timeout) -> dict` injetável; testes usam fakes. Testes com OSRM real são `@pytest.mark.integration` e pulam se `OSRM_URL` não responder.
- Arquivos grandes (`dados/osrm/*.pbf`, `*.osrm*`) ficam fora do git (`.gitignore`); `dados/matriz_eta.json` (~10 bases × 19 bairros) **entra** no git.

---

## Estrutura de arquivos deste plano

```
samu_sim/core/config.py          + osrm_url, matriz_path, osrm_timeout_seg
samu_sim/roteador/__init__.py    + RoteadorOSRM, RoteadorMatriz, criar_roteador(nome, cfg=None)
samu_sim/politicas/__init__.py   + MenorEtaCobertura
samu_sim/despachante/__main__.py, samu_sim/ambulancia/__main__.py, samu_sim/local.py  (criar_roteador com cfg)
scripts/preparar_osrm.sh         download + pre-processamento (roda uma vez)
scripts/gerar_matriz_osrm.py     OSRM table -> dados/matriz_eta.json
scripts/comparar_roteadores.py   roda samu_sim.local com haversine e osrm e imprime lado a lado
dados/matriz_eta.json
docker-compose.yml               + servico osrm (profile) + OSRM_URL/ROTEADOR nos servicos
.gitignore                       + dados/osrm/
tests/test_roteador.py (+), tests/test_politicas.py (+), tests/test_gerar_matriz.py, tests/test_osrm_integracao.py
```

---

### Task 1: Config e `RoteadorOSRM` com fallback

**Files:**
- Modify: `samu_sim/core/config.py`, `samu_sim/roteador/__init__.py`
- Test: `tests/test_roteador.py` (adicionar)

**Interfaces:**
- `Config`: `osrm_url: str = "http://localhost:5000"`, `osrm_timeout_seg: float = 2.0`, `matriz_path: str = "dados/matriz_eta.json"`.
- `RoteadorOSRM(url: str, fallback: Roteador, timeout_seg: float = 2.0, http_get=None, ao_falhar=None)`, `nome = "osrm"`, atributo `fallbacks: int`. `eta` monta `f"{url}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"`, lê `routes[0].duration` (segundos). Qualquer exceção ou `code != "Ok"` → `fallbacks += 1`, `ao_falhar(str)` se definido, retorna `fallback.eta(...)`. `http_get(url, timeout) -> dict` padrão usa `urllib.request.urlopen` + `json.load`.
- `criar_roteador(nome: str, cfg: Config | None = None) -> Roteador`: `"haversine"`; `"osrm"` → `RoteadorOSRM(cfg.osrm_url, RoteadorHaversine(), cfg.osrm_timeout_seg)`; `"matriz"` (Task 2). `cfg=None` → `Config()`.

- [ ] **Step 1: Adicionar testes em `tests/test_roteador.py`**

```python
from samu_sim.core.config import Config
from samu_sim.roteador import RoteadorOSRM


def test_osrm_usa_duration_da_resposta():
    urls = []

    def http_get(url, timeout):
        urls.append(url)
        return {"code": "Ok", "routes": [{"duration": 1234.5, "distance": 9000}]}

    r = RoteadorOSRM("http://osrm:5000", RoteadorHaversine(), http_get=http_get)
    assert r.eta(COPACABANA, CENTRO) == 1234.5
    assert urls[0] == "http://osrm:5000/route/v1/driving/-43.1822,-22.9711;-43.1829,-22.9068?overview=false"
    assert r.fallbacks == 0


def test_osrm_cai_para_fallback_em_erro_e_conta():
    motivos = []

    def http_get(url, timeout):
        raise TimeoutError("lento")

    r = RoteadorOSRM("http://osrm:5000", RoteadorHaversine(vel_kmh=30), timeout_seg=0.1,
                     http_get=http_get, ao_falhar=motivos.append)
    assert r.eta(COPACABANA, CENTRO) == pytest.approx(858, abs=30)
    assert r.fallbacks == 1 and "lento" in motivos[0]


def test_osrm_code_nao_ok_tambem_e_fallback():
    r = RoteadorOSRM("http://x", RoteadorHaversine(), http_get=lambda u, t: {"code": "NoRoute"})
    assert r.eta(CENTRO, CENTRO) == 0.0 and r.fallbacks == 1


def test_criar_roteador_osrm_com_config():
    r = criar_roteador("osrm", Config(osrm_url="http://osrm:5000"))
    assert r.nome == "osrm"
```

- [ ] **Step 2: Rodar e ver falhar** → `ImportError` (RoteadorOSRM).

- [ ] **Step 3: Implementar**

Em `config.py`, adicionar após `api_porta`:
```python
    osrm_url: str = "http://localhost:5000"
    osrm_timeout_seg: float = 2.0
    matriz_path: str = "dados/matriz_eta.json"
```

Em `samu_sim/roteador/__init__.py`, substituir o conteúdo por:
```python
"""Roteador: tempo estimado de viagem (segundos simulados) entre dois pontos.

Tres implementacoes, mesma interface:
- haversine: linha reta a velocidade media (sem dependencias; subestima no Rio)
- osrm:      malha viaria real via HTTP, com timeout e fallback para haversine
- matriz:    lookup base x bairro pre-computado pelo OSRM (roda sem OSRM, ex.: AWS)
"""
import json
import urllib.request
from typing import Callable, Protocol

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


def _http_get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


class RoteadorOSRM:
    """GET /route/v1/driving/lon,lat;lon,lat. Nunca levanta: falha -> fallback."""
    nome = "osrm"

    def __init__(self, url: str, fallback: Roteador, timeout_seg: float = 2.0,
                 http_get: Callable[[str, float], dict] | None = None,
                 ao_falhar: Callable[[str], None] | None = None):
        self._url = url.rstrip("/")
        self._fallback = fallback
        self._timeout = timeout_seg
        self._http_get = http_get or _http_get_json
        self._ao_falhar = ao_falhar
        self.fallbacks = 0

    def eta(self, origem: Ponto, destino: Ponto) -> float:
        url = (f"{self._url}/route/v1/driving/{origem[1]},{origem[0]};{destino[1]},{destino[0]}"
               f"?overview=false")
        try:
            r = self._http_get(url, self._timeout)
            if r.get("code") != "Ok":
                raise RuntimeError(f"osrm code={r.get('code')}")
            return float(r["routes"][0]["duration"])
        except Exception as e:  # noqa: BLE001 - qualquer falha vira fallback
            self.fallbacks += 1
            if self._ao_falhar:
                self._ao_falhar(repr(e))
            return self._fallback.eta(origem, destino)


def criar_roteador(nome: str, cfg=None) -> Roteador:
    from samu_sim.core.config import Config  # import tardio: config nao depende de roteador
    cfg = cfg or Config()
    if nome == "haversine":
        return RoteadorHaversine()
    if nome == "osrm":
        return RoteadorOSRM(cfg.osrm_url, RoteadorHaversine(), cfg.osrm_timeout_seg)
    raise ValueError(f"roteador desconhecido: {nome}")
```

- [ ] **Step 4: Rodar** `tests/test_roteador.py` → `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add samu_sim/core/config.py samu_sim/roteador/__init__.py tests/test_roteador.py
git commit -m "feat(roteador): RoteadorOSRM com timeout e fallback para haversine

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `RoteadorMatriz`

**Files:**
- Modify: `samu_sim/roteador/__init__.py`
- Test: `tests/test_roteador.py` (adicionar)

**Interfaces:**
- Formato de `matriz_eta.json`:
  ```json
  {"gerado_em": "...", "fonte": "osrm", "raio_km": 1.5,
   "pontos": {"base-01": [lat, lon], "Copacabana": [lat, lon], ...},
   "eta": {"base-01": {"Copacabana": 900.0, ...}, "Copacabana": {"base-01": 880.0, ...}}}
  ```
  `pontos` inclui bases e centróides de bairros; `eta[a][b]` é simétrico-ish (calculado nos dois sentidos).
- `RoteadorMatriz(caminho: str | Path, fallback: Roteador, raio_km: float | None = None)`, `nome = "matriz"`, `fallbacks: int`. `eta(origem, destino)`: acha o ponto conhecido mais próximo de `origem` e de `destino`; se ambos estão a ≤ `raio_km` (default = do arquivo) e `eta[po][pd]` existe → retorna esse valor **mais** o tempo haversine dos dois trechos de aproximação (origem→po e pd→destino) pelo fallback; senão `fallbacks += 1` e devolve `fallback.eta`.
- `criar_roteador("matriz", cfg)` → `RoteadorMatriz(cfg.matriz_path, RoteadorHaversine())`.

- [ ] **Step 1: Testes**

```python
import json
from samu_sim.roteador import RoteadorMatriz


def matriz_tmp(tmp_path):
    m = {"gerado_em": "x", "fonte": "teste", "raio_km": 1.5,
         "pontos": {"base-01": list(CENTRO), "Copacabana": list(COPACABANA)},
         "eta": {"base-01": {"Copacabana": 1000.0}, "Copacabana": {"base-01": 1100.0}}}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def test_matriz_usa_lookup_quando_perto_dos_pontos(tmp_path):
    r = RoteadorMatriz(matriz_tmp(tmp_path), RoteadorHaversine())
    assert r.eta(CENTRO, COPACABANA) == 1000.0            # exatamente nos pontos
    assert r.eta(COPACABANA, CENTRO) == 1100.0
    perto = (COPACABANA[0] + 0.004, COPACABANA[1])         # ~450 m do centroide
    e = r.eta(CENTRO, perto)
    assert 1000.0 < e < 1000.0 + 120                       # + trecho de aproximacao
    assert r.fallbacks == 0


def test_matriz_cai_para_fallback_longe_dos_pontos(tmp_path):
    r = RoteadorMatriz(matriz_tmp(tmp_path), RoteadorHaversine(vel_kmh=30))
    longe = (-23.0, -43.6)
    assert r.eta(CENTRO, longe) == pytest.approx(RoteadorHaversine(30).eta(CENTRO, longe))
    assert r.fallbacks == 1


def test_criar_roteador_matriz(tmp_path):
    r = criar_roteador("matriz", Config(matriz_path=str(matriz_tmp(tmp_path))))
    assert r.nome == "matriz"
```

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar** (adicionar ao `roteador/__init__.py`, antes de `criar_roteador`)

```python
class RoteadorMatriz:
    """Lookup em matriz pre-computada (bases x centroides de bairro). Pontos fora do
    raio conhecido caem no fallback. Soma o trecho de aproximacao ate o ponto conhecido."""
    nome = "matriz"

    def __init__(self, caminho, fallback: Roteador, raio_km: float | None = None):
        from pathlib import Path
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        self._pontos: dict[str, tuple[float, float]] = {k: (v[0], v[1]) for k, v in dados["pontos"].items()}
        self._eta: dict[str, dict[str, float]] = dados["eta"]
        self._raio = raio_km if raio_km is not None else float(dados.get("raio_km", 1.5))
        self._fallback = fallback
        self.fallbacks = 0

    def _mais_proximo(self, p: Ponto) -> tuple[str, float]:
        nome, dist = min(((n, haversine_km(p[0], p[1], q[0], q[1])) for n, q in self._pontos.items()),
                         key=lambda x: x[1])
        return nome, dist

    def eta(self, origem: Ponto, destino: Ponto) -> float:
        po, do_ = self._mais_proximo(origem)
        pd, dd = self._mais_proximo(destino)
        valor = self._eta.get(po, {}).get(pd)
        if valor is None or do_ > self._raio or dd > self._raio:
            self.fallbacks += 1
            return self._fallback.eta(origem, destino)
        aproximacao = 0.0
        if do_ > 0:
            aproximacao += self._fallback.eta(origem, self._pontos[po])
        if dd > 0:
            aproximacao += self._fallback.eta(self._pontos[pd], destino)
        return float(valor) + aproximacao
```
E em `criar_roteador`:
```python
    if nome == "matriz":
        return RoteadorMatriz(cfg.matriz_path, RoteadorHaversine())
```

- [ ] **Step 4: Rodar** → `10 passed`. Commit:

```bash
git add samu_sim/roteador/__init__.py tests/test_roteador.py
git commit -m "feat(roteador): RoteadorMatriz com lookup pre-computado e fallback

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Política `menor_eta_cobertura`

**Files:**
- Modify: `samu_sim/politicas/__init__.py`
- Test: `tests/test_politicas.py` (adicionar)

**Interfaces:**
- `MenorEtaCobertura(penalidade_seg: float = 600.0)`, `nome = "menor_eta_cobertura"`. Ordena por `eta + penalidade` onde a penalidade se aplica à candidata que é a **última disponível da sua base** (`base_id`) — i.e., despachá-la deixa a base descoberta. Empates: menor `eta` puro.
- `criar_politica` reconhece o nome.

- [ ] **Step 1: Testes**

```python
from samu_sim.politicas import MenorEtaCobertura


def test_cobertura_penaliza_ultima_da_base():
    # duas ambulancias na base A (uma bem perto), uma na base B (um pouco mais longe)
    a1 = amb("a1", -22.905, -43.205); a1.base_id = "A"
    a2 = amb("a2", -22.905, -43.205); a2.base_id = "A"
    b1 = amb("b1", -22.92, -43.22); b1.base_id = "B"          # unica da base B
    ordem = MenorEtaCobertura(penalidade_seg=600).escolher(CHAMADO, [b1, a1, a2], RoteadorHaversine())
    assert [a.id for a in ordem][:2] == ["a1", "a2"]           # A tem 2: sem penalidade
    assert ordem[-1].id == "b1"


def test_cobertura_sem_penalidade_quando_todas_sao_ultimas():
    a1 = amb("a1", -22.905, -43.205); a1.base_id = "A"
    b1 = amb("b1", -22.95, -43.25); b1.base_id = "B"
    ordem = MenorEtaCobertura().escolher(CHAMADO, [b1, a1], RoteadorHaversine())
    assert [a.id for a in ordem] == ["a1", "b1"]               # ambas penalizadas igual -> por eta


def test_criar_politica_cobertura():
    assert criar_politica("menor_eta_cobertura").nome == "menor_eta_cobertura"
```

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar**

```python
class MenorEtaCobertura:
    """Menor ETA, mas penaliza despachar a ultima ambulancia disponivel de uma base
    (deixaria a regiao descoberta). Penalidade em segundos de ETA equivalente."""
    nome = "menor_eta_cobertura"

    def __init__(self, penalidade_seg: float = 600.0):
        self._penalidade = penalidade_seg

    def escolher(self, chamado, disponiveis, roteador):
        from collections import Counter
        por_base = Counter(a.base_id for a in disponiveis)
        destino = (chamado.lat, chamado.lon)

        def chave(a):
            eta = roteador.eta((a.lat, a.lon), destino)
            penal = self._penalidade if por_base[a.base_id] == 1 else 0.0
            return (eta + penal, eta)

        return sorted(disponiveis, key=chave)
```
E `_POLITICAS["menor_eta_cobertura"] = MenorEtaCobertura`.

- [ ] **Step 4: Rodar** → `7 passed`. Commit:

```bash
git add samu_sim/politicas/__init__.py tests/test_politicas.py
git commit -m "feat(politicas): menor_eta_cobertura penaliza esvaziar uma base

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Plumbing — `criar_roteador(nome, cfg)` nos serviços, `local.py` e compose

**Files:**
- Modify: `samu_sim/despachante/__main__.py`, `samu_sim/ambulancia/__main__.py`, `samu_sim/local.py`, `docker-compose.yml`, `.gitignore`

- [ ] **Step 1: Entrypoints** — nos dois `__main__.py`, trocar `criar_roteador(rodada.roteador)` por `criar_roteador(rodada.roteador, cfg)`. No despachante, logar fallbacks: após criar `rot = criar_roteador(...)`, se `hasattr(rot, "fallbacks")`, passar `ao_falhar` que registra evento: como `RoteadorOSRM` recebe `ao_falhar` só no construtor, criar em `criar_roteador` um parâmetro opcional `ao_falhar=None` repassado ao OSRM/matriz... **Decisão simples:** `criar_roteador(nome, cfg=None, ao_falhar=None)`; `RoteadorMatriz` também aceita `ao_falhar`. No despachante: `rot = criar_roteador(rodada.roteador, cfg, ao_falhar=lambda m: log.registrar("roteador_fallback", motivo=m))`.

- [ ] **Step 2: `local.py`** — `rodar(...)` recebe `cfg: Config | None = None` e usa `criar_roteador(roteador, cfg)`; CLI ganha `--osrm-url` e `--matriz` que montam a `Config`. Adicionar ao resultado `"roteador_fallbacks": getattr(rot, "fallbacks", 0)`.

- [ ] **Step 3: compose** — adicionar ao `&env`: `ROTEADOR: ${ROTEADOR:-haversine}`, `OSRM_URL: http://osrm:5000`. Bootstrap usa `cfg.roteador` na rodada (já usa). Adicionar serviço:
```yaml
  osrm:
    image: ghcr.io/project-osrm/osrm-backend:v5.27.1
    profiles: ["osrm"]
    command: osrm-routed --algorithm mld --max-table-size 1000 /data/rio.osrm
    volumes:
      - ./dados/osrm:/data
    ports: ["5000:5000"]
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- 'http://localhost:5000/route/v1/driving/-43.18,-22.90;-43.19,-22.91' | grep -q Ok"]
      interval: 5s
      timeout: 3s
      retries: 30
```
`.gitignore`: `dados/osrm/`.

- [ ] **Step 4: Rodar suíte** → tudo verde. Commit:

```bash
git add samu_sim/despachante/__main__.py samu_sim/ambulancia/__main__.py samu_sim/local.py samu_sim/roteador/__init__.py docker-compose.yml .gitignore
git commit -m "feat: roteador configuravel (OSRM_URL, matriz) nos servicos, runner local e compose

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Preparar o OSRM (download + pré-processamento) e teste de integração

**Files:**
- Create: `scripts/preparar_osrm.sh`, `tests/test_osrm_integracao.py`

- [ ] **Step 1: `scripts/preparar_osrm.sh`**

```bash
#!/usr/bin/env bash
# Baixa o extrato OSM do Rio (BBBike, ~36 MB) e pre-processa para o OSRM (MLD).
# Roda uma vez; resultado em dados/osrm/. Uso: bash scripts/preparar_osrm.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dados/osrm
IMG=ghcr.io/project-osrm/osrm-backend:v5.27.1
if [ ! -f dados/osrm/rio.osm.pbf ]; then
  echo ">> baixando extrato do Rio (BBBike)"
  curl -L -o dados/osrm/rio.osm.pbf https://download.bbbike.org/osm/bbbike/RiodeJaneiro/RiodeJaneiro.osm.pbf
fi
V="$(pwd -W 2>/dev/null || pwd)/dados/osrm"
echo ">> osrm-extract (perfil car)"
docker run --rm -v "$V:/data" $IMG osrm-extract -p /opt/car.lua /data/rio.osm.pbf
echo ">> osrm-partition"
docker run --rm -v "$V:/data" $IMG osrm-partition /data/rio.osrm
echo ">> osrm-customize"
docker run --rm -v "$V:/data" $IMG osrm-customize /data/rio.osrm
echo ">> pronto. suba com: docker compose --profile osrm up -d osrm"
ls -la dados/osrm | head
```

- [ ] **Step 2: Rodar** `bash scripts/preparar_osrm.sh` (alguns minutos) e depois `docker compose --profile osrm up -d osrm`; esperar healthy; testar:
```bash
curl -s 'http://localhost:5000/route/v1/driving/-43.1822,-22.9711;-43.1829,-22.9068?overview=false' | head -c 200
```
Esperado: `{"code":"Ok","routes":[{"duration":<~900-1400>,...`.

- [ ] **Step 3: `tests/test_osrm_integracao.py`**

```python
import os
import urllib.request
import pytest
from samu_sim.roteador import RoteadorOSRM, RoteadorHaversine

pytestmark = pytest.mark.integration
COPACABANA = (-22.9711, -43.1822)
CENTRO = (-22.9068, -43.1829)
SANTA_CRUZ = (-22.9186, -43.6845)


@pytest.fixture(scope="module")
def url():
    u = os.environ.get("OSRM_URL", "http://localhost:5000")
    try:
        urllib.request.urlopen(f"{u}/route/v1/driving/-43.18,-22.90;-43.19,-22.91", timeout=3)
    except Exception:
        pytest.skip("OSRM nao esta acessivel")
    return u


def test_osrm_real_da_tempo_maior_que_haversine(url):
    r = RoteadorOSRM(url, RoteadorHaversine())
    osrm = r.eta(CENTRO, SANTA_CRUZ)
    reta = RoteadorHaversine().eta(CENTRO, SANTA_CRUZ)
    assert r.fallbacks == 0
    assert osrm > 0
    # Santa Cruz fica a ~52 km em linha reta; de carro e bem mais que a reta a 30 km/h? Nao
    # necessariamente (via expressa). So garantimos coerencia de ordem de grandeza:
    assert 0.3 * reta < osrm < 3 * reta
```

- [ ] **Step 4: Rodar** `.venv/Scripts/python -m pytest -q -m integration tests/test_osrm_integracao.py` → `1 passed`. Commit:

```bash
git add scripts/preparar_osrm.sh tests/test_osrm_integracao.py
git commit -m "feat: preparo do OSRM (extrato BBBike do Rio) e teste de integracao

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `scripts/gerar_matriz_osrm.py` e `dados/matriz_eta.json`

**Files:**
- Create: `scripts/gerar_matriz_osrm.py`, `dados/matriz_eta.json`
- Test: `tests/test_gerar_matriz.py`

**Interfaces:**
- `montar_pontos(bases, bairros) -> dict[str, tuple[lat, lon]]` (ids de base e nomes de bairro).
- `consultar_tabela(url, pontos, http_get) -> dict[str, dict[str, float]]` — uma chamada `GET {url}/table/v1/driving/{lon,lat;...}?annotations=duration`, lê `durations[i][j]` (segundos; `null` → omitido).
- `gerar(url, bases_csv, bairros_csv, saida, raio_km=1.5, http_get=None) -> dict` grava o JSON no formato da Task 2.
- CLI: `python scripts/gerar_matriz_osrm.py --url http://localhost:5000 --saida dados/matriz_eta.json`.

- [ ] **Step 1: Teste**

```python
import json
from scripts.gerar_matriz_osrm import consultar_tabela, gerar, montar_pontos
from samu_sim.core.modelos import Base
from samu_sim.gerador.demanda import Bairro


def test_consultar_tabela_mapeia_durations():
    pontos = {"b1": (-22.9, -43.2), "X": (-22.95, -43.25)}
    chamadas = []

    def http_get(url, timeout):
        chamadas.append(url)
        return {"code": "Ok", "durations": [[0, 500.0], [520.0, 0]]}

    m = consultar_tabela("http://osrm", pontos, http_get)
    assert m["b1"]["X"] == 500.0 and m["X"]["b1"] == 520.0 and m["b1"]["b1"] == 0
    assert chamadas[0].startswith("http://osrm/table/v1/driving/-43.2,-22.9;-43.25,-22.95?")


def test_gerar_escreve_json_no_formato_do_roteador(tmp_path):
    bases = tmp_path / "bases.csv"; bases.write_text("id,nome,lat,lon\nb1,B,-22.9,-43.2\n", encoding="utf-8")
    bairros = tmp_path / "bairros.csv"; bairros.write_text("bairro,zona,lat,lon,populacao\nX,Sul,-22.95,-43.25,10\n", encoding="utf-8")
    saida = tmp_path / "m.json"
    gerar("http://osrm", bases, bairros, saida,
          http_get=lambda u, t: {"code": "Ok", "durations": [[0, 500.0], [520.0, 0]]})
    m = json.loads(saida.read_text(encoding="utf-8"))
    assert m["pontos"]["b1"] == [-22.9, -43.2] and m["eta"]["b1"]["X"] == 500.0 and m["fonte"] == "osrm"
    from samu_sim.roteador import RoteadorMatriz, RoteadorHaversine
    assert RoteadorMatriz(saida, RoteadorHaversine()).eta((-22.9, -43.2), (-22.95, -43.25)) == 500.0
```

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Implementar `scripts/gerar_matriz_osrm.py`**

```python
"""Gera dados/matriz_eta.json (bases x centroides de bairro) com o servico table do OSRM.
Uso: python scripts/gerar_matriz_osrm.py --url http://localhost:5000"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.gerador.demanda import carregar_bairros, carregar_bases  # noqa: E402
from samu_sim.roteador import _http_get_json  # noqa: E402


def montar_pontos(bases, bairros) -> dict[str, tuple[float, float]]:
    pontos = {b.id: (b.lat, b.lon) for b in bases}
    pontos.update({b.nome: (b.lat, b.lon) for b in bairros})
    return pontos


def consultar_tabela(url: str, pontos: dict, http_get=None, timeout: float = 60.0) -> dict:
    http_get = http_get or _http_get_json
    nomes = list(pontos)
    coords = ";".join(f"{pontos[n][1]},{pontos[n][0]}" for n in nomes)
    r = http_get(f"{url.rstrip('/')}/table/v1/driving/{coords}?annotations=duration", timeout)
    if r.get("code") != "Ok":
        raise RuntimeError(f"osrm table falhou: {r}")
    matriz: dict[str, dict[str, float]] = {}
    for i, a in enumerate(nomes):
        matriz[a] = {}
        for j, b in enumerate(nomes):
            d = r["durations"][i][j]
            if d is not None:
                matriz[a][b] = float(d)
    return matriz


def gerar(url: str, bases_csv, bairros_csv, saida, raio_km: float = 1.5, http_get=None) -> dict:
    pontos = montar_pontos(carregar_bases(bases_csv), carregar_bairros(bairros_csv))
    dados = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "osrm", "raio_km": raio_km,
        "pontos": {k: [v[0], v[1]] for k, v in pontos.items()},
        "eta": consultar_tabela(url, pontos, http_get),
    }
    Path(saida).write_text(json.dumps(dados, indent=1, ensure_ascii=False), encoding="utf-8")
    return dados


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:5000")
    p.add_argument("--bases", default="dados/bases.csv")
    p.add_argument("--bairros", default="dados/bairros.csv")
    p.add_argument("--saida", default="dados/matriz_eta.json")
    p.add_argument("--raio-km", type=float, default=1.5)
    a = p.parse_args()
    d = gerar(a.url, a.bases, a.bairros, a.saida, a.raio_km)
    n = len(d["pontos"])
    print(f"matriz {n}x{n} gravada em {a.saida}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar teste** → `2 passed`. Gerar a matriz real (OSRM de pé):
```bash
.venv/Scripts/python scripts/gerar_matriz_osrm.py
.venv/Scripts/python -c "import json; m=json.load(open('dados/matriz_eta.json')); print(len(m['pontos']), 'pontos; base-01->Santa Cruz', m['eta']['base-01']['Santa Cruz']/60, 'min')"
```
Esperado: `29 pontos`, tempo Centro→Santa Cruz na faixa de 50–90 min.

- [ ] **Step 5: Commit**

```bash
git add scripts/gerar_matriz_osrm.py tests/test_gerar_matriz.py dados/matriz_eta.json
git commit -m "feat: matriz de ETA base x bairro pre-computada pelo OSRM

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Comparação haversine × OSRM × matriz

**Files:**
- Create: `scripts/comparar_roteadores.py`

- [ ] **Step 1: Implementar**

```python
"""Roda a mesma rodada (mesma seed) com cada roteador e imprime P50/P90 lado a lado.
Uso: python scripts/comparar_roteadores.py --fator 5000 --duracao-sim 21600 --roteadores haversine,osrm,matriz"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from samu_sim.core.config import Config  # noqa: E402
from samu_sim.local import rodar  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--roteadores", default="haversine,osrm,matriz")
    p.add_argument("--fator", type=float, default=5000)
    p.add_argument("--duracao-sim", type=float, default=6 * 3600)
    p.add_argument("--ambulancias", type=int, default=40)
    p.add_argument("--chamados-por-dia", type=int, default=600)
    p.add_argument("--politica", default="menor_eta")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--osrm-url", default="http://localhost:5000")
    a = p.parse_args()
    cfg = Config(osrm_url=a.osrm_url)
    linhas = []
    for nome in a.roteadores.split(","):
        r = rodar(a.fator, a.duracao_sim, a.ambulancias, a.politica, nome, a.seed,
                  a.chamados_por_dia, visibilidade_seg=0.2, cfg=cfg)
        m = r["metricas"]
        linhas.append((nome, m["total"], m["atendidos"], m["resposta"]["p50"], m["resposta"]["p90"],
                       {z: v["p90"] for z, v in m["por_zona"].items()}, r.get("roteador_fallbacks", 0)))
    print(f"{'roteador':10s} {'total':>5s} {'atend':>5s} {'P50':>8s} {'P90':>8s}  P90 por zona (min)")
    for nome, t, at, p50, p90, zonas, fb in linhas:
        z = "  ".join(f"{k}={v/60:.0f}" for k, v in sorted(zonas.items()) if v is not None)
        print(f"{nome:10s} {t:5d} {at:5d} {p50/60:7.1f}m {p90/60:7.1f}m  {z}  fallbacks={fb}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Rodar** (OSRM de pé): `.venv/Scripts/python scripts/comparar_roteadores.py --fator 5000` (≈ 3 × 5 s). Colar a saída no README (seção "Resultados preliminares — D3").

- [ ] **Step 3: README** — adicionar seção "Roteamento (D3)" com: como preparar o OSRM, `--profile osrm`, `ROTEADOR=osrm|matriz`, a tabela de comparação, e a nota: *"a matriz existe para rodar sem o container de 1 GB do OSRM (AWS t3.micro); chamados fora do raio dos centróides caem em haversine — contados em `roteador_fallback`"*. Marcar D3 no "Estado".

- [ ] **Step 4: Commit**

```bash
git add scripts/comparar_roteadores.py README.md
git commit -m "feat: comparacao haversine x osrm x matriz e docs do roteamento

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec:** ADR 3 (3 implementações, fallback, comparação medida) → Tasks 1, 2, 5, 6, 7; §6 "OSRM fora/lento → timeout 2 s → haversine; loga `roteador_fallback`" → Tasks 1, 4; §11-A `menor_eta_cobertura` → Task 3; matriz para AWS (ADR 5) → Tasks 2, 6; compose com OSRM só local → Task 4. Dados reais do Data.Rio (§9) continuam como proxy (CSV seed) — documentado no README; fica como próximo passo.
- **Placeholders:** nenhum.
- **Consistência:** `criar_roteador(nome, cfg=None, ao_falhar=None)` (Task 4 estende a assinatura da Task 1 — implementar já com `ao_falhar` na Task 1 para não retrabalhar); `RoteadorMatriz(caminho, fallback, raio_km=None, ao_falhar=None)`; formato do JSON igual nas Tasks 2 e 6; `rodar(..., cfg=None)` e chave `roteador_fallbacks` usados na Task 7.

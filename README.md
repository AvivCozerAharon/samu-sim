# samu-sim

Simulador distribuído de despacho de ambulâncias no Rio de Janeiro. Chamados sintéticos
(proporcionais à população por bairro) são despachados por N despachantes concorrentes que
disputam ambulâncias com lock otimista; workers simulam o deslocamento em tempo acelerado.

Spec: `docs/superpowers/specs/2026-09-18-samu-sim-design.md`.

## Rodar (D1 — tudo em memória)

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m samu_sim.local --fator 20 --duracao-sim 3600 --ambulancias 50 --politica mais_proxima
```

`--fator` acelera o tempo (1 s real = `fator` s simulados). `--log-dir logs` grava o event log JSONL.

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
O relógio simulado é compartilhado pela tabela `rodada` (checkpoint `inicio_real/inicio_sim/fator`);
cada serviço relê a cada 10 s, então `POST /controle` muda o fator em todos sem saltar o tempo.

### Testes de caos

| Falha | Como provocar | O que observar |
|---|---|---|
| Worker morre | `docker compose kill ambulancia-w1` | após ~2–3 min, `reaper_liberou` em `logs/local/api.jsonl`; chamado volta pra fila |
| Despachante morre com msg em mãos | `docker compose kill despachante && docker compose start despachante` | `chamado_ja_despachado` nos logs; `analisar_rodada.py` sem `despachos_duplicados` |
| Corrida entre despachantes | 2 réplicas + `FATOR=200` | `reserva_falhou` > 0 nos logs, nunca 2 `despachada` pro mesmo chamado |

O `bootstrap` é idempotente: se já existe uma rodada ele não mexe em nada (`docker compose start`
re-executa one-shots). Para recomeçar: `docker compose down -v` ou `RESET=1`.

### O que os testes de caos encontraram (e como foi corrigido)

| Sintoma | Causa | Correção |
|---|---|---|
| Tempos de resposta **negativos** | o clock da VM do Docker Desktop saltou −236 s e todos os serviços derivavam o tempo simulado do `time.time()` | `Relogio` sincroniza uma vez com o wall-clock e depois avança com `time.monotonic()`; um salto só afeta quem re-sincronizar |
| Reaper liberava ambulância **30 s** após reserva (timeout é 120 s) | reserva não gravava `heartbeat_em` (ficava 0) | despachante grava heartbeat na reserva |
| Worker reiniciado executava o ciclo do **chamado errado** | mensagem antiga na fila do worker passava na máquina de estados depois do reaper reatribuir a ambulância | worker exige `ambulancia.chamado_id == msg.chamado_id` |
| `ConflitoVersao` em massa + `ResourceNotFound` | `docker compose start` re-executava o bootstrap, que apagava as tabelas no meio da rodada | bootstrap idempotente (`RESET=1` para forçar) |

### Testes de integração (exigem LocalStack)

```bash
docker compose up -d localstack
AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test python -m pytest -q -m integration
```

## Roteamento (D3 — OSRM na malha viária real do Rio)

Três implementações da mesma interface `Roteador.eta(origem, destino)`:

| Roteador | Como | Quando usar |
|---|---|---|
| `haversine` | linha reta a 30 km/h | dia 1, testes, fallback |
| `osrm` | HTTP no OSRM (malha OSM do Rio), timeout 2 s → fallback haversine, evento `roteador_fallback` | local, com `--profile osrm` |
| `matriz` | lookup em `dados/matriz_eta.json` (bases × centróides de bairro, gerado pelo OSRM `table`) + trecho de aproximação | AWS t3.micro (sem container de 1 GB); pontos a > 1,5 km de um centróide caem em haversine |

```bash
bash scripts/preparar_osrm.sh                      # uma vez: extrato BBBike do Rio (36 MB) + osrm-extract/partition/customize (~2 min)
docker compose --profile osrm up -d osrm
python scripts/gerar_matriz_osrm.py                # regenera dados/matriz_eta.json
ROTEADOR=osrm docker compose --profile osrm up -d  # stack inteira roteando pelo OSRM
python scripts/comparar_roteadores.py --fator 3000 --duracao-sim 43200 --ambulancias 50 --chamados-por-dia 400
```

### Haversine × OSRM × matriz (mesma seed, 12 h simuladas, 50 ambulâncias, 400 chamados/dia)

| roteador | P50 | P90 | P90 Barra | P90 Norte | P90 **Oeste** | P90 Sul |
|---|---|---|---|---|---|---|
| haversine | 8,5 min | 15,5 min | 24 | 12 | **27** | 12 |
| osrm | 9,1 min | 17,6 min | 21 | 12 | **33** | 14 |
| matriz | 10,2 min | 18,5 min | 23 | 13 | **33** | 13 |

A linha reta subestima o P90 global em ~14% e o da Zona Oeste em **22%** — é onde a malha
(Av. Brasil, Santa Cruz, Guaratiba) mais diverge da reta. A matriz reproduz o OSRM a ~5%,
o que valida usá-la na AWS. Política `menor_eta_cobertura` (não esvaziar uma base) fica
para os experimentos do D5.

**Gargalo medido:** `menor_eta` avalia todas as candidatas; 40 chamadas `/route` = 210 ms
reais = 17 min *simulados* a fator 5000 (a primeira comparação saiu com P50 de 128 min por
isso). Solução: `Roteador.etas_de(origens, destino)` em lote — 1 chamada `/table` = 34 ms.

## Estado

- [x] D1: núcleo em memória (relógio, fila, repositório com lock otimista, políticas, serviços, métricas)
- [x] D2: docker compose + LocalStack (SQS/DynamoDB), reaper, análise de rodada
- [x] D3: OSRM + política `menor_eta` real + matriz pré-computada
- [ ] D4: Terraform + EC2 + mapa
- [ ] D5: experimentos A (políticas) e B (frota)

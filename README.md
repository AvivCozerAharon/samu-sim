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

### Testes de integração (exigem LocalStack)

```bash
docker compose up -d localstack
AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test python -m pytest -q -m integration
```

## Estado

- [x] D1: núcleo em memória (relógio, fila, repositório com lock otimista, políticas, serviços, métricas)
- [x] D2: docker compose + LocalStack (SQS/DynamoDB), reaper, análise de rodada
- [ ] D3: OSRM + política `menor_eta` real + matriz pré-computada
- [ ] D4: Terraform + EC2 + mapa
- [ ] D5: experimentos A (políticas) e B (frota)

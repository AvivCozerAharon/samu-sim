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

## Estado

- [x] D1: núcleo em memória (relógio, fila, repositório com lock otimista, políticas, serviços, métricas)
- [ ] D2: docker compose + LocalStack (SQS/DynamoDB), reaper, análise de rodada
- [ ] D3: OSRM + política `menor_eta` real + matriz pré-computada
- [ ] D4: Terraform + EC2 + mapa
- [ ] D5: experimentos A (políticas) e B (frota)

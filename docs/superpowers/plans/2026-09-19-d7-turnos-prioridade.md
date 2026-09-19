# samu-sim — Plano D7: prioridade no despacho e turnos que aprendem

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Chamados vermelhos são atendidos antes dos verdes — filas por prioridade e métrica "P90 dos vermelhos". (2) Um otimizador roda a simulação em turnos e, a cada turno, lê o event log, produz um diagnóstico em linguagem simples ("Zona Oeste P90 33 min; UPA Botafogo com 12 % de utilização") e move ambulâncias entre bases; mantém a mudança se o objetivo melhorou, desfaz se piorou. (3) Console mostra a trajetória dos turnos e o diagnóstico.

**Architecture:** três filas SQS (`samu-chamados-vermelho|amarelo|verde`); o despachante consome na ordem vermelho → amarelo → verde (só desce de nível quando a fila acima está vazia). `montar_frota` aceita uma alocação `{base_id: n}`; a `Rodada` guarda `alocacao` (JSON) e o bootstrap lê `dados/alocacao.json` se existir. `samu_sim/otimizador.py` = laço de turnos em memória (`local.rodar`) com diagnóstico + proposta + aceite/rejeição; `scripts/turnos.py` grava `docs/experimentos/turnos.json`; `GET /turnos` serve esse arquivo e o console ganha a seção "Turnos".

**Spec:** `docs/superpowers/specs/2026-09-18-samu-sim-design.md` §13 (ML/próximos passos) — o "aprendizado" aqui é otimização guiada por dados, explicável; previsão de demanda por ML fica documentada como passo seguinte.

## Global Constraints
- Objetivo do otimizador: `J = 3·P90(vermelho) + P90(amarelo) + 0,5·P90(verde)` (min), avaliado com a mesma seed do turno anterior; aceita se `J` cair ≥ 1 %.
- Um movimento por turno (1 ambulância), para o diagnóstico ser legível; máximo de N turnos (default 10).
- Compatibilidade: sem `dados/alocacao.json` tudo funciona como hoje (round-robin).

---

### Task 1: filas por prioridade
- `Config.fila_chamados` vira prefixo; `Config.filas_chamados() -> dict[prioridade, nome]`. `FilaMemoria`/`FilaSQS` inalteradas; `gerador` publica na fila da prioridade; `Despachante` recebe `dict[prioridade, Fila]` e em `processar_lote` percorre vermelho → amarelo → verde parando no primeiro nível com mensagens. Reaper devolve à fila da prioridade do chamado. Bootstrap/Terraform criam as 3 filas; `local.py`/`dev_api.py` montam as 3.
- Métricas: `calcular` ganha `por_prioridade` {p50, p90, n}; `analisar_rodada` idem; `/metricas` expõe; console mostra "P90 vermelho" ao lado do P90 global.
- Testes: vermelho publicado depois de 5 verdes é despachado primeiro; métricas por prioridade.

### Task 2: alocação por base
- `montar_frota(bases, n, n_workers, alocacao=None)`; `Rodada.alocacao: str | None` (JSON); `local.rodar(..., alocacao=None)`; bootstrap lê `dados/alocacao.json` (`{"base-05": 3, ...}`) e grava na rodada. `rodar` passa a devolver também `chamados` (lista de dicts) e `ambulancias` para o diagnóstico.
- Testes: alocação respeitada; soma diferente de `n` → erro claro.

### Task 3: otimizador de turnos
- `samu_sim/otimizador.py`: `diagnosticar(resultado, bases) -> dict` (P90 por zona e prioridade; utilização por base = Σ(liberado_em − despachado_em)/(n_amb_base × duração); chamados que esperaram > 60 s por zona); `propor(diag, alocacao, bases) -> (alocacao_nova, acoes: list[str])` (tira 1 da base com menor utilização e ≥ 2 ambulâncias; põe na base com maior demanda (peso dos bairros a ≤ 5 km) da zona com pior J parcial que ainda não recebeu neste ciclo); `Otimizador.turno()` executa, compara J, aceita/rejeita; `executar(n_turnos)` devolve trajetória.
- `scripts/turnos.py --turnos 10 --ambulancias 73 --chamados-por-dia 600` → `docs/experimentos/turnos.json` + resumo por turno impresso: diagnóstico, ações, J antes/depois, aceito/rejeitado; grava `dados/alocacao.json` com a melhor alocação.
- Testes: com um cenário sintético de 2 bases (uma ociosa, uma sobrecarregada) o otimizador move na direção certa e aceita.

### Task 4: console "Turnos"
- `GET /turnos` (lê `docs/experimentos/turnos.json`, 404 se não houver); seção na barra lateral: barras J por turno (aceito verde / rejeitado cinza), alocação final, último diagnóstico e ações em texto. `scripts/graficos.py` ganha `c_turnos.png`.

### Task 5: docs
- README: seção "Prioridade e turnos" com a trajetória, a tabela de ações e o parágrafo honesto sobre ML (o que é otimização, o que seria ML, por que RL não). Atualizar `calibracao.md` (prioridade agora influencia). Commit, push, merge; redeploy na EC2 com `alocacao.json`.

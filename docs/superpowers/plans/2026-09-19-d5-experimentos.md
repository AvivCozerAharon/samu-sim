# samu-sim — Plano D5: experimentos A (políticas) e B (frota), gráficos e README final

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Responder com números "qual política de despacho reduz o P90 (sobretudo na Zona Oeste)?" e "a partir de quantas ambulâncias o ganho é marginal?", com gráficos, uma rodada de validação na AWS e o README final com as decisões de arquitetura.

**Architecture:** `scripts/experimentos.py` roda a matriz de cenários em memória (`samu_sim.local.rodar`, roteador `matriz` — validado contra o OSRM no D3 —, 24 h simuladas, 3 seeds) e grava `docs/experimentos/resultados.json`. `scripts/graficos.py` gera PNGs com matplotlib. `scripts/experimento_aws.sh` roda um cenário por rodada na EC2 (RESET + política via `.env`), coleta o event log e usa `analisar_rodada.py` para comparar com o resultado em memória.

**Tech Stack:** matplotlib (dev), scripts existentes.

**Spec:** `docs/superpowers/specs/2026-09-18-samu-sim-design.md` §11

## Global Constraints
- Comparações sempre com a mesma seed entre cenários; 3 seeds (42, 7, 2024) e média/desvio reportados.
- Regime sem saturação para A (frota 50, 600 chamados/dia); B varre 20/30/40/50/65/80 com `menor_eta`.
- Em memória, o despachante faz polling a cada 20 ms reais; a fator 2000 isso é 40 s simulados de espera máxima — igual para todos os cenários, e reportado.

---

### Task 1: `scripts/experimentos.py`
- `--rapido` roda 1 seed e 12 h. Saída: JSON `{cenario: {seed: metricas}}` + tabela no terminal (P50, P90 global, P90 por zona, atendidos/total).
- Cenários A: `mais_proxima`, `menor_eta`, `menor_eta_cobertura` (frota 50). B: frota ∈ {20,30,40,50,65,80} (`menor_eta`).
- Commit.

### Task 2: `scripts/graficos.py`
- `docs/img/a_politicas_p90_zona.png` (barras agrupadas: zona × política, linha da meta 15 min) e `docs/img/b_frota_p90.png` (curva P90 e P50 × frota, com banda dos seeds).
- `pip install matplotlib` em `dev`. Commit.

### Task 3: validação na AWS
- `scripts/experimento_aws.sh POLITICA N_AMB DURACAO_REAL_SEG`: atualiza `.env`, RESET, sobe, espera, `s3 sync`, baixa, roda `analisar_rodada.py`. Rodar `menor_eta` e `mais_proxima` (fator 60, 6 h sim = 6 min reais cada). Comparar com o em memória (mesma seed, mesmas 6 h) e registrar a diferença.

### Task 4: README final
- Seção "Resultados": tabela A, tabela B, gráficos, o insight em uma frase.
- Seção "Decisões de arquitetura" (ADRs do spec, com o que mudou e por quê), "O que eu faria diferente", "Próximos passos" (Fargate, WS+React, ML com o event log).
- Marcar D5. Commit, push, merge.

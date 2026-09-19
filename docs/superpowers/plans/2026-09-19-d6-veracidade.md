# samu-sim — Plano D6: veracidade (dados reais e ciclo realista)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir os dados inventados por dados públicos calibrados com estatísticas reais do SAMU-RJ: 165 bairros do Censo 2022, ~43 bases reais (hospitais de emergência + UPAs), demanda com o ranking real (Campo Grande, Santa Cruz, Centro), curva horária da literatura (picos 12 h e 20 h), gravidade e tipo no chamado, e ciclo com transporte ao hospital.

**Architecture:** `scripts/preparar_dados.py` gera `dados/bairros.csv` (165 linhas, com `zona`, `regiao_adm`, `populacao` 2022, `fator_demanda`) a partir do JSON do ArcGIS da prefeitura (`dados/fontes/`); `scripts/geocodificar_bases.py` gera `dados/bases.csv` (hospitais + UPAs, `tipo`) via Nominatim com cache. `GeradorChamados` ganha `prioridade`/`tipo` e a nova `PESOS_HORA`. O worker ganha a etapa `transportando` (no local → hospital mais próximo → base). `docs/calibracao.md` registra cada número e fonte. Experimentos A/B são re-executados.

**Spec:** `docs/superpowers/specs/2026-09-18-samu-sim-design.md` §9 (dados) — atualiza a decisão "UPAs como proxy".

## Global Constraints
- Fontes: Data.Rio/IPP (Censo 2022 por bairro), SMS-Rio (hospitais e UPAs), Diário do Rio/SAMU-RJ 2024 (216 mil envios/ano ≈ 592/dia; Campo Grande 12.614), literatura SAMU (picos 12 h/20 h; 48–60 % clínico, ~33 % trauma; USA minoria).
- Sem chave de API: Nominatim com `User-Agent` próprio, 1 req/s, cache em `dados/fontes/geocode.json`.
- Compatibilidade: `carregar_bairros`/`carregar_bases` continuam funcionando (colunas novas opcionais); testes que contavam 19/10 passam a ler o CSV.

---

### Task 1: `scripts/preparar_dados.py` → `dados/bairros.csv` (165)
- Centróide do maior anel de cada bairro; `zona` por `regiao_adm` (mapa fixo AP → Centro/Sul/Norte/Barra/Oeste); `fator_demanda` = 1,0, exceto Centro 6,0 (população flutuante; calibrado para o Centro entrar no top 3 como no dado real) e Paquetá 0 (ilha sem base).
- Teste: 165 linhas, soma pop ≈ 6,21 M, Campo Grande/Santa Cruz/Centro no top 3 de `populacao × fator_demanda`, todas as zonas presentes.

### Task 2: `scripts/geocodificar_bases.py` → `dados/bases.csv` (~43)
- Lista de hospitais (12) e UPAs (31, endereço quando há; senão "UPA <nome>, Rio de Janeiro"); geocodifica; valida que o ponto cai na bbox do município; `tipo` = `hospital|upa`. Fallback: centróide do bairro.
- Teste: ≥ 35 bases, todas na bbox, `tipo` preenchido.

### Task 3: demanda calibrada + gravidade/tipo
- `PESOS_HORA` com picos em 12 h e 20 h, vale 1–6 h. `Chamado.prioridade` (`vermelho|amarelo|verde` ≈ 10/30/60 %, vermelho sobe à noite) e `Chamado.tipo` (`clinico|trauma`, trauma ≈ 33 %, 45 % entre 22–5 h). `GeradorChamados` usa `populacao × fator_demanda`.
- Testes: distribuição das prioridades dentro de ±3 pp em 20 000 chamados; ranking de bairros; pesos.

### Task 4: ciclo com hospital
- `StatusAmbulancia.TRANSPORTANDO`; transições `no_local → transportando → retornando`. Worker: após atendimento (20–30 min), ETA até o hospital mais próximo (bases `tipo=hospital`) pela matriz/roteador, 10 min de entrega, depois retorna à base. Eventos `transporte_iniciado`, `hospital_chegou`. Snapshot/front: cor nova (`transportando`), interpolação chamado → hospital.
- Testes: ciclo completo passa por `transportando`; hospital escolhido é o mais próximo.

### Task 5: matriz, experimentos, docs
- `gerar_matriz_osrm.py` com 165 + 43 pontos (OSRM local; se o Docker não subir, `matriz` cai em haversine para pontos fora e isso é medido).
- Re-executar `experimentos.py` e `graficos.py`; `docs/calibracao.md`; README (seção "Dados" e tabela de resultados atualizada). Commit, push, merge.

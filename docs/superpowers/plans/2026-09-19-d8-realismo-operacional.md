# samu-sim — Plano D8: realismo operacional (disponível no retorno, reposicionamento por previsão, trânsito)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir os três erros de modelo que mais distorcem o joelho da frota: (1) a ambulância volta a ser despachável ao liberar no hospital, movendo-se enquanto retorna; (2) ao liberar, em vez de voltar à base de origem, vai para a base onde a demanda prevista das próximas 2 h é maior relativa à cobertura (modelo de demanda zona × hora treinado no event log); (3) tempos de viagem escalados por um perfil de trânsito por hora.

**Architecture:** `Repositorio.atualizar_posicao_se_disponivel(id, lat, lon)` (sem `versao`, condicional em `status=disponivel`). O worker, após a entrega no hospital, transiciona `transportando → disponivel` no hospital e executa um *retorno interrompível*: a cada passo (≥ 30 s sim) atualiza a posição; se o status deixou de ser `disponivel` (foi reservada), para. `samu_sim/previsao.py` = `ModeloDemanda` (tabela zona × hora suavizada, treinada de eventos `chamado_criado`) + `Reposicionador.escolher_base(hospital, agora_sim)`. `RoteadorComTransito` envolve qualquer roteador e multiplica o ETA pelo fator da hora simulada. Experimento B re-executado com os três ligados.

## Global Constraints
- Compatível: sem modelo de demanda o worker volta à base de origem; sem `transito` os tempos são os do OSRM.
- O modelo de demanda é treinado **só** com eventos `chamado_criado` (o que um sistema real teria); `scripts/treinar_demanda.py --logs <pasta>` ou `--dias N` (gera N dias com o gerador e treina — honesto: aprende a curva do gerador; o valor é o pipeline).
- Fatores de trânsito: **estimativa** documentada em `docs/calibracao.md` (TomTom Traffic Index Rio ≈ +40–60 % nos picos): 1,0 (0–6 h), 1,25 (7 h), 1,5 (8–9 h), 1,3 (10–16 h), 1,55 (17–19 h), 1,3 (20–21 h), 1,1 (22–23 h).

### Task 1: disponível no retorno
- Repositório (memória + Dynamo): `atualizar_posicao_se_disponivel`. Worker: `_retornar(amb_id, origem, destino_base)` interrompível; evento `retorno_interrompido` quando reservada no caminho. Status `retornando` deixa de ser usado pelo worker (fica no enum por compatibilidade do front).
- Testes: retorno completo põe na base; reserva durante o retorno interrompe sem sobrescrever a posição; snapshot mostra a ambulância `disponivel` se movendo (posição vem do repo, sem interpolação no front).

### Task 2: previsão de demanda e reposicionamento
- `previsao.py`: `ModeloDemanda.treinar(eventos) / prever(zona, hora_inicio, horas=2) / salvar/carregar JSON`; suavização por vizinhos de hora e Laplace. `Reposicionador(modelo, bases, bairros, repo)`: `escolher_base(posicao, agora_sim)` = argmax sobre bases a ≤ 15 km de `prevista(zona) / (disponiveis_na_zona + 1)`, empatando pela distância. Worker recebe `reposicionador` opcional; ao escolher outra base, atualiza `base_id` da ambulância (evento `reposicionada`).
- `scripts/treinar_demanda.py` → `dados/demanda_prevista.json`. `local.rodar(..., reposicionamento=True)` carrega o modelo se existir. Config `reposicionamento: bool`.
- Testes: modelo aprende picos; reposicionador escolhe a zona com mais demanda prevista e menos cobertura; worker vai para a base escolhida.

### Task 3: trânsito por hora
- `RoteadorComTransito(base: Roteador, hora_fn, fatores: list[float])` em `roteador/`; `criar_roteador(nome, cfg, ..., relogio=None)` envolve quando `cfg.transito`. Config `transito: bool = False`. Testes: fator aplicado por hora; `etas_de` em lote também.

### Task 4: experimentos e docs
- Experimento B com `reposicionamento` e `transito` ligados (3 seeds) → novo joelho; experimento E: reposicionamento on/off, mesmas seeds. README: nova tabela B, seção "O que o realismo operacional mudou", `calibracao.md` (trânsito, previsão). Commit, push, merge, redeploy.

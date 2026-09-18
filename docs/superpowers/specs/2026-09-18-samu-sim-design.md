# samu-sim — Simulador distribuído de despacho de ambulâncias (Rio de Janeiro)

Data: 2026-09-18
Status: aprovado (brainstorm concluído)

## 1. Objetivo

Sistema distribuído que simula o atendimento de chamados de emergência na cidade do
Rio de Janeiro: chamados são gerados a partir de dados reais de população por bairro,
despachantes escolhem ambulâncias segundo uma política plugável, workers simulam o
deslocamento das ambulâncias, e métricas de tempo de resposta (P50/P90 por zona) são
calculadas para comparar cenários.

Uso principal: ferramenta de apoio à decisão ("qual política de despacho reduz o P90
da Zona Oeste?", "a partir de quantas ambulâncias o ganho é marginal?").

Contexto: projeto construído em ~5 dias para servir de base a uma entrevista técnica.
As decisões abaixo priorizam (a) problemas distribuídos reais e mensuráveis, (b) custo
zero na AWS, (c) escopo fechado. Tudo que não está em "Escopo" está em "Fora de escopo".

## 2. Decisões de arquitetura (ADRs resumidos)

| # | Decisão | Alternativas rejeitadas | Motivo |
|---|---|---|---|
| 1 | Tempo real acelerado, fator ∈ {1,2,5,10,20} ajustável em runtime | DES num processo (não é distribuído); relógio lógico com ticks (complexo p/ 1 semana) | Problemas de concorrência aparecem de verdade; demo visual |
| 2 | SQS + DynamoDB desde o dia 1, emulados por LocalStack | Kafka/Redpanda + Redis (portar p/ AWS custa tempo/dinheiro); Redis-tudo | Um só código roda local e na AWS |
| 3 | Roteador com 3 implementações: `haversine` (D1), `osrm` (local), `matriz` (AWS) | OSRM desde o início (risco de setup); só matriz | Sistema funciona no dia 1; comparação haversine×OSRM vira dado |
| 4 | Mapa Leaflet com polling servido pelo FastAPI; `/ws/estado` exposto para futuro React+WS | Só métricas; React+WS agora | 1 dia de trabalho, demo forte |
| 5 | AWS: 1 EC2 t3.micro (free tier) com docker compose + SQS/DynamoDB reais, via Terraform | ECS Fargate (pago); Lambda (arquitetura diferente) | Custo zero; Fargate é próximo passo |
| 6 | Experimentos obrigatórios: comparação de políticas (A) e tamanho de frota (B) | Posicionamento de bases (stretch) | Baratos: política plugável + parâmetro |
| 7 | Roteador é biblioteca dentro do despachante, não serviço | Serviço HTTP de roteamento | Menos uma rede para falhar; OSRM já é container próprio |
| 8 | Uma fila SQS `eventos-<worker>` por worker de ambulância | Fila única com filtro no consumidor | Evita mensagem "roubada" por worker errado |
| 9 | Métricas derivadas do event log (JSONL), não de contadores em memória | Prometheus/Grafana | Uma fonte de verdade; funciona offline; é o dataset do ML |
| 10 | Lock otimista via `ConditionExpression` (status + versao) no DynamoDB | Lock distribuído (Redis/DynamoDB Lock) | Suficiente para o caso; falhas contadas como métrica |

## 3. Arquitetura

4 serviços próprios (mesma imagem Docker, comando diferente) + LocalStack (local) +
OSRM (só local).

```
gerador ──► [SQS chamados] ──► despachante (N) ──reserva condicional──► DynamoDB
                                    │                                        ▲
                                    ├── roteador (lib): haversine|osrm|matriz │
                                    ▼                                        │
                        [SQS eventos-w1..wN] ──► ambulancia (N workers) ─────┘
                                                        │ heartbeat
                                     api (FastAPI) ─ lê DynamoDB ─► /estado /metricas /controle /ws/estado / (mapa)
                                       └─ reaper (thread)
todos os serviços ──► eventlog (JSONL por serviço/rodada; sobe p/ S3 no fim)
```

### 3.1 Estrutura do repositório

```
samu-sim/
  samu_sim/
    core/         modelos (Chamado, Ambulancia, estados), Relogio, config
    infra/        Fila e Repositorio: implementações em memória + SQS/DynamoDB (boto3)
    roteador/     interface Roteador + haversine / osrm / matriz
    politicas/    interface Politica + mais_proxima / menor_eta / menor_eta_cobertura
    gerador/      serviço
    despachante/  serviço
    ambulancia/   serviço (workers)
    api/          serviço FastAPI + static/ (mapa Leaflet) + reaper
    eventlog/     escrita append-only de eventos
  dados/          bairros.geojson, bases.csv, populacao.csv, matriz_eta.json
  scripts/        preparar_dados.py, gerar_matriz_osrm.py, analisar_rodada.py
  infra/          terraform: sqs.tf, dynamodb.tf, iam.tf, ec2.tf, variables.tf
  tests/
  docker-compose.yml, docker-compose.aws.yml, Dockerfile, pyproject.toml
```

Python 3.12, FastAPI, boto3, pytest. Sem framework de frontend.

### 3.2 Componentes

| Componente | Responsabilidade | Depende de |
|---|---|---|
| `core.Relogio(fator)` | `agora_sim()`, `dormir_sim(seg)`; checkpoint `(inicio_real, inicio_sim)` para mudar fator sem saltar o tempo | — |
| `infra.Fila` | `publicar(msg)`, `consumir() -> iter[msg]`, `ack(msg)`. Impl: `FilaMemoria`, `FilaSQS` | boto3 |
| `infra.Repositorio` | get/put de ambulâncias, chamados e rodada; `reservar_ambulancia(id, versao)`; `transicionar(id, de, para, versao)`. Impl: `RepositorioMemoria`, `RepositorioDynamo` | boto3 |
| `roteador.Roteador` | `eta(origem, destino) -> segundos`. Impl: `Haversine(vel_kmh)`, `OSRM(url, timeout, fallback)`, `Matriz(arquivo, fallback)` | HTTP (OSRM) |
| `politicas.Politica` | `escolher(chamado, disponiveis, roteador) -> list[Ambulancia]` ordenada | Roteador |
| `gerador` | sorteia chamados (bairro ∝ população, curva horária, seed fixa) e publica em `chamados` no ritmo do relógio | Fila, Relogio, dados |
| `despachante` | consome `chamados`; política; tenta reservar candidatas em ordem; grava chamado; publica `despachada` na fila do worker dono | Fila, Repositorio, Politica |
| `ambulancia` | máquina de estados por ambulância; consome `eventos-<worker>`; heartbeat a cada 30 s reais | Fila, Repositorio, Relogio |
| `reaper` | thread na `api`; a cada 60 s libera ambulâncias com heartbeat vencido (>120 s) e republica o chamado com `tentativas+1` | Repositorio, Fila |
| `api` | `GET /estado`, `GET /metricas`, `POST /controle` (fator, política, pause, reset), `WS /ws/estado`, `GET /` (mapa) | Repositorio |
| `eventlog` | `registrar(evento: dict)` → JSONL `logs/<rodada>/<servico>.jsonl`; upload p/ S3 opcional | fs, boto3 |

Toda dependência externa tem implementação em memória: a suíte roda sem Docker.

## 4. Modelo de dados

### 4.1 DynamoDB

`ambulancias` (PK `id`)
```
id, base_id, lat, lon,
status: disponivel | reservada | a_caminho | no_local | retornando,
versao: int (incrementa a cada update),
chamado_id: str | null,
heartbeat_em: float (tempo simulado),
worker_id: str
```

`chamados` (PK `id`)
```
id, lat, lon, bairro, zona,
criado_em, despachado_em, chegada_em, liberado_em  (tempo simulado; null até acontecer),
ambulancia_id: str | null,
status: pendente | despachado | atendido,
tentativas: int
```

`rodada` (PK `id`, 1 item ativo)
```
id, seed, politica, fator, n_ambulancias, roteador,
inicio_real, inicio_sim   (checkpoint do relógio),
pausada: bool
```
Serviços leem `rodada` no boot e a cada 10 s.

Zonas: Centro, Sul, Norte, Oeste, Barra — mapeamento fixo bairro→zona em `dados/`.

### 4.2 Mensagens

`chamados` (SQS standard): `{chamado_id, lat, lon, bairro, zona, criado_em}`
`eventos-<worker_id>` (SQS standard): `{tipo: "despachada", chamado_id, ambulancia_id, eta_seg, ts_sim}`

### 4.3 Event log

Um registro JSON por linha, campos comuns `{ts_sim, ts_real, rodada_id, servico, tipo, ...}`.
Tipos: `chamado_criado, despacho_tentado, reserva_falhou, despachada, chegou, liberada,
transicao_rejeitada, roteador_fallback, reaper_liberou, rodada_iniciada, fator_alterado`.

## 5. Fluxos

### 5.1 Chamado
1. `gerador` publica em `chamados`.
2. `despachante` recebe; se `chamado.status == despachado` → ack (idempotência).
3. Lê disponíveis (scan filtrado; cache local de 2 s).
4. `politica.escolher()` → candidatas ordenadas.
5. Para cada candidata: `reservar_ambulancia(id, versao)` (condição `status=disponivel AND versao=:v`).
   Sucesso → grava `chamado.despachado_em/ambulancia_id/status`, publica `despachada` em `eventos-<worker>`, ack.
   Falha → loga `reserva_falhou`, próxima candidata.
6. Nenhuma disponível → não dá ack; SQS reentrega após visibility timeout (30 s real).
   Fila crescendo = backpressure; métrica "idade do chamado mais antigo".

### 5.2 Máquina de estados da ambulância
```
disponivel --reserva(despachante)--> reservada --msg despachada--> a_caminho
    ^                                                                 | dormir_sim(eta)
    |                                                                 v
    +---- retornando <-- dormir_sim(atendimento 10-20 min) -------- no_local
```
Cada transição é `transicionar(id, de, para, versao)` condicional. Condição falha
(mensagem duplicada/atrasada) → `transicao_rejeitada` + ack. Após `no_local`, política
decide: voltar à base (`retornando`, ETA até a base) ou ficar no local (`disponivel`
direto). Padrão: voltar à base.

### 5.3 Relógio
`agora_sim = inicio_sim + (agora_real - inicio_real) * fator`. `POST /controle {fator}`
grava novo checkpoint com os valores atuais; serviços releem em ≤10 s.

## 6. Falhas e mitigação

| Falha | Mitigação | Teste de caos |
|---|---|---|
| Despachante morre com msg | sem ack → reentrega; idempotência por `chamado.status` | `docker kill` despachante |
| Dois despachantes, mesma ambulância | condicional DynamoDB; métrica `reserva_falhou` | 3 despachantes + fator 20 |
| Worker de ambulância morre | heartbeat + reaper; chamado volta à fila | `docker kill` worker |
| Msg duplicada/atrasada | máquina de estados rejeita | injetar duplicata via script |
| OSRM fora/lento | timeout 2 s → haversine; `roteador_fallback` | parar container OSRM |
| DynamoDB throttle | cache 2 s no despachante; retry do boto3 | — |
| Frota insuficiente | não é bug: métrica de idade da fila / P90 | experimento B |

## 7. Observabilidade

- Logs JSON estruturados (`logging` + formatter) com `rodada_id, servico, chamado_id, ambulancia_id`. Local: `docker compose logs`; AWS: CloudWatch agent.
- `scripts/analisar_rodada.py`: lê o event log e produz P50/P90 por zona, utilização da frota, contagem de `reserva_falhou`/`roteador_fallback`/`reaper_liberou`, e gráfico comparativo (matplotlib) entre rodadas.
- `GET /metricas`: mesma conta, ao vivo, sobre `chamados` (janela dos últimos 60 min sim).

## 8. Testes

- Unitários: haversine; cada política; Relogio (mudança de fator não salta); máquina de estados.
- Concorrência: 2 despachantes em threads sobre `RepositorioMemoria` disputando 1 chamado → exatamente 1 reserva.
- Integração em-processo: gerador → despachante → 2 workers, tudo em memória, fator 1000, 50 chamados → todos atendidos, nenhum duplicado, P90 calculável.
- Contrato (`@pytest.mark.integration`, exige Docker/LocalStack): `reservar_ambulancia` condicional no DynamoDB real.

## 9. Dados

`scripts/preparar_dados.py` (roda uma vez):
- Bairros (GeoJSON) e população por bairro: Data.Rio / IPP / IBGE.
- Bases: unidades de saúde do Data.Rio filtradas por UPA + hospitais de emergência (~20). Se não houver dataset aberto do SAMU, UPAs são proxy — documentado no README.
- Demanda: 300 chamados/dia ∝ população, curva horária com picos 8–11h e 18–21h. Parâmetros em config.
- `scripts/gerar_matriz_osrm.py`: `matriz_eta.json` (base × centróide de bairro) para o modo AWS.

## 10. Infra AWS (Terraform)

Recursos: filas SQS (`chamados`, `eventos-w1..wN`), tabelas DynamoDB (on-demand),
bucket S3 para event log, IAM role da instância, EC2 t3.micro (Amazon Linux, Docker
instalado via user-data, `docker-compose.aws.yml` sem LocalStack/OSRM). Alarme de
billing em US$ 10 criado no dia 1. `terraform destroy` ao fim de cada sessão.

## 11. Experimentos

A. Políticas: mesma seed, 6 h de pico simuladas, `mais_proxima` × `menor_eta` × `menor_eta_cobertura`. Saída: P50/P90 por zona.
B. Frota: política fixa, 30/50/80 ambulâncias. Saída: curva P90 × frota.
Stretch: posicionamento de 1 base nova (5 candidatos).

## 12. Cronograma

| Dia | Entrega |
|---|---|
| D1 | Repo; `core`, `infra` (memória + SQS/DynamoDB); 3 serviços rodando em-processo com testes verdes; dados do Rio |
| D2 | docker compose + LocalStack; 4 serviços em containers; chaos worker/reaper; event log + `analisar_rodada.py` |
| D3 | OSRM local; `menor_eta`; matriz; comparação haversine × OSRM |
| D4 | Terraform + deploy EC2; mapa Leaflet; `/metricas`; alarme de billing |
| D5 | Experimentos A + B na AWS; README com ADRs, tabela de falhas, gráficos; `terraform destroy` |
| D6–D7 | Sem código: ensaio da narrativa técnica, PEI, cases |

## 13. Fora de escopo (próximos passos no README)

Triagem/prioridade de chamados; hospital de destino; trânsito por hora; ECS Fargate;
React + WebSocket (endpoint `/ws/estado` já existe); ML — previsão de demanda por
zona×hora para reposicionamento e política de despacho aprendida, alimentados pelo event
log (interface `Politica` aceita uma `PoliticaML` sem mudar o resto).

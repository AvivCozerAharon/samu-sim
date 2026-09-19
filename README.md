# samu-sim

Simulador **distribuído** de despacho de ambulâncias no Rio de Janeiro, construído como
ferramenta de apoio à decisão: *qual política de despacho reduz o tempo de resposta na Zona
Oeste?* e *a partir de quantas ambulâncias o ganho é marginal?*

Chamados sintéticos (proporcionais à população por bairro, com picos de manhã e à noite) entram
numa fila **SQS**; N **despachantes** concorrentes escolhem a ambulância por uma política plugável e
disputam a reserva com **lock otimista** no **DynamoDB**; **workers** simulam o deslocamento pela
malha viária real (OSRM) em tempo acelerado; um **reaper** recupera ambulâncias de workers mortos;
uma **API** expõe métricas e um console ao vivo. Mesmo código roda em memória (1 processo), em
`docker compose` com LocalStack, e numa EC2 com SQS/DynamoDB/S3 reais via Terraform.

## Resultados

![política × zona](docs/img/a_politicas_p90_zona.png)
![tamanho da frota](docs/img/b_frota_p90.png)

*24 h simuladas, 600 chamados/dia (≈ os 592/dia reais do SAMU-RJ), 3 seeds, 165 bairros do Censo
2022, 43 bases reais, tempos do OSRM, ciclo com transporte ao hospital. `scripts/experimentos.py` →
`docs/experimentos/resultados.json`; calibração e fontes em [`docs/calibracao.md`](docs/calibracao.md).*

| A · política (73 ambulâncias = frota real) | P50 | P90 | P90 Barra | P90 **Oeste** |
|---|---|---|---|---|
| `mais_proxima` (linha reta) | 7,5 min | 16,5 min | 22 | **16** |
| `menor_eta` (malha viária) | 7,6 min | 16,0 min | 22 | **12** |
| `menor_eta_cobertura` (não esvaziar base) | 8,9 min | 18,4 min | 24 | 15 |

| B · frota (`menor_eta`) | 20 | 30 | 40 | 50 | **65** | 80 |
|---|---|---|---|---|---|---|
| P90 | 404 min | 406 | 223 | 127 | **17,9** | 15,0 |
| na fila ao fim do dia | 1045 | 757 | 393 | 155 | 0 | 0 |

**Os insights:**

- **A frota real está no lugar certo.** Com o ciclo completo (deslocamento + 20–30 min no local +
  transporte ao hospital + entrega), 50 ambulâncias colapsam ao longo do dia (155 na fila) e o joelho
  fica em ~65; o SAMU-RJ opera 73 — dentro da faixa estável, com P90 ≈ 16 min. Bater 15 min exige ~80.
- **A política paga na Zona Oeste.** Despachar pela linha reta custa 4 min de P90 lá (16 → 12 com a
  malha viária), porque o Maciço da Pedra Branca e a baía de Sepetiba tornam a "mais próxima" enganosa;
  no resto da cidade a diferença some. Em regime saturado (50 ambulâncias) a diferença era de 40 → 17 min.
- **"Não esvaziar a base" piorou.** A política com penalidade de cobertura manda uma ambulância mais
  longe para preservar a base — e o custo de resposta supera o ganho de cobertura. Um resultado negativo
  útil: a intuição estava errada, e só a medição mostrou.

**Validação distribuída:** o mesmo cenário rodado na AWS — EC2 com 6 containers, SQS e DynamoDB
reais — reproduziu o modelo em memória com < 2 % de diferença (`scripts/experimento_aws.sh`).

## Decisões de arquitetura (e o que mudou)

| Decisão | Por quê | O que aprendi |
|---|---|---|
| Tempo real acelerado (fator 1–200) em vez de simulação a eventos discretos | os problemas de concorrência têm que existir de verdade | o relógio distribuído é a parte mais traiçoeira: wall-clock salta (VM), então cada serviço sincroniza uma vez e avança com `monotonic` |
| SQS + DynamoDB desde o dia 1 (LocalStack) | um só código local e na AWS | SQS *standard* é at-least-once e sem ordem: idempotência por chamado + máquina de estados com versão resolveram |
| Lock otimista (`ConditionExpression` em `status` e `versao`) | N despachantes disputam a mesma ambulância | corridas perdidas são contadas (`reserva_falhou`), nunca escondidas |
| Heartbeat + reaper em vez de lease/lock distribuído | simples e observável | o reaper expôs 2 bugs (heartbeat na reserva; mensagem antiga após reatribuição) |
| Roteador com 3 implementações (haversine → OSRM → matriz) | funcionar no dia 1, medir depois | a reta subestima o P90 da Zona Oeste em 22%; `/table` em lote resolveu o gargalo de 40 `/route` por despacho |
| Métricas a partir do event log JSONL | uma fonte de verdade; vira dataset | o mesmo log alimenta o feed do console, o `analisar_rodada.py` e os experimentos |
| EC2 t3.micro + compose (não Fargate) | custo zero | o build na instância atrasa o gerador ~30 min sim: chamados "do passado" precisam ser descartados |

## O que eu faria diferente / próximos passos

- **Relógio lógico** (ticks) em vez de tempo real acelerado: reprodutibilidade exata e rodadas
  em segundos; custa uma barreira de sincronização entre serviços.
- **Fargate + ALB** no lugar da EC2 única; **WebSocket + React** no lugar do polling.
- **Dados reais** do Data.Rio (bairros/UPAs/SAMU) no lugar dos 19 bairros e 10 bases-proxy.
- **Machine learning sobre o event log**: previsão de demanda por zona × hora para
  *reposicionar* ambulâncias livres (a `Politica` é uma interface; uma `PoliticaML` entra sem
  tocar no resto); e triagem/prioridade de chamados.
- Experimento C: onde abrir 1 base nova para maximizar a queda do P90 na Zona Oeste.

---

Spec: `docs/superpowers/specs/2026-09-18-samu-sim-design.md` · planos por dia em `docs/superpowers/plans/`.

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
o que valida usá-la na AWS.

**Gargalo medido:** `menor_eta` avalia todas as candidatas; 40 chamadas `/route` = 210 ms
reais = 17 min *simulados* a fator 5000 (a primeira comparação saiu com P50 de 128 min por
isso). Solução: `Roteador.etas_de(origens, destino)` em lote — 1 chamada `/table` = 34 ms.

## AWS (D4 — EC2 + SQS + DynamoDB + S3 via Terraform)

Mesmo código, sem LocalStack: `docker-compose.aws.yml` numa **EC2 t3.micro** falando com
SQS, DynamoDB e S3 reais pelo *instance profile* (nenhuma credencial na máquina). Tudo criado
por Terraform em `infra/` (15 recursos): filas, tabelas on-demand, bucket de logs, role/perfil
IAM com permissão só nesses recursos, security group com 22 e 8000 abertos só para o seu IP,
e a instância com *user-data* que instala Docker, clona o repo e sobe o compose.

```bash
aws configure                              # usuario IAM proprio; regiao us-east-1
cp infra/terraform.tfvars.example infra/terraform.tfvars   # seu IP /32, chave ssh publica, repo
bash scripts/deploy.sh                     # apply + espera a API (~4 min)
bash scripts/atualizar_ec2.sh              # git pull + rebuild na instancia (RESET=1 zera a rodada)
bash scripts/coletar_logs_ec2.sh           # event log -> S3 -> logs/
terraform -chdir=infra destroy -auto-approve   # no fim da sessao
```

Custo: t3.micro ≈ US$ 0,01/h; SQS/DynamoDB/S3 dentro do free tier permanente. Dois orçamentos
(gasto zero e US$ 10/mês) alertam por e-mail.

O que o deploy real encontrou: o build da imagem atrasa o gerador ~30 min simulados em relação
ao checkpoint do bootstrap, e chamados "do passado" saíam com espera fictícia (P90 de 51 min);
o gerador agora descarta chamados já vencidos ao iniciar (`chamados_pulados`).

## Console ao vivo

`GET /` serve o console: relógio simulado, P50/P90 por zona contra a meta de 15 min, frota por
estado, fila, controle de velocidade/pausa, mapa com ambulâncias se movendo (posição interpolada
entre base e chamado por `despachado_em`/`chegada_prevista_em`), feed de eventos de todos os
serviços (`GET /eventos` lê os JSONL da rodada) e **modo seguir**: clique num chamado ou em
"Seguir o próximo chamado" para acompanhar a linha do tempo dele (aberto → despachada → a
caminho → no local → concluído) com a câmera enquadrando. Estado também por WebSocket em
`/ws/estado`. Sem Docker: `python scripts/dev_api.py` roda tudo em memória num processo.

## Estado

- [x] D1: núcleo em memória (relógio, fila, repositório com lock otimista, políticas, serviços, métricas)
- [x] D2: docker compose + LocalStack (SQS/DynamoDB), reaper, análise de rodada
- [x] D3: OSRM + política `menor_eta` real + matriz pré-computada
- [x] D4: Terraform + EC2 + mapa (console ao vivo, modo seguir)
- [x] D5: experimentos A (políticas) e B (frota), validação na AWS, gráficos
- [x] D6: dados reais (Censo 2022, hospitais/UPAs, estatísticas do SAMU-RJ), gravidade, ciclo com hospital

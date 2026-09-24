# samu-sim

Simulador distribuído de despacho de ambulâncias no Rio de Janeiro.

Eu queria estudar sistemas distribuídos e AWS num problema que não fosse mais um CRUD. Despacho de
ambulância serve bem: a ambulância só pode estar num lugar, vários despachantes competem pela mesma,
e o processo que está cuidando dela pode morrer no meio do atendimento. Só que não dá para testar
política de despacho na rua, porque o paciente está dentro. Então simulei a cidade.

Acabou virando uma ferramenta de decisão. São três perguntas, cada uma respondida com intervalo de
confiança: qual política de despacho reduz o tempo de resposta na Zona Oeste, a partir de quantas
ambulâncias o ganho fica marginal, e onde abrir a próxima base.

Como funciona. Chamados sintéticos, proporcionais à população de cada bairro e com picos por volta de
meio-dia e das 20 h, entram numa fila SQS. N despachantes concorrentes escolhem a ambulância por uma
política plugável e disputam a reserva com lock otimista no DynamoDB. Workers simulam o deslocamento
pela malha viária real (OSRM) em tempo acelerado. Um reaper recupera as ambulâncias de workers que
morreram. Uma API expõe as métricas e um console ao vivo.

O mesmo código roda de três jeitos: tudo em memória num processo só, em `docker compose` com
LocalStack, e numa EC2 com SQS, DynamoDB e S3 reais subidos por Terraform.

## Resultados

> **Em refação (D10).** As tabelas abaixo são da calibração anterior: 600 chamados/dia (o número
> incluía transferências entre hospitais; a demanda de emergência é ~490/dia) e relógio a 2000×,
> velocidade em que o próprio simulador fica atrás do relógio e infla o P90 em 1–2 min (a mesma
> seed deu P90 de 16,9, 17,1 e 21,7 min; a 500×, 14,9 e 15,0). Os scripts já usam 490/dia e 500×;
> falta rodar de novo e atualizar os números.

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

| B · frota (`menor_eta`, com trânsito e reposicionamento) | 20 | 30 | 40 | 50 | **65** | 80 |
|---|---|---|---|---|---|---|
| P90 | 312 min | 335 | 210 | 102 | **23,2** | 20,0 |
| na fila ao fim do dia | 1005 | 653 | 382 | 68 | 0 | 0 |

*(sem trânsito, D6: 65 → 17,9 min e 80 → 15,0 min; o trânsito de pico custa ~5 min de P90 em qualquer frota)*

O que eu tirei disso:

A frota real está dimensionada corretamente, e ainda assim a meta de 15 min não é alcançável com ela.
Com o ciclo completo (deslocamento, 20 a 30 min no local, transporte ao hospital, entrega) e trânsito
de pico, 50 ambulâncias colapsam ao longo do dia e o joelho da curva fica em torno de 65. O SAMU-RJ
opera 73, dentro da faixa estável, com P90 de uns 21 min. Nem 80 ambulâncias batem os 15 min com
trânsito ligado; sem trânsito, batem. O problema do P90 no Rio é mais via do que frota.

A política de despacho só faz diferença na Zona Oeste. Despachar pela linha reta custa 4 min de P90
lá (16 → 12 quando passei a rotear pela malha viária), porque o Maciço da Pedra Branca e a baía de
Sepetiba tornam a "ambulância mais próxima" enganosa. No resto da cidade a diferença some.

O terceiro resultado é o que eu não esperava. A política de "não esvaziar a base" piorou: ela manda
uma ambulância mais longe para preservar cobertura, e o custo de resposta supera o ganho. Eu estava
convencido do contrário quando implementei, e só a medição mostrou.

Validação distribuída (D5, modelo anterior): rodei o mesmo cenário na AWS, numa EC2 com 6 containers
e SQS e DynamoDB reais, contra o modelo em memória. Com 1 seed, 6 h simuladas, 50 ambulâncias e 19
bairros, deu P90 29,7 contra 29,5 min (menos de 1 % de diferença) e P50 8,3 contra 7,8 min (uns 6 %).
Está em `scripts/experimento_aws.sh`. Não refiz depois dos dados reais do D6, e é o próximo teste que
eu quero repetir.

## Realismo operacional (D8): o que cada correção do modelo mudou

![realismo](docs/img/e_realismo.png)

Três correções, medidas uma a uma na frota real de 73 (3 seeds, 24 h):

| variante | P50 | P90 | P90 vermelhos |
|---|---|---|---|
| ambulância despachável ao liberar no hospital (sempre ligado) | 7,3 min | 15,4 min | 16,2 min |
| + reposicionamento por previsão de demanda | 7,4 | 15,1 | 16,3 |
| + trânsito por hora | 9,5 | 20,9 | 21,8 |
| + ambos | 10,0 | 21,3 | 21,0 |

O maior erro do modelo era a ambulância só voltar a ser despachável quando chegava na base. Ela ficava
ociosa num hospital que fica exatamente onde a demanda está. Passando a despachá-la ao ser liberada, o
P90 com 73 caiu de 16,0 para 15,4 min e o joelho da curva de frota desceu junto.

O reposicionamento foi mais frustrante. A ideia é mandar a ambulância liberada para a base de maior
demanda prevista nas próximas 2 h, dentro de 8 km, e só se a pressão lá for pelo menos 1,5 vez a da
base atual. Efeito neutro: −0,3 min, dentro do ruído. E a primeira versão, sem limiar e com raio de
15 km, piorava 1,3 min, porque o custo do deslocamento comia o ganho. Com 43 bases já bem distribuídas
sobra pouco para reposicionar. O modelo de demanda em si é honesto (treina só com `chamado_criado` e
aprende os picos de 12 h e 19 h por zona), mas a decisão que ele alimenta não move o ponteiro aqui.

Trânsito é a correção que mais muda a conclusão. Um fator por hora sobre o tempo de via livre do
OSRM, uns 50 % a mais nos picos, custa +5,5 min de P90, e com ele a meta de 15 min sai do alcance
de qualquer frota que eu testei.

## Prioridade e turnos que aprendem (D7)

![turnos](docs/img/c_turnos.png)

Cada chamado nasce com a classificação do regulador: vermelho 10 %, amarelo 30 %, verde 60 %. São
três filas SQS, o despachante só desce de nível quando a de cima está vazia, e o reaper devolve o
chamado à fila da prioridade dele. Com isso a métrica que importa deixa de ser o P90 geral e passa a
ser o P90 dos vermelhos. O objetivo dos experimentos vira
`J = 3·P90(vermelho) + P90(amarelo) + ½·P90(verde)`.

`scripts/turnos.py` roda o dia simulado repetidamente. A cada turno o otimizador lê o
resultado e escreve o diagnóstico em linguagem simples — *"Zona Barra tem o pior resultado: P90 21 min;
UPA Paciência está ociosa 98 % do tempo com 2 ambulâncias; mover 1 ambulância de UPA Paciência para
UPA Jacarepaguá (cobre 607 mil hab. num raio de 5 km)"* — aplica o movimento, mede, e mantém se J
caiu pelo menos 2 %. Se não caiu, desfaz. É hill-climbing com memória do que já tentou.

Em 10 turnos com a frota real de 73: J 80,9 → 72,6, uma queda de 10 %. O P90 global foi de 16,4 para
14,2 min e o dos vermelhos de 19,0 para 17,2. Dos 9 movimentos propostos, 3 foram aceitos (Paciência
e Vila Kennedy para a UPA Jacarepaguá, Evandro Freire para o Lourenço Jorge) e 6 rejeitados. A Barra
continua sendo a zona pior servida, com 4 bases para 460 mil habitantes, e isso é o que me fez
concluir que o próximo ganho vem de uma base nova, não de realocação.

A alocação vencedora fica em `dados/alocacao.json` e o bootstrap a usa na AWS; o console mostra a
trajetória (`GET /turnos`).

Isto não é aprendizado de máquina, e eu faço questão de escrever isso. É otimização guiada por dados:
cada decisão tem uma justificativa que dá para narrar e auditar.

Onde ML entraria de verdade são dois lugares. Previsão de demanda por zona e hora sobre o event log,
para reposicionar ambulâncias livres ao longo do dia. Só que com dados sintéticos o modelo
aprenderia a curva que eu mesmo escrevi, então o que vale aqui é o pipeline, não o modelo; com a
série real do SAMU-RJ ele aprenderia padrão real. E triagem automática a partir da ligação, que exige
dados reais de chamadas.

Aprender a política de despacho com aprendizado por reforço seria a versão vistosa, e é a que eu não
faria: caro de treinar num simulador em tempo real acelerado, e o resultado seria uma política que eu
não consigo explicar para quem decide o orçamento.

## Onde abrir a próxima base (D9 — experimento D)

![expansão](docs/img/d_expansao.png)

O otimizador de turnos (D7) mostrou que **realocar** a frota não resolve a Barra (P90 ≈ 19 min com a
alocação otimizada). A pergunta seguinte é a que a prefeitura faz de verdade: *com orçamento para
2 ambulâncias, vale mais abrir uma base nova ou reforçar uma existente — e onde?*

Método, em dois estágios pra caber em 30 min de máquina:

1. **Heurística barata**: candidatas = centróides dos bairros a mais de 5 km de qualquer base, ordenados
   pela demanda populacional descoberta (`samu_sim/expansao.py`). Dá 10 candidatas — todas na Barra
   e na Zona Oeste (Guaratiba, Recreio, Itanhangá, Vargens…).
2. **Triagem** (1 seed, 12 h) de cada candidata com +2 ambulâncias na base nova, e **final** (5 seeds,
   24 h) das 4 melhores contra dois cenários com as mesmas seeds: a **frota atual** (73, alocação
   otimizada) e um **controle** — as mesmas +2 ambulâncias na base existente mais pressionada
   (UPA Engenho Novo). Sem o controle, o ganho seria confundido com "mais frota".

| cenário (+2 ambulâncias) | P90 geral | P90 Barra | Δ P90 vs frota atual [IC 95 %] | Δ vs controle |
|---|---|---|---|---|
| frota atual (73) | 14,1 | 19,2 | — | — |
| +2 em UPA Engenho Novo (controle) | 14,1 | 19,4 | −0,1 [−0,5, +0,3] n.s. | — |
| **base nova em Vargem Pequena** | **13,2** | **17,3** | **−0,9 [−1,3, −0,5]** | −0,8 [−1,1, −0,6] |
| base nova no Recreio | 13,3 | 17,3 | −0,9 [−1,3, −0,5] | −0,8 [−0,9, −0,7] |
| base nova em Pedra de Guaratiba | 13,5 | 19,3 | −0,6 [−1,2, −0,2] | −0,6 (Oeste −1,1, Barra 0) |
| base nova em Vargem Grande | 13,6 | 17,4 | −0,6 [−1,0, −0,2] | −0,5 [−0,7, −0,3] |

A leitura que eu faço:

Reforçar uma base existente não muda nada. São −0,1 min e o intervalo contém zero. Faz sentido com o
experimento B: o sistema já está na faixa estável, e ambulância extra onde já há cobertura vira
ociosidade.

Uma base nova nas Vargens ou no Recreio reduz o P90 da cidade em uns 0,9 min e o da Barra em uns
2 min, de 19,2 para 17,3. O intervalo exclui zero mesmo com apenas 5 seeds, e isso só é possível
porque a comparação é pareada por seed. Vale dizer que Vargem Pequena e Recreio empatam: os
intervalos se sobrepõem quase inteiros, então o que dá para afirmar é que as duas batem o controle,
não que uma bate a outra.

Pedra de Guaratiba é um caso diferente — ajuda a Zona Oeste (−1,1) e não ajuda a Barra. Candidatas
diferentes atacam zonas diferentes, e aí a escolha deixa de ser técnica: depende de qual zona a
Secretaria quer priorizar.

Nenhuma delas leva a Barra à meta de 15 min, que é o mesmo veredito do D8.

Reproduzir: `python scripts/experimento_d.py` (≈ 28 min; `--rapido` em 5 min) → `docs/experimentos/expansao.json`,
`python scripts/graficos.py`. O console mostra as finalistas na seção "Onde abrir a próxima base" e
as candidatas no mapa.

## Cenários com intervalo de confiança (D9)

Até o D8 cada comparação era uma média de 3 seeds, e isso não serve: não dá para distinguir efeito de
ruído. Quem decide o orçamento precisa ouvir "abrir uma base no Recreio reduz o P90 em 2,0 ± 0,3 min".

`samu_sim/estatistica.py` faz o IC de 95 % por bootstrap, em Python puro e determinístico, e a
diferença pareada por seed. O pareamento é o que resolve o problema: os dois cenários rodam com as
mesmas seeds, então o mesmo dia de chamados acontece nos dois mundos, a variância do gerador cancela,
e o intervalo da diferença fica muito mais estreito do que comparar duas médias independentes. É
common random numbers. Só chamo de significativo quando o intervalo não contém zero, e com pelo menos
3 seeds.
- `samu_sim/cenarios.py` — um `Cenario` descreve frota, política, alocação por base, bases extras,
  trânsito e reposicionamento; `executar` roda N seeds e resume com IC; `comparar` faz a diferença
  pareada por métrica (P90, P50, P90 vermelhos, pendentes, P90 por zona).
- API: `POST /cenarios` enfileira um job (uma simulação em memória por vez, numa thread da API),
  `GET /cenarios/{id}` devolve o resultado, `GET /cenarios/{a}/comparar/{b}` a diferença pareada.
  O console tem a seção **"E se…?"**: escolhe frota/política/seeds/duração, submete e seleciona dois
  cenários concluídos pra ver a diferença com IC.
- CLI: `python scripts/cenarios.py --base '{"nome":"73"}' --alt '{"nome":"80","n_ambulancias":80}'`.
- Armadilha medida: o relógio acelerado precisa de CPU. Na t3.micro, o mesmo cenário a fator 3000 deu
  P90 44 min onde o correto (local, ou fator 500) é 19 — o processamento fica pra trás do relógio e os
  tempos saem inflados. Por isso `CENARIOS_FATOR_MAX` (500 na AWS): um job de 5 seeds × 24 h leva ~15 min lá.

## Caos e invariantes (D11): o sistema se mantém correto quando tudo dá errado?

O objetivo do projeto é o sistema distribuído, então o resultado que mais importa para mim não é o
P90: é conseguir mostrar que nenhuma falha deixa o estado errado.

- A fila caótica (`samu_sim/infra/fila_caotica.py`) tem a mesma interface da `Fila` e injeta, com
  seed, as falhas que o SQS e os processos permitem: mensagem duplicada, atrasada, fora de ordem,
  ack perdido (consumidor morreu depois de processar) e processo que morre ao publicar.
- `derrubar()` e `reviver()` simulam o `docker restart`, em que a memória dos ciclos se perde.
  `pausar()` e `retomar()` simulam uma pausa de GC ou uma VM travada: a memória fica, e o ciclo
  antigo tenta continuar de onde parou.
- O verificador (`samu_sim/invariantes.py`) só faz checagem exata. A ordem entre logs de processos
  diferentes é ambígua, então a sequência de cada ambulância é ordenada pela versão do registro, que
  o lock otimista incrementa:

| | invariante |
|---|---|
| I1 | cada ambulância segue a máquina de estados, um chamado por vez |
| I2 | cada chamado é concluído exatamente uma vez |
| I3 | depois de drenar, nenhum chamado ficou sem atendimento |
| I4 | depois de drenar, nenhuma ambulância ficou presa |
| I5 | cada chamado recebe uma ambulância, mais uma por vez que o reaper o devolveu |

`python scripts/caos.py --rodadas 20` roda o sistema inteiro sob caos (12 h simuladas por rodada),
desliga as falhas, espera drenar e julga. Antes das correções abaixo eu tinha 1 rodada limpa em 4.
Depois, 20 em 20 — com centenas de duplicatas, atrasos, acks perdidos, processos mortos ao publicar
e quedas de worker em cada rodada.

O que o caos achou (e que nenhum teste unitário tinha pegado):

| bug | como aparecia | correção |
|---|---|---|
| **Worker reiniciado segurava ambulâncias para sempre** | I4: ambulância presa em `no_local` | o heartbeat listava todas as não disponíveis do worker no banco; o worker novo mantinha vivas as do ciclo que morreu com o processo anterior. Agora só fala pelas que têm ciclo em voo *neste* processo (e sai um scan por heartbeat) |
| **Gerador reiniciado perdia chamados** | I3: chamado `nunca_salvo` | ao subir, ele pulava os chamados atrasados > 60 s (regra feita para a primeira subida). Num restart, retoma sem pular |
| **Gerador reiniciado sobrescrevia chamado despachado** | I5 (janela estreita) | `criar_chamado` condicional (`attribute_not_exists(id)`): nunca sobrescreve |
| **Ciclo pausado passava pelo lock otimista** | I1: `chegou` com a ambulância livre | o ciclo relia a versão *atual* do banco antes de cada transição; depois de uma pausa em que o reaper reatribuiu a ambulância, o ciclo zumbi a movia. Agora cada ciclo carrega a versão da sua última transição, que funciona como fencing token (`ciclo_obsoleto`) |
| **Despachante mandava trabalho para worker morto** | no mapa: ambulância indo e voltando | o reaper liberava a ambulância, o despachante a reservava de novo (a mais próxima) e ela ficava presa outra vez. Agora os workers anunciam o próprio heartbeat e o reaper **passa as ambulâncias de um worker morto para um vivo**, e reequilibra quando ele volta |
| **Reaper teletransportava a ambulância para a base** | no mapa: salto para trás | libera onde ela estaria, pela mesma interpolação do mapa (partida, destino, horários previstos) |
| **Log do despacho sumia se o processo morresse ao publicar** | I1 (falso positivo) | o evento `despachada` descreve a escrita no banco, então é gravado antes de publicar |

### Laboratório de falhas no console

`python scripts/dev_api.py` (73 ambulâncias, 490 chamados/dia, trânsito ligado) abre o console com
a aba **Laboratório**: liga as falhas da fila com taxas ajustáveis, derruba ou congela workers,
põe mais despachantes disputando a frota, marca no mapa uma **ocorrência com várias vítimas** (um
chamado por vítima, no mesmo ponto e hora: a disputa pelas ambulâncias próximas aparece sozinha) e
mostra cada falha injetada ao lado do mecanismo que a resolveu. "Drenar e verificar" desliga o caos,
acelera o relógio e julga as cinco invariantes. No livro de ocorrências, o que você injeta aparece
como **falha** e o que o sistema fez como **sistema**. Heartbeat e reaper usam 2 s e 6 s reais no
laboratório, para a recuperação acontecer na frente de quem assiste.

## Consistência sob falha (D10): o que uma revisão do código achou

Cinco pontos em que duas escritas concorrentes, ou um processo morrendo no meio, deixavam o estado
errado. Nenhum aparecia nos experimentos em memória; todos apareceriam em produção.

| problema | onde | correção | teste |
|---|---|---|---|
| **Reaper devolvia chamado já redespachado.** Se a ambulância A travou e o chamado já tinha sido redespachado para B, o reaper voltava o chamado a PENDENTE e ele seria despachado de novo | `api/reaper.py` | só devolve se o chamado ainda for da ambulância liberada, com escrita condicional | `test_nao_devolve_chamado_ja_redespachado_para_outra_ambulancia` |
| **Escritas no chamado sem condição.** Despachante, worker e reaper gravavam o chamado inteiro (`put_item`); a última escrita apagava a outra | `infra/repositorio.py`, `infra/aws.py` | `salvar_chamado_se(c, status, ambulancia_id)`: `ConditionExpression` em status + dono, como já era nas ambulâncias. O worker que perde para o reaper encerra o ciclo (`chamado_retomado`) | `test_salvar_chamado_se_*`, `test_worker_para_o_ciclo_se_o_chamado_foi_retomado` |
| **Mensagem duplicada em corrida mandava duas ambulâncias.** Dois despachantes liam o mesmo chamado PENDENTE ao mesmo tempo e reservavam ambulâncias diferentes | `despachante/servico.py` | a gravação DESPACHADO é condicional a PENDENTE; quem perde desfaz a própria reserva (`despacho_duplicado_evitado`) | `test_mensagem_duplicada_em_corrida_desfaz_a_segunda_reserva` |
| **Inversão de prioridade.** Vermelho sem ambulância ficava invisível pelo visibility timeout (30 s reais) e, nesse intervalo, o despachante atendia verdes | `despachante/servico.py`, `infra/fila.py` | `Fila.adiar` (`ChangeMessageVisibility`): volta em 2 s; até lá o despachante não desce de prioridade | `test_sem_ambulancia_para_vermelho_segura_os_verdes_e_volta_rapido` |
| **Dual write no gerador.** Salvar o chamado e publicar na fila são duas escritas; morrer entre elas deixava um chamado que ninguém despacha | `gerador/servico.py`, `api/reaper.py` | outbox no próprio registro: `publicado=False` até a fila confirmar; o reaper republica o PENDENTE que continua sem publicar em duas passadas seguidas (duplicata é inofensiva, o despachante é idempotente) | `test_republica_pendente_que_nunca_foi_publicado_na_segunda_passada` |

E um limite que faltava: `POST /controle` aceitava qualquer fator, embora acima de ~2000 o próprio
simulador vire o gargalo (a 3000 na t3.micro, o P90 medido sobe de 19 para 44 min). Agora usa o mesmo
teto dos cenários (`CENARIOS_FATOR_MAX`: 2000 local, 500 na AWS) e recusa com 422.

## Decisões de arquitetura (e o que mudou)

| Decisão | Por quê | O que aprendi |
|---|---|---|
| Tempo real acelerado (fator 1–200) em vez de simulação a eventos discretos | os problemas de concorrência têm que existir de verdade | o relógio distribuído é a parte mais traiçoeira: wall-clock salta (VM), então cada serviço sincroniza uma vez e avança com `monotonic` |
| SQS + DynamoDB desde o dia 1 (LocalStack) | um só código local e na AWS | SQS *standard* é at-least-once e sem ordem: idempotência por chamado + máquina de estados com versão resolveram |
| Lock otimista (`ConditionExpression` em `status` e `versao`) | N despachantes disputam a mesma ambulância | corridas perdidas são contadas (`reserva_falhou`), nunca escondidas |
| Heartbeat + reaper em vez de lease/lock distribuído | simples e observável | o reaper expôs 2 bugs (heartbeat na reserva; mensagem antiga após reatribuição); um terceiro (devolver chamado já redespachado) foi corrigido no D10 com escrita condicional, que é o que um fencing token daria |
| Roteador com 3 implementações (haversine → OSRM → matriz) | funcionar no dia 1, medir depois | a reta subestima o P90 da Zona Oeste em 22%; `/table` em lote resolveu o gargalo de 40 `/route` por despacho |
| Métricas a partir do event log JSONL | uma fonte de verdade; vira dataset | o mesmo log alimenta o feed do console, o `analisar_rodada.py` e os experimentos |
| EC2 t3.micro + compose (não Fargate) | custo zero | o build na instância atrasa o gerador ~30 min sim: chamados "do passado" precisam ser descartados |

## O que eu faria diferente / próximos passos

A coisa que mais me incomoda é o relógio. Trocaria tempo real acelerado por relógio lógico, em ticks:
daria reprodutibilidade exata e rodadas em segundos, ao custo de uma barreira de sincronização entre
os serviços.

Trânsito real (COR ou Waze, por corredor e hora) no lugar do perfil estimado. É a variável que mais
muda a conclusão do projeto e a menos calibrada, o que é uma combinação ruim.

O problema técnico que eu mais quero atacar é preempção: desviar uma ambulância que está a caminho de
um verde para um vermelho a 2 min. Cancelar um ciclo em voo em outro processo é o melhor problema
distribuído que sobrou, e é o que quebra o meu modelo de condição por item — precisaria de transação.

Também na lista: Fargate e ALB no lugar da EC2 única, e WebSocket para métricas e eventos no console
(hoje `/metricas` e `/eventos` são polling, embora o estado já venha por WebSocket). Reposicionamento
com objetivo explícito — cobertura garantida por zona em vez de pressão relativa —, que agora dá para
avaliar com `scripts/cenarios.py` antes de mexer. Replay do event log, para reconstruir o estado em
qualquer instante. E frota heterogênea, com USA, USB, motolância e troca de plantão, que muda o que a
política pode decidir.

---

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
| Corrida entre despachantes | 2 réplicas + `FATOR=200` | `reserva_falhou` > 0 nos logs, nunca 2 `despachada` pro mesmo chamado (se a corrida for pela mesma mensagem duplicada: `despacho_duplicado_evitado`) |

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
por Terraform em `infra/` (17 recursos): 5 filas, 3 tabelas on-demand, bucket de logs, role/perfil
IAM com permissão só nesses recursos, security group com 22, 8000 e 8100 (a `mesa`) só para o seu IP,
e a instância com *user-data* que instala Docker, clona o repo e sobe o compose.

```bash
aws configure                              # usuario IAM proprio; regiao us-east-1
cp infra/terraform.tfvars.example infra/terraform.tfvars   # seu IP /32, chave ssh publica, repo
bash scripts/deploy.sh                     # apply + espera a API (~4 min)
bash scripts/atualizar_ec2.sh              # git pull + rebuild na instancia (RESET=1 zera a rodada)
bash scripts/coletar_logs_ec2.sh           # event log -> S3 -> logs/
terraform -chdir=infra destroy -auto-approve   # no fim da sessao
```

Custo: t3.micro ≈ US$ 0,01/h; SQS/DynamoDB/S3 dentro do free tier permanente. Alertas de orçamento
(AWS Budgets) não estão no Terraform: crie no console.

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
- [x] D7: filas por prioridade, otimizador de turnos (alocação por base), console de turnos
- [x] D8: despachável ao liberar, previsão de demanda + reposicionamento, trânsito por hora (ablação medida)
- [x] D9: cenários com IC (bootstrap, diferença pareada por seed, `POST /cenarios`), experimento D (onde abrir a próxima base)
- [x] D10: demanda recalibrada sem transferências (490/dia), zonas por Área de Planejamento, consistência sob falha (escrita condicional do chamado, outbox, sem inversão de prioridade, teto do fator)
- [x] D11: fila caótica, verificador de invariantes (`scripts/caos.py`), fencing por versão, rebalanceamento de ambulâncias entre workers, laboratório de falhas no console, trânsito ligado por padrão, console redesenhado
- [ ] refazer os experimentos A–E a 490/dia e 500× e atualizar as tabelas

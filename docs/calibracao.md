# Calibração do modelo — o que é dado real, o que é estimado, e de onde veio

Atualizado em 2026-09-19 (D6).

## Bairros e população — **dado real**

- 165 bairros do município com população do **Censo 2022** (dados preliminares por setor censitário
  agregados pelo IPP) e geometria: serviço ArcGIS da prefeitura
  `pgeo3.rio.rj.gov.br/arcgis/rest/services/Censo/Limites_administrativos_Censo_2022/MapServer/2`,
  publicado no [Data.Rio](https://www.data.rio/datasets/fd354740f1934bf5bf8e9b0e2b509aa9_2/about).
  Bruto em `dados/fontes/censo2022_bairros_geo.json`; `scripts/preparar_dados.py` gera `dados/bairros.csv`.
- População total: 6.211.223. Centróide de cada bairro = centróide do maior anel do polígono.
- Zonas (Centro/Sul/Norte/Barra/Oeste) = agrupamento das 33 regiões administrativas por Área de
  Planejamento (`ZONA_POR_RA` no script). Paquetá (ilha) fica com demanda zero.

## Bases — **dado real (localização parcialmente estimada)**

- 12 hospitais municipais de emergência e 31 UPAs, da
  [SMS-Rio](https://saude.prefeitura.rio/urgencia-e-emergencia/hospitais/) e
  [UPAs](https://saude.prefeitura.rio/urgencia-e-emergencia/upas/). `scripts/geocodificar_bases.py`.
- 21 unidades geocodificadas pelo endereço (Nominatim/OpenStreetMap); 22 sem endereço público
  ficam no centróide do bairro (`origem` no CSV). O SAMU-RJ declara **40 bases descentralizadas**;
  a lista exata não é pública, então hospitais + UPAs são o *proxy* (é onde as ambulâncias
  ficam e para onde levam pacientes).
- Frota real: **73 ambulâncias + 30 motolâncias** (SAMU-RJ, 2024). Motolâncias não são modeladas.

## Demanda — **calibrado com estatística real**

- Volume: **216 mil envios de ambulância em 2024** ≈ 592/dia → `chamados_por_dia = 600`
  ([Diário do Rio](https://diariodorio.com/samu-do-rio-registra-mais-de-660-mil-chamadas-e-216-mil-atendimentos-em-2024/)).
  Das 665 mil ligações, 4,6 % eram trote (não modelado: só envios).
- Distribuição espacial: população × `fator_demanda`. Ranking real 2024: **Campo Grande (12.614 ≈ 5,8 %),
  Santa Cruz, Centro**. Com população pura o Centro (23,6 mil residentes) fica fora do top 20; o
  fator 9,5 (população flutuante: trabalho, comércio, população de rua) o coloca em 3º com ~3,5 %.
  Resultado: Campo Grande 5,5 %, Santa Cruz 3,9 %, Centro 3,5 %. **Estimativa**: um único fator
  calibrado num único dado; o ideal seria a série de chamados por bairro, que não é pública.
- Curva horária: dois picos, ~12 h e ~20 h, vale de madrugada — de
  [análise da configuração do SAMU de Ribeirão Preto (SciELO)](http://www.scielo.br/j/gp/a/PFMBhXWHkJhL5z64KW44pJP/?lang=pt).
  Forma exata (`PESOS_HORA`) é **estimada** a partir da descrição.
- Ponto do chamado: uniforme num raio de 1,5 km do centróide do bairro (**estimativa**).

## Gravidade e tipo — **calibrado com literatura**

- `prioridade`: vermelho 10 % / amarelo 30 % / verde 60 %. Literatura: envios de suporte avançado
  são minoria; a divisão exata é **estimativa** compatível com a classificação do regulador.
- `tipo`: trauma 30 % de dia e 48 % entre 22 h e 4 h (média ≈ 35 %); clínico o restante. Perfis de
  atendimento do SAMU em capitais: 48–60 % clínicos, ~33 % trauma
  ([SciELO](https://www.scielo.br/j/rgenf/a/9pJCzdb5cBGwymtLxHSf8QK/?lang=pt)). Ainda **não influencia**
  o despacho (fica para o D7: fila por prioridade).

## Ciclo da ambulância — **calibrado com literatura**

- Deslocamento: tempos do OSRM na malha OSM do Rio (extrato BBBike), perfil `car`, sem trânsito
  (**subestima horário de pico**).
- No local: 20–30 min (uniforme). Transporte ao **hospital de emergência mais próximo** (12
  hospitais), entrega 8–15 min, depois retorno à base — durante o retorno a ambulância **não** é
  despachável (**simplificação**; na prática pode ser).
- Meta usada nos gráficos: P90 ≤ 15 min (referência comum de serviços de emergência; o SAMU-RJ
  não publica meta oficial).

## O que continua sintético

Sequência de chamados (seed), pontos dentro do bairro, gravidade por chamado, tempos no local.
Com a série real de chamados (data, hora, bairro, classificação) do SAMU-RJ o gerador seria
substituído por reamostragem dos dados — o resto do sistema não muda.

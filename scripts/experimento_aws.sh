#!/usr/bin/env bash
# Roda um cenario na EC2 (stack distribuida real) e traz o event log para analise.
# Uso: bash scripts/experimento_aws.sh <politica> <n_ambulancias> <duracao_real_seg> [fator] [chamados_por_dia] [seed]
# Ex.: bash scripts/experimento_aws.sh menor_eta 50 360 60 600 42   # 6 min reais = 6 h simuladas
set -euo pipefail
POL=$1; NAMB=$2; DUR=$3; FATOR=${4:-60}; CPD=${5:-600}; SEED=${6:-42}
cd "$(dirname "$0")/.."
IP=$(terraform -chdir=infra output -raw ip_publico)
BUCKET=$(terraform -chdir=infra output -raw bucket_logs)
RODADA="exp-${POL}-${NAMB}-$(date +%H%M%S)"
echo ">> $RODADA na EC2 $IP: fator $FATOR, ${DUR}s reais"
ssh -o StrictHostKeyChecking=accept-new ec2-user@"$IP" "cd /opt/samu-sim \
  && sudo docker compose -f docker-compose.aws.yml --env-file .env down >/dev/null 2>&1 \
  && sudo sed -i -e 's/^POLITICA=.*/POLITICA=$POL/' -e 's/^N_AMBULANCIAS=.*/N_AMBULANCIAS=$NAMB/' \
       -e 's/^FATOR=.*/FATOR=$FATOR/' -e 's/^CHAMADOS_POR_DIA=.*/CHAMADOS_POR_DIA=$CPD/' \
       -e 's/^RODADA_ID=.*/RODADA_ID=$RODADA/' .env \
  && (grep -q '^SEED=' .env && sudo sed -i 's/^SEED=.*/SEED=$SEED/' .env || echo SEED=$SEED | sudo tee -a .env >/dev/null) \
  && sudo docker compose -f docker-compose.aws.yml --env-file .env run --rm -e RESET=1 bootstrap | tail -1 \
  && sudo docker compose -f docker-compose.aws.yml --env-file .env up -d >/dev/null 2>&1 \
  && sleep $DUR \
  && sudo docker compose -f docker-compose.aws.yml --env-file .env stop >/dev/null 2>&1 \
  && sudo aws s3 sync logs/$RODADA s3://$BUCKET/$RODADA --quiet && echo '>> log no S3'"
mkdir -p logs && aws s3 sync "s3://$BUCKET/$RODADA" "logs/$RODADA" --quiet
echo ">> logs/$RODADA"
.venv/Scripts/python scripts/analisar_rodada.py "logs/$RODADA"

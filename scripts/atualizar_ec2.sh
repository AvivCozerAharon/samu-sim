#!/usr/bin/env bash
# Atualiza o codigo na EC2 (git pull + rebuild). RESET=1 zera a rodada. Uso: bash scripts/atualizar_ec2.sh [RESET=1]
set -euo pipefail
cd "$(dirname "$0")/../infra"
IP=$(terraform output -raw ip_publico)
ssh -o StrictHostKeyChecking=accept-new ec2-user@"$IP" "cd /opt/samu-sim && sudo git pull -q \
  && if [ '${RESET:-0}' = '1' ]; then sudo docker compose -f docker-compose.aws.yml --env-file .env down; \
       sudo sed -i \"s/^RODADA_ID=.*/RODADA_ID=aws-\$(date +%Y%m%d-%H%M)/\" .env; \
       sudo docker compose -f docker-compose.aws.yml --env-file .env run --rm -e RESET=1 bootstrap; fi \
  && sudo docker compose -f docker-compose.aws.yml --env-file .env up --build -d"
echo ">> http://$IP:8000/"

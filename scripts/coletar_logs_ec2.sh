#!/usr/bin/env bash
# Copia o event log da EC2 para logs/ e para o bucket S3. Uso: bash scripts/coletar_logs_ec2.sh
set -euo pipefail
cd "$(dirname "$0")/.."
IP=$(terraform -chdir=infra output -raw ip_publico)
BUCKET=$(terraform -chdir=infra output -raw bucket_logs)
ssh ec2-user@"$IP" "cd /opt/samu-sim && sudo aws s3 sync logs s3://$BUCKET/ --quiet && echo enviado"
mkdir -p logs && aws s3 sync "s3://$BUCKET/" logs/ --quiet && ls logs/

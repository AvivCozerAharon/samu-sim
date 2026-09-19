#!/usr/bin/env bash
# terraform apply + espera a API responder + imprime URLs. Uso: bash scripts/deploy.sh
# Pre-requisitos: aws configure feito; infra/terraform.tfvars preenchido (ver .example).
set -euo pipefail
cd "$(dirname "$0")/../infra"
terraform init -input=false >/dev/null
terraform apply -input=false -auto-approve
URL=$(terraform output -raw url_api)
echo ">> esperando a API em $URL (user-data leva ~3-5 min: dnf + build da imagem)"
for i in $(seq 1 60); do
  if curl -sf -m 5 "$URL/saude" >/dev/null 2>&1; then echo ">> API no ar: $URL"; exit 0; fi
  sleep 10
done
echo ">> API nao respondeu em 10 min; veja: $(terraform output -raw ssh) 'sudo tail -50 /var/log/cloud-init-output.log'"
exit 1

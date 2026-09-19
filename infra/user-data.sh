#!/bin/bash
# Executado pelo cloud-init na primeira inicializacao da EC2 (Amazon Linux 2023).
set -euxo pipefail
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
curl -sL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
# t3.micro tem 1 GB de RAM: swap para o build da imagem nao morrer
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
cd /opt && git clone --branch "${repo_ref}" "${repo_git}" samu-sim && cd samu-sim
cat > .env <<ENV
AWS_REGION=${regiao}
S3_BUCKET=${s3_bucket}
FATOR=${fator}
POLITICA=${politica}
N_AMBULANCIAS=${n_ambulancias}
CHAMADOS_POR_DIA=${chamados_por_dia}
RODADA_ID=aws-$(date +%Y%m%d-%H%M)
ENV
chown -R ec2-user:ec2-user /opt/samu-sim
docker compose -f docker-compose.aws.yml --env-file .env up --build -d

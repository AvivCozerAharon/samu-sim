#!/usr/bin/env bash
# Baixa o extrato OSM do Rio (BBBike, ~36 MB) e pre-processa para o OSRM (MLD).
# Roda uma vez; resultado em dados/osrm/. Uso: bash scripts/preparar_osrm.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dados/osrm
IMG=ghcr.io/project-osrm/osrm-backend:v5.27.1
if [ ! -f dados/osrm/rio.osm.pbf ]; then
  echo ">> baixando extrato do Rio (BBBike)"
  curl -sL -o dados/osrm/rio.osm.pbf https://download.bbbike.org/osm/bbbike/RiodeJaneiro/RiodeJaneiro.osm.pbf
fi
V="$(pwd -W 2>/dev/null || pwd)/dados/osrm"
echo ">> osrm-extract (perfil car)"
docker run --rm -v "$V:/data" $IMG osrm-extract -p /opt/car.lua /data/rio.osm.pbf
echo ">> osrm-partition"
docker run --rm -v "$V:/data" $IMG osrm-partition /data/rio.osrm
echo ">> osrm-customize"
docker run --rm -v "$V:/data" $IMG osrm-customize /data/rio.osrm
echo ">> pronto. suba com: docker compose --profile osrm up -d osrm"
ls -la dados/osrm | head -20

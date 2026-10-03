#!/usr/bin/env bash
# Backup do Postgres de producao: pg_dump | gzip, retencao de 14 dias.
# Rode por cron na VPS (ver docs/deploy-vps.md). "Backup nao testado nao existe":
# restaure em staging ao menos 1x/mes.
set -euo pipefail

# Diretorio da app (onde estao docker-compose.prod.yml e .env). Por padrao, a
# raiz do repo relativa a este script; sobrescreva com APP_DIR=/opt/app.
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$APP_DIR"

# Le POSTGRES_USER/DB do .env.
set -a
# shellcheck disable=SC1091
source .env
set +a

mkdir -p backups
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="backups/mobia-${STAMP}.sql.gz"

docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists \
  | gzip > "$OUT"

# Retencao: remove backups com mais de 14 dias.
find backups -name 'mobia-*.sql.gz' -mtime +14 -delete

echo "backup gerado: $APP_DIR/$OUT"
echo "LEMBRE-SE de copiar para fora da VPS (outra maquina/objeto storage)."

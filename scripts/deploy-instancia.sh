#!/bin/bash
# Roda NA INSTANCIA Oracle, dentro de /opt/app. Chamado por scripts/deploy-oracle.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml"

# Enquanto o exclude de testes nao estiver no frontend/tsconfig.json do repo,
# o `next build` quebra type-checando *.test.ts(x). Idempotente.
sed -i 's#"exclude": \["node_modules"\]#"exclude": ["node_modules", "**/*.test.ts", "**/*.test.tsx", "test"]#' frontend/tsconfig.json

echo ">> build";   $COMPOSE build
echo ">> migrate"; $COMPOSE run --rm migrate
echo ">> up";      $COMPOSE up -d
$COMPOSE ps

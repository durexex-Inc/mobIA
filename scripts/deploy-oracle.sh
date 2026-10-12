#!/bin/bash
# Deploy de atualizacao na Oracle Cloud. Rodar no Cloud Shell, dentro do clone:
#
#   cd ~/mobIA && git pull && bash scripts/deploy-oracle.sh
#
# Envia o codigo do clone para /opt/app na instancia, roda build + migrate + up
# (scripts/deploy-instancia.sh) e confere os endpoints. Para no primeiro erro.
set -euo pipefail

HOST="${DEPLOY_HOST:-ubuntu@147.15.91.33}"
KEY="${DEPLOY_KEY:-$HOME/mk}"
APP_DIR="/opt/app"
SSH=(ssh -o PubkeyAcceptedKeyTypes=+ssh-ed25519 -o IdentitiesOnly=yes
     -o StrictHostKeyChecking=accept-new -i "$KEY" "$HOST")

cd "$(dirname "$0")/.."
echo "== commit: $(git log --oneline -1)"

echo "== 1/3 enviando codigo para $HOST:$APP_DIR"
tar --exclude=.git --exclude=node_modules --exclude=.venv --exclude=.ruff_cache \
    --exclude=.env -czf - . | "${SSH[@]}" "tar -C $APP_DIR -xzf -"

echo "== 2/3 build + migrate + up"
"${SSH[@]}" "bash $APP_DIR/scripts/deploy-instancia.sh"

echo "== 3/3 verificacao"
api=$(curl -s -o /dev/null -w '%{http_code}' https://api.mobia.dev.br/health)
painel=$(curl -s -o /dev/null -w '%{http_code}' https://painel.mobia.dev.br/)
echo "api/health: $api (esperado 200)"
echo "painel:     $painel (esperado 307)"
[ "$api" = "200" ] || { echo "ATENCAO: api nao respondeu 200"; exit 1; }
echo "== deploy concluido"

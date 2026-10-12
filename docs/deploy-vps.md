# Projeto está rodando 

```https://painel.mobia.dev.br/busca```

# Painel administrativo
```https://painel.mobia.dev.br/```

# Deploy em VPS (Oracle Cloud) com Docker + Traefik — mobIA

Uma VPS, tudo em containers atrás do **Traefik** (HTTPS automático via Let's
Encrypt). Deploy pela pipeline (GitHub Actions → GHCR → SSH), com migração antes
do app e rollback automático.

## Arquitetura na VPS

```
Internet ──443──> Traefik ──┬─ api.<dominio>     -> container api      (FastAPI :8000)
                            └─ painel.<dominio>  -> container frontend (Next   :3000)

rede interna (sem internet, sem porta pública):
   api, worker, frontend  ──> postgres (pgvector)   e   redis
   worker ──> internet (Anthropic/OpenAI/WhatsApp/SMTP) pela rede "web"
```

- `api` e `worker` são **a mesma imagem** (`mobia-api`), só muda o comando.
- `postgres` e `redis` ficam **só na rede interna** (`internal: true`): sem porta
  publicada, sem acesso à internet. É por isso que `INFRA_INTERNA_CONFIAVEL=true`
  dispensa o TLS para eles — o tráfego nunca sai do host.
- `migrate` roda `alembic upgrade head` e sai, **antes** de `api`/`worker` subirem.

## 1. Provisionar a VPS (Ubuntu 22.04/24.04)

```bash
# como root, no primeiro acesso
adduser deploy && usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy   # copia sua chave

# Docker Engine + plugin compose
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy

# Firewall: só SSH, HTTP e HTTPS
apt-get install -y ufw fail2ban unattended-upgrades
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
systemctl enable --now fail2ban
dpkg-reconfigure -plow unattended-upgrades
```

Endureça o SSH (`/etc/ssh/sshd_config`): `PasswordAuthentication no`,
`PermitRootLogin no`, depois `systemctl restart ssh`. A partir daqui use o
usuário `deploy`.

## 2. DNS

No seu provedor de DNS, crie dois registros **A** apontando para o IP da VPS:

```
api.seudominio.com.br     A   <IP_DA_VPS>
painel.seudominio.com.br  A   <IP_DA_VPS>
```

O Let's Encrypt (HTTP-01) só emite depois que o DNS resolver para a VPS.

## 3. Código e `.env` na VPS

```bash
sudo mkdir -p /opt/app && sudo chown deploy:deploy /opt/app
git clone https://github.com/durexex-Inc/mobIA.git /opt/app
cd /opt/app
git checkout feature/deploy-vps     # enquanto não houver merge na main

cp .env.prod.example .env
# gere os segredos e edite o .env:
python3 -c "import base64,os;print('CONTENT_ENCRYPTION_KEY='+base64.b64encode(os.urandom(32)).decode())"
python3 -c "import secrets;print('JWT_SEGREDO='+secrets.token_urlsafe(48))"
python3 -c "import secrets;print('AUDITORIA_CHAVE_DO_LEAD='+secrets.token_urlsafe(48))"
python3 -c "import secrets;print('LEAD_INDICE_CHAVE='+secrets.token_urlsafe(48))"
nano .env   # DOMINIO, ACME_EMAIL, GHCR_OWNER (minúsculas), POSTGRES_*, chaves de IA, WhatsApp, SMTP, SEED_ADMIN_*
```

`.env` nunca vai para o git (já está no `.gitignore`) e deve ter backup seguro à
parte.

## 4. Secrets do GitHub (Settings → Secrets and variables → Actions)

| Secret | O quê |
|---|---|
| `VPS_HOST` | IP ou host da VPS |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | chave **privada** SSH com acesso ao `deploy` |
| `VPS_PORT` | porta SSH (opcional, padrão 22) |
| `GHCR_PULL_TOKEN` | PAT (classic) com `read:packages`, para a VPS puxar as imagens |

As imagens são publicadas em `ghcr.io/<owner>/mobia-api` e `.../mobia-frontend`.
Elas nascem privadas; o `GHCR_PULL_TOKEN` deixa a VPS baixá-las (ou torne os
pacotes públicos em GHCR → Package settings).

## 5. Primeiro deploy

**Opção A — pela pipeline (recomendado):** em *Actions → Deploy VPS → Run
workflow*, escolha a branch `feature/deploy-vps`. Ela builda, publica no GHCR e
faz o deploy por SSH (grava `IMAGE_TAG` no `.env`, `pull`, migra, `up -d`).

**Opção B — build local na VPS (bootstrap sem pipeline):**

```bash
cd /opt/app
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d
```

Acompanhe o Traefik emitir o certificado: `docker compose -f docker-compose.prod.yml logs -f traefik`.

## 6. Semente de produção (admin + catálogo) — uma vez

```bash
cd /opt/app
docker compose -f docker-compose.prod.yml run --rm api python -m mobia.admin.seed_producao
```

Cria o admin de `SEED_ADMIN_*` e **imprime a URI `otpauth://`** (MFA) — cadastre
no autenticador na hora; não reaparece. Carrega o catálogo de
`data/seed/imoveis.csv` se a base estiver vazia. É idempotente.

## 7. Conferir

```bash
curl -I https://api.seudominio.com.br/health
# abra https://painel.seudominio.com.br e entre com o admin (e o código MFA)
```

Webhook do WhatsApp (painel da Meta): `https://api.seudominio.com.br/webhooks/whatsapp`,
com o `WHATSAPP_VERIFY_TOKEN` do `.env`.

## 8. Backups do Postgres

```bash
chmod +x /opt/app/scripts/backup_postgres.sh
# cron diário às 3h, com log
( crontab -l 2>/dev/null; echo "0 3 * * * cd /opt/app && APP_DIR=/opt/app ./scripts/backup_postgres.sh >> /opt/app/backups/backup.log 2>&1" ) | crontab -
```

Copie os `.sql.gz` para **fora** da VPS (outra máquina / object storage) e
**teste a restauração** ao menos 1×/mês:

```bash
gunzip -c backups/mobia-AAAAMMDD-HHMMSS.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

## 9. Rollback

A pipeline faz rollback automático se o healthcheck da API não ficar verde
(repõe a tag anterior gravada em `/opt/app/.last-good`). Manualmente:

```bash
cd /opt/app
sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=$(cat .last-good)|" .env
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Migração é retrocompatível por política (expand/contract): adicione coluna →
deploy → migre dados → remova depois, para o rollback do app não quebrar no
schema novo.

## 10. Logs e operação

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f worker
```

**Dashboard do Traefik** fica desligado. Para ligar com segurança, exponha
`api.dashboard=true` atrás de um roteador em `traefik.<dominio>` com middleware
de `basicauth` — nunca aberto.

## Checklist de go-live

- [ ] DNS de `api.` e `painel.` apontando para a VPS; HTTPS emitido; HSTS ativo
- [ ] `.env` preenchido (segredos de produção, não os de dev) e com backup à parte
- [ ] `ufw` só com 22/80/443; `fail2ban` e updates automáticos ligados
- [ ] Seed rodado; login no painel com MFA funcionando
- [ ] Backup diário rodando e **restauração testada** em staging
- [ ] Rollback ensaiado (subir uma tag, voltar para a anterior)
- [ ] Webhook do WhatsApp validado na Meta

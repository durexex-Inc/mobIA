# Deploy na Oracle Cloud (Always Free) com Docker + Traefik — mobIA

Mesma arquitetura do [`deploy-vps.md`](./deploy-vps.md): uma única máquina Ubuntu,
tudo em containers atrás do **Traefik** (HTTPS automático via Let's Encrypt),
Postgres e Redis só na rede interna, deploy pela pipeline (GitHub Actions → GHCR
→ SSH) com migração antes do app e rollback automático.

Este guia cobre **só o que é específico da Oracle Cloud**. Domínio do projeto:
`mobia.dev.br` → a API responde em `api.mobia.dev.br` e o painel em
`painel.mobia.dev.br`.

## O que muda em relação a um VPS comum

1. **A instância que vale a pena é ARM (aarch64).** O *Always Free* da Oracle dá
   uma **Ampere A1** que continua grátis **depois** dos 30 dias de trial (os
   créditos de trial expiram; o Always Free não). Por isso o build virou
   multi-arch (`linux/amd64,linux/arm64` no `deploy-vps.yml`) — sem isso o
   `docker compose pull` falha no ARM com `no matching manifest`.
   > **Cota atual (2026):** a Oracle reduziu o Always Free A1 de 4 OCPU/24 GB para
   > **2 OCPU / 12 GB**. Ainda sobra para o mobIA (os `mem_limit` da stack somam
   > ~2,4 GB). Documentação ainda repete 4/24 em muitos lugares — o teto cobrado
   > a R$ 0 hoje é 2/12.
2. **Firewall em duas camadas.** Diferente da Hostinger, abrir só o `ufw` **não
   basta**: a Oracle fecha o tráfego na *Security List* da VCN (nível nuvem) **e**
   nas regras `iptables` que a imagem Ubuntu já traz. É o motivo nº 1 de "o
   Traefik sobe mas o site dá timeout". As duas precisam liberar 80/443.
3. **IP público é efêmero por padrão** — reserve-o, senão ele muda se a instância
   for recriada e o DNS quebra.

---

## 1. Criar a instância

Console Oracle → **Compute → Instances → Create instance**:

- **Image:** Canonical **Ubuntu 24.04** (ou 22.04).
- **Shape:** *Change shape* → **Ampere** → **VM.Standard.A1.Flex** →
  **2 OCPU / 12 GB** (todo o Always Free ARM de uma vez).
- **Networking:** deixe criar uma VCN nova; garanta **"Assign a public IPv4
  address" = Yes** e que a sub-rede seja **pública**.
- **SSH keys:** cole sua chave pública (a mesma cujo par privado irá no secret
  `VPS_SSH_KEY`). O usuário padrão da imagem Ubuntu é `ubuntu`.
- **Boot volume:** o mínimo (~47–50 GB) já cabe nos 200 GB de block storage
  Always Free.

> **"Out of host capacity" no A1 é comum.** Se der, tente outro *Availability
> Domain* na mesma região, troque para 1 OCPU/6 GB, ou repita depois de alguns
> minutos — a capacidade ARM free gira bastante.

## 2. Reservar o IP público

**Networking → IP Management → Reserved Public IPs → Reserve** (ou, na VNIC da
instância, converta o IP efêmero em *reserved*). Anote o IP — ele vai no DNS e no
secret `VPS_HOST`.

## 3. Abrir as portas 80/443 (as DUAS camadas)

**Camada 1 — Security List da VCN.** Networking → sua VCN → sub-rede → *Security
List* padrão → **Add Ingress Rules** (a 22 já vem aberta):

| Stateless | Source      | IP Protocol | Dest. Port |
|-----------|-------------|-------------|------------|
| No        | 0.0.0.0/0   | TCP         | 80         |
| No        | 0.0.0.0/0   | TCP         | 443        |

**Camada 2 — iptables na instância.** A imagem Ubuntu da Oracle tem um `REJECT`
no fim da chain `INPUT`; é preciso inserir os ACCEPT **antes** dele:

```bash
# veja em que linha está o REJECT (normalmente a 6)
sudo iptables -L INPUT --line-numbers
# insira os ACCEPT antes do REJECT (ajuste o índice 6 se necessário)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
# persista (senão some no reboot)
sudo netfilter-persistent save
```

## 4. Provisionar o SO

Conecte via `ssh ubuntu@<IP>` e rode (adaptado do `deploy-vps.md` §1):

```bash
sudo adduser deploy && sudo usermod -aG sudo deploy
sudo rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy   # replica a chave

# Docker Engine + plugin compose
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy

# fail2ban + updates automáticos do SO
sudo apt-get update
sudo apt-get install -y fail2ban unattended-upgrades
sudo systemctl enable --now fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades
```

> **Sobre o `ufw` na Oracle:** o firewall real aqui é o `iptables` do passo 3. Se
> instalar o `ufw`, ele pode conflitar com as regras da Oracle e **derrubar seu
> próprio SSH**. O recomendado na Oracle é ficar só com o `iptables` já
> configurado (passo 3) + a Security List (passo 3) — não instale o `ufw` a menos
> que saiba reconciliar as chains.

Endureça o SSH (`/etc/ssh/sshd_config`): `PasswordAuthentication no`,
`PermitRootLogin no`, depois `sudo systemctl restart ssh`. A partir daqui use o
usuário `deploy`.

## 5. DNS no registro.br (`mobia.dev.br`)

No painel do **registro.br** → domínio `mobia.dev.br` → **Editar Zona DNS** →
adicione dois registros **A** apontando para o IP reservado:

```
api      A   <IP_DA_INSTANCIA>
painel   A   <IP_DA_INSTANCIA>
```

Espere propagar (`dig +short api.mobia.dev.br` deve devolver o IP) **antes** do
primeiro deploy — o Let's Encrypt (HTTP-01) só emite o certificado depois que o
nome resolve para a instância.

## 6. Código e `.env` na instância

```bash
sudo mkdir -p /opt/app && sudo chown deploy:deploy /opt/app
git clone https://github.com/durexex-Inc/mobIA.git /opt/app
cd /opt/app
git checkout feature/deploy-vps     # enquanto não houver merge na main

cp .env.prod.example .env
# gere os segredos:
python3 -c "import base64,os;print('CONTENT_ENCRYPTION_KEY='+base64.b64encode(os.urandom(32)).decode())"
python3 -c "import secrets;print('JWT_SEGREDO='+secrets.token_urlsafe(48))"
python3 -c "import secrets;print('AUDITORIA_CHAVE_DO_LEAD='+secrets.token_urlsafe(48))"
python3 -c "import secrets;print('LEAD_INDICE_CHAVE='+secrets.token_urlsafe(48))"
nano .env
```

No `.env`, confira/preencha: `DOMINIO=mobia.dev.br`, `ACME_EMAIL` (seu e-mail real,
para avisos do Let's Encrypt), `GHCR_OWNER=durexex-inc` (minúsculas),
`POSTGRES_PASSWORD`, as chaves de IA, WhatsApp, SMTP e `SEED_ADMIN_*`. O `.env`
nunca vai para o git e deve ter backup seguro à parte.

## 7. Secrets do GitHub

Settings → Secrets and variables → Actions (igual ao `deploy-vps.md` §4):

| Secret | O quê |
|---|---|
| `VPS_HOST` | o **IP reservado** da instância |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | chave **privada** SSH do `deploy` |
| `VPS_PORT` | opcional, padrão 22 |
| `GHCR_PULL_TOKEN` | PAT (classic) com `read:packages`, para a instância puxar as imagens |

O `deploy-vps.yml` agora builda `linux/amd64,linux/arm64` — a mesma tag serve
tanto o ARM da Oracle quanto um x86. O build arm64 roda por emulação QEMU no
runner, então fica **mais lento** (10–25 min); normal para o volume de deploys de
um hackathon.

## 8. Primeiro deploy

**Opção A — build local na instância (bootstrap mais rápido no ARM).** Como a A1
é ARM nativo, buildar na própria máquina evita a emulação e não depende do GHCR:

```bash
cd /opt/app
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f traefik   # acompanhe o certificado
```

**Opção B — pela pipeline.** Actions → *Deploy VPS* → *Run workflow* na branch
`feature/deploy-vps`. Ela builda multi-arch, publica no GHCR e faz o deploy por
SSH (grava `IMAGE_TAG`, `pull`, migra, `up -d`, healthcheck, rollback). Daí em
diante todo push na `main` redeploya.

## 9. Semente e conferência (uma vez)

```bash
cd /opt/app
docker compose -f docker-compose.prod.yml run --rm api python -m mobia.admin.seed_producao
```

Cria o admin de `SEED_ADMIN_*` e imprime a URI `otpauth://` do MFA — cadastre no
autenticador na hora (não reaparece). Carrega o catálogo de `data/seed/imoveis.csv`
se a base estiver vazia. É idempotente.

```bash
curl -I https://api.mobia.dev.br/health
# abra https://painel.mobia.dev.br e entre com o admin + código MFA
```

Webhook do WhatsApp (painel da Meta): `https://api.mobia.dev.br/webhooks/whatsapp`,
com o `WHATSAPP_VERIFY_TOKEN` do `.env`.

## 10. Backups, rollback e operação

Idênticos ao VPS — ver [`deploy-vps.md`](./deploy-vps.md) §8 (backup diário do
Postgres por cron, com cópia **para fora** da instância e restauração testada),
§9 (rollback pela tag em `.last-good`) e §10 (logs). Na Oracle Free, use o próprio
object storage da conta ou outra máquina para guardar os `.sql.gz` fora da
instância.

## Checklist de go-live (Oracle)

- [ ] Instância A1 (2 OCPU/12 GB) Ubuntu, IP **reservado**
- [ ] 80/443 liberadas na **Security List da VCN** *e* no **iptables** (salvo com `netfilter-persistent save`)
- [ ] `api.mobia.dev.br` e `painel.mobia.dev.br` resolvendo para o IP (registro.br)
- [ ] `.env` preenchido (segredos de produção) e com backup à parte
- [ ] HTTPS emitido pelo Let's Encrypt; HSTS ativo
- [ ] Seed rodado; login no painel com MFA funcionando
- [ ] Backup diário rodando e restauração testada
- [ ] Rollback ensaiado; webhook do WhatsApp validado na Meta

# Frontend Next.js (SSR). Build autossuficiente (output: "standalone"): o
# runtime carrega so o server.js + .next/standalone, sem o node_modules inteiro.
# Contexto de build = ./frontend. Tag = SHA do commit (ver o workflow).

# ---- deps ----
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- build ----
FROM node:22-bookworm-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# O build nao conecta no Redis (armazem.ts e lazy/server-only); as paginas do
# painel sao dinamicas (cookie de sessao), nao geram no build.
RUN npm run build

# ---- runtime: nao-root, so o standalone ----
FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
COPY --from=builder --chown=app:app /app/public ./public
USER app
EXPOSE 3000
# server.js e o entrypoint que o modo standalone gera.
CMD ["node", "server.js"]

# Imagem unica para API e worker -- o mesmo artefato, so muda o comando na
# compose (web = uvicorn, worker = arq). Tag = SHA do commit (ver o workflow).

# ---- build: uv instala deps + projeto numa venv isolada ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Camada de dependencias primeiro (cache): so o lock + o manifesto. `--no-dev`
# nao traz pytest/ruff; `--no-install-project` deixa o projeto para a camada
# seguinte, para o cache das deps nao invalidar a cada mudanca de codigo.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Agora o projeto. alembic/, data/ e scripts/ entram porque o runtime precisa:
# migrations no release, data/seed/imoveis.csv no seed, scripts/ nos comandos admin.
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY data ./data
COPY scripts ./scripts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime: enxuto, nao-root ----
FROM python:3.13-slim-bookworm AS runtime

# Usuario sem privilegio: um comprometimento do processo nao vira root no container.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Diretorio da midia local (TEC-132) -- volume na compose o torna persistente.
RUN mkdir -p /app/.midias && chown app:app /app/.midias

USER app
EXPOSE 8000

# Sem HEALTHCHECK aqui de proposito: esta imagem serve tambem o worker, que nao
# abre HTTP. O healthcheck do /health fica no servico `api` da compose.
CMD ["uvicorn", "mobia.app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]

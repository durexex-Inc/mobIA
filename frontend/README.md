# Painel de funil (TEC-190)

O dashboard da gerente comercial: as seis etapas do funil da RN-17.2 com
conversão entre elas, os indicadores da RN-17.1 e os cinco filtros da
RN-17.3. Consome `GET /api/v1/metricas/funil` do FastAPI.

## Rodar em desenvolvimento

O backend precisa estar de pé, com `CATALOGO_ADMIN_TOKEN` configurado:

```bash
cd ..
docker compose up -d
./.venv/Scripts/python.exe -m alembic upgrade head
CATALOGO_ADMIN_TOKEN=local ./.venv/Scripts/python.exe -m uvicorn mobia.app.main:app --port 8000
```

Noutro terminal:

```bash
MOBIA_API_BASE=http://localhost:8000 MOBIA_ADMIN_TOKEN=local npm run dev
```

## As duas variáveis, e por que uma delas não é `NEXT_PUBLIC_`

| variável | onde é lida |
| --- | --- |
| `MOBIA_API_BASE` | servidor Next, ao montar a URL do FastAPI |
| `MOBIA_ADMIN_TOKEN` | servidor Next, no header `X-Admin-Token` |

**`MOBIA_ADMIN_TOKEN` nunca chega ao navegador, e não pode chegar.** É o
token de admin do backend inteiro — quem o tem lê o catálogo, o cadastro de
corretores e este painel. Prefixá-lo com `NEXT_PUBLIC_` o embutiria no bundle
de cliente, entregando-o a qualquer pessoa que abrisse o painel. A página é
um Server Component justamente por isso: a busca acontece no servidor, e o
navegador recebe só o HTML.

O `revalidate: 60` da busca não é só cache. Ele é o teto de defasagem da
RN-17.3 e é o que faz N navegadores com o painel aberto virarem **uma**
chamada por minuto ao FastAPI — que vê o IP deste servidor, não o de cada
navegador, e aplica 100 requisições por minuto por IP.

## O que o painel ainda não sabe

A etapa **Agendado** e os quatro indicadores de visita (criados, confirmados,
realizados e taxa de no-show) saem `null`, com o texto "sem fonte de dados" —
**nunca zero**. Não existe tabela de agendamento no backend: marcar visita é
RF-11 e RF-12, épicos ainda não construídos. Zero seria uma afirmação falsa,
e é a decisão D1 do desenho.

A tela distingue três ausências, e a distinção é deliberada:

| texto | significa |
| --- | --- |
| `sem fonte de dados` | não existe de onde tirar o número (defeito do sistema, RF-12 conserta) |
| `sem dados no período` | a coorte estava vazia (fato do negócio) |
| `—` | não há conversão calculável entre estas duas etapas |

## Comandos

```bash
npm run dev     # desenvolvimento
npm test        # vitest
npm run lint    # eslint
npm run build   # build de produção
```

Os três rodam no CI, no job `Frontend`. Os gates de Python (`ruff`, `mypy`)
não olham para este diretório — nenhum deles lê TypeScript.

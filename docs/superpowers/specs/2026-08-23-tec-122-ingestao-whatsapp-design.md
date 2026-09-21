# TEC-122 — Receber, validar e enfileirar mensagem do WhatsApp

- **Data:** 2026-08-23
- **Jira:** [TEC-122](https://eduardodurieuxlopes.atlassian.net/browse/TEC-122) · Épico [TEC-123](https://eduardodurieuxlopes.atlassian.net/browse/TEC-123)
- **Origem:** RF-01, RN-01.1, RN-01.2, RNF-01, RNF-15 (SRS v1.0)
- **Status:** aprovado, aguardando plano de implementação

## Problema

Marina escreve no WhatsApp às 22h30. A mensagem precisa ser aceita na hora, sem
depender de horário comercial, e não pode se perder se um worker cair. O webhook
da Meta desiste e re-tenta quando não recebe 2xx rápido, e qualquer processamento
de LLM dentro do ciclo da requisição estoura esse orçamento.

Esta é a primeira história do projeto: o repositório está vazio. Implementá-la
significa também escolher a stack e assentar a fundação que TEC-125, TEC-126,
TEC-127 e TEC-128 vão estender.

## Decisões de stack

| Camada | Escolha | Razão |
|---|---|---|
| Linguagem/framework | Python 3.12 + FastAPI | O backlog é pesado em IA (TEC-157 embeddings, TEC-158 busca híbrida, TEC-210 evals no CI); ecossistema mais maduro. |
| Banco | PostgreSQL + SQLAlchemy 2.0 + Alembic | pgvector já é requisito do TEC-157. |
| Fila | Redis + ARQ | Async-nativo (casa com FastAPI), com retry/backoff e cron — que TEC-128 (debounce 6s), TEC-171 (lembretes) e TEC-183 (cadência) vão precisar. Redis também serve rate limiting (TEC-205) e locks (TEC-168). (A TEC-128 acabou usando `_defer_by`, não `cron`; a escolha do ARQ continua certa, a justificativa é que não se confirmou para esta card.) |
| Logging | structlog, JSON, com `correlation_id` | Base do TEC-211. |
| Testes | pytest + pytest-asyncio, Postgres e Redis reais via docker-compose | Os critérios são de integração; mock de fila não prova durabilidade. |

Escopo de fundação: **enxuta**. Entram estrutura em camadas, settings, Alembic,
logging e docker-compose. Ficam fora CI/CD, Dockerfile de produção e
observabilidade — são TEC-216 e TEC-211.

## Abordagem: a tabela `messages` como outbox

A regra de negócio é "a mensagem é persistida antes de ir para a fila, para que
nenhuma mensagem recebida se perca". A garantia vem de a linha existir no
Postgres antes de qualquer publicação no Redis; o enfileiramento é otimista e um
sweeper cobre a janela entre o commit e o enqueue.

Alternativas descartadas:

- **Outbox transacional com relay dedicado.** Mesma garantia observável, mas
  adiciona um processo cujo único uso seria este, e a latência de entrega passa
  a depender do polling do relay.
- **Redis Streams com consumer group.** Move a fonte da verdade de entrega para
  o Redis, cuja durabilidade sem fsync é mais fraca do que a regra exige.

## Modelo de dados

### `messages`

| Coluna | Tipo | Nota |
|---|---|---|
| `id` | uuid pk | |
| `channel` | text | `whatsapp`; `web` entra no TEC-124 |
| `provider_message_id` | text | wamid da Meta. Índice simples — vira `UNIQUE` no TEC-125 (dedup) |
| `sender_external_id` | text | wa_id do lead |
| `recipient_external_id` | text | `phone_number_id` da conta |
| `content_type` | text | `text`, `audio`, `image`, … — apenas registrado; TEC-131/132 interpretam |
| `text_body` | text null | |
| `raw_payload` | jsonb | Payload íntegro, para reprocesso e auditoria |
| `status` | text | `RECEIVED` → `QUEUED` → `PROCESSING` → `PROCESSED` \| `FAILED` |
| `attempts` | int | |
| `received_at`, `queued_at`, `processed_at` | timestamptz | |
| `last_error` | text null | |

Índices: `(status, received_at)` para o sweeper, `(provider_message_id)`.

### `outbound_dispatches`

`id`, `message_id` fk, `kind`, `created_at`, com `UNIQUE (message_id, kind)`.
É a guarda que torna o reprocessamento seguro: a segunda tentativa de emitir o
mesmo efeito colide e vira no-op.

Descarte por assinatura inválida **não** é persistido — o critério pede log com
o motivo. Trilha de auditoria durável é TEC-206.

## Estrutura de módulos

```
src/mobia/
  app/main.py              factory FastAPI
  app/config.py            pydantic-settings
  app/logging.py           structlog JSON + correlation_id
  api/routes/whatsapp.py   GET verify (hub.challenge) + POST ingest
  domain/messages/         models.py · schemas.py · service.py · status.py
  domain/outbound/         port.py (Protocol) · noop.py
  infra/                   db.py · queue.py · signature.py
  workers/main.py          WorkerSettings do ARQ
  workers/jobs/            process_message.py · sweep_stalled.py
alembic/
tests/{unit,integration,features}
docker-compose.yml · Makefile · pyproject.toml
```

## Fluxo do webhook

`GET /webhooks/whatsapp` responde ao handshake da Meta (`hub.mode`,
`hub.verify_token`, `hub.challenge`). Não consta nos critérios de aceite, mas
sem ele a Meta não registra o webhook e nenhum cenário é verificável em
ambiente real.

`POST /webhooks/whatsapp`:

1. Lê o corpo **bruto** antes de qualquer parse — o HMAC é sobre os bytes exatos.
2. Verifica `X-Hub-Signature-256` com `hmac.compare_digest`. Assinatura ausente
   ou inválida → log `webhook.rejected` com `reason`, `remote_ip` e
   `payload_sha256`; responde 200 sem enfileirar. Responder 2xx é deliberado:
   a Meta re-tenta em não-2xx, e um forjador não deve conseguir provocar retry.
3. Faz o parse do envelope. Notificações de `statuses` ou estrutura desconhecida
   são logadas e ignoradas; só entradas em `messages[]` viram linha.
4. `INSERT` com `status=RECEIVED` e **commit**. A partir daqui a mensagem existe.
5. `enqueue_job('process_message', id)` e `UPDATE status=QUEUED`. Falha do Redis
   é capturada e logada como `enqueue.failed`, sem propagar: a linha fica
   `RECEIVED` e o sweeper resolve.
6. `200 OK`. O orçamento de 300 ms no p95 cobre um insert e um LPUSH.

Nenhuma chamada ao provedor de LLM ocorre neste caminho — não há dependência de
LLM injetada na rota, e o teste do cenário 1 asserta zero chamadas em um
`LLMPort` fake.

## Worker e idempotência

`process_message(id)` reivindica a mensagem com
`UPDATE … SET status='PROCESSING' WHERE id=… AND status IN ('RECEIVED','QUEUED','PROCESSING')`
e checa `rowcount`; quem perde a corrida sai como no-op.

Todo efeito externo passa por `OutboundPort` e grava `outbound_dispatches` na
mesma transação do envio — a constraint `UNIQUE (message_id, kind)` faz a
reentrega virar no-op. A implementação atual é `NoopOutbound`, já que resposta
ao lead só existe a partir do TEC-134; a guarda entra agora porque é o que o
critério "nenhuma resposta duplicada" exige da infraestrutura.

Sucesso → `PROCESSED`. Exceção → `FAILED`, `last_error`, `attempts += 1`, retry
com backoff do ARQ. DLQ e degradação graciosa são TEC-209.

## Sweeper

Cron ARQ a cada 30 s, reenfileira com `attempts < 5`:

- `RECEIVED` há mais de 30 s — queda entre o commit e o enqueue.
- `QUEUED` ou `PROCESSING` há mais de 5 min — worker morto no meio do job.

## Testes

Os três cenários Gherkin viram testes de integração contra Postgres e Redis
reais.

1. **Confirmar recebimento antes de processar.** POST assinado → 200; linha em
   `QUEUED`; job presente na fila; `LLMPort` fake com zero chamadas.
2. **Descartar payload com assinatura forjada.** Nenhuma linha, fila vazia,
   log `webhook.rejected` com o motivo.
3. **Não perder mensagem em falha do worker.** Job executado com exceção no meio
   (deixando `PROCESSING` persistido), worker reiniciado, execução concluída →
   `PROCESSED` e exatamente **um** registro no fake outbound.

A latência p95 é um teste à parte (200 requisições, assert p95 < 300 ms) marcado
`@pytest.mark.perf` e fora do run padrão: medição de latência em CI compartilhado
é frágil e viraria flake.

Unitários: verificação HMAC (válido, forjado, ausente, corpo alterado), parser
do envelope Meta (texto, áudio, imagem, `statuses`, malformado) e transições de
status.

## Fora de escopo

Deduplicação por `message_id` (TEC-125), debounce de rajada (TEC-128),
transcrição de áudio (TEC-131), canal web (TEC-124), qualquer processamento de
LLM, CI/CD (TEC-216), observabilidade (TEC-211), DLQ (TEC-209).

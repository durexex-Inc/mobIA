# TEC-126 — Persistir mensagens com tokens, custo e latência

- **Data:** 2026-08-24
- **Jira:** [TEC-126](https://eduardodurieuxlopes.atlassian.net/browse/TEC-126) · Épico [TEC-123](https://eduardodurieuxlopes.atlassian.net/browse/TEC-123)
- **Origem:** RF-02, RN-02.1 (SRS v1.0); insumo do painel de custo (RN-17.4) e da observabilidade de LLM (RNF-36)
- **Status:** aprovado, aguardando plano de implementação

## Problema

Anelise precisa saber quanto o atendimento automático custa por conversa e onde
ele está lento. Para isso, toda mensagem — de entrada e de saída — tem de ficar
registrada com papel, canal, tipo e timestamp, e as geradas pelo agente têm de
trazer tokens, custo em dólar, latência e qual subagente respondeu.

O que existe hoje não serve. `messages` foi desenhada no TEC-122 como **entrada**:
carrega a maquinaria de outbox do sweeper (`status`, `attempts`, `queued_at`,
`claimed_at`, `last_error`) e agrupa por `sender_external_id`. A fala do agente
tem sender e recipient invertidos, não tem `provider_message_id`, e não participa
de pipeline de ingestão nenhum.

Esta história é o que destrava TEC-127 (janela de contexto), que por sua vez
destrava todo o caminho de LLM — épicos TEC-133, TEC-144 e TEC-155.

## Abordagem: `messages` vira a linha do tempo, telemetria sai para o lado

`messages` deixa de ser "o que chegou" e passa a ser o registro conversacional
canônico: entrada e saída na mesma tabela, ordenadas por um único timestamp.
Tokens, custo, latência, modelo e subagente vão para `message_telemetry`, 1-1,
que só ganha linha quando o agente falou.

A divisão é pela pergunta que cada consulta faz. TEC-127 monta o contexto do
modelo lendo as 20 mensagens mais recentes e não quer saber de custo — lê a
timeline sem join. O painel de custo (E8) soma dólares e não deve tocar em
conteúdo de lead — lê telemetria sem join. Ninguém precisa das duas coisas ao
mesmo tempo.

Alternativas descartadas:

- **Tudo em `messages`.** Seis colunas de telemetria nullable somadas às seis de
  outbox produzem uma tabela onde metade das colunas é sempre nula para qualquer
  linha: outbox não significa nada para o agente, telemetria não significa nada
  para o lead.
- **Separar por direção (`messages` + `agent_messages`).** Cada tabela fica
  coesa, mas a timeline passa a exigir `UNION ALL` ordenado por timestamp — e é
  exatamente essa consulta que TEC-127 faz a cada turno.

## Modelo de dados

### `messages` — o que muda

| Coluna | Mudança | Nota |
|---|---|---|
| `role` | nova, `varchar(16)` not null | `LEAD` \| `AGENTE` \| `CORRETOR` \| `SISTEMA` |
| `direction` | nova, `varchar(8)` not null | `INBOUND` \| `OUTBOUND` |
| `conversation_key` | nova, `varchar(64)` not null | id externo do lead, invariante à direção |
| `received_at` | renomeada para `created_at` | "recebida em" é mentira numa linha de saída |
| `provider_message_id` | passa a nullable | a fala do agente não tem wamid |
| `sender_external_id`, `recipient_external_id` | passam a nullable | detalhe de roteamento do provedor, não identidade da conversa |
| `text_body` | `text` → `bytea` | AEAD |
| `raw_payload` | `jsonb` → `bytea`, nullable | AEAD; a linha de saída não tem payload de provedor |
| `content_type` | passa a guardar enum de domínio | `TEXTO` \| `AUDIO` \| `IMAGEM` \| `DOCUMENTO` \| `DESCONHECIDO` |
| `status` | passa a nullable | NULL = não participa do pipeline de ingestão |

Índice novo: `(channel, conversation_key, created_at DESC)` — é a consulta de
TEC-127. O índice `(status, received_at)` do sweeper acompanha o rename.

`conversation_key` é denormalizado de propósito: guarda o id externo do lead,
seja ele o `sender` (entrada) ou o `recipient` (saída). Uma tabela
`conversations` de primeira classe exigiria decidir quando uma conversa abre e
fecha, e isso é TEC-129 (unificar histórico entre canais) e TEC-130 (encerrar por
inatividade). Elas introduzem a entidade e fazem backfill da FK.

`sender_external_id` e `recipient_external_id` passam a nullable pelo mesmo
motivo que `provider_message_id`: são identidade de roteamento do provedor, e
quem decide a do envio é quem envia — TEC-134. `conversation_key` já identifica
o interlocutor, então a timeline não depende delas. Quem tiver o dado na mão
pode passá-lo ao recorder; quem não tiver grava NULL em vez de inventar.

A `UNIQUE (channel, provider_message_id)` do TEC-125 sobrevive ao nullable:
Postgres não considera dois NULLs iguais, então as linhas de saída convivem sem
colidir entre si nem enfraquecer a dedup da entrada.

`content_type` migra do vocabulário cru da Meta (`text`, `audio`, `image`) para
um enum de domínio porque `messages` agora é o registro canônico que TEC-124
(widget web) também vai alimentar, com vocabulário próprio. O mapeamento passa
para o parser; a coluna guarda o termo do domínio.

### `message_telemetry`

| Coluna | Tipo | Nota |
|---|---|---|
| `message_id` | uuid pk, fk → `messages.id` on delete cascade | 1-1 |
| `model` | `varchar(64)` not null | o modelo que produziu a resposta |
| `subagent` | `varchar(32)` not null | qualificador, roteador, … |
| `tokens_in`, `tokens_out` | `integer` not null | |
| `cost_usd` | `numeric(12,6)` **null** | NULL = modelo sem preço cadastrado |
| `latency_ms` | `integer` not null | |
| `created_at` | `timestamptz` not null | |

### A armadilha do sweeper

`status` é hoje `not null default RECEIVED`. Se a linha do agente nascesse com
esse default, **o sweeper varreria a fala do próprio agente e a enfileiraria para
processamento** — TEC-122 recuperando uma mensagem que nunca foi recebida de
ninguém.

A defesa é tripla e cada perna é independente: `status` nullable e a linha de
saída nasce com NULL; o `SELECT` do sweeper passa a filtrar por
`direction = INBOUND`; e `CLAIMABLE_STATUSES` num `IN (…)` nunca casa com NULL.

## Cifra em repouso

`src/mobia/infra/crypto.py`, AES-GCM via `cryptography.hazmat`. Chave de 32 bytes
em base64 em `Settings.content_encryption_key`, com default de desenvolvimento —
mesmo padrão que `whatsapp_app_secret` já segue.

Gravado: `nonce(12) || ciphertext || tag(16)`. O nonce é aleatório por chamada,
então o mesmo texto cifra diferente toda vez e busca por igualdade sobre conteúdo
deixa de existir. É intencional.

O AAD é `{message_id}:{coluna}`. Sem ele, quem tem `UPDATE` no banco mas não a
chave pode mover o ciphertext de um lead para a linha de outro, e a aplicação
decifra sem reclamar. Com ele, a decifragem falha.

O custo aceito: `raw_payload` deixa de ser consultável por operador JSONB, e
depurar pelo `psql` fica cego. Rotação de chave fica fora de escopo.

## Mascaramento em log

Duas camadas, porque a primeira sozinha vaza no dia em que alguém esquecer.

1. Nada no código loga `text_body` nem `raw_payload` — já é verdade hoje.
2. Um processor em `app/logging.py`, antes do `JSONRenderer`, redige corridas de
   10 a 15 dígitos em qualquer valor do `event_dict` e mascara por chave conhecida
   (`sender_external_id`, `recipient_external_id`, `conversation_key`).

## `MessageRecorder`

`src/mobia/domain/messages/recorder.py` expõe a costura que TEC-134 vai usar:

```python
async def record_agent_message(
    self, *, conversation_key: str, channel: str, text: str,
    model: str, subagent: str, tokens_in: int, tokens_out: int,
    latency_ms: int,
    sender_external_id: str | None = None,
    recipient_external_id: str | None = None,
) -> uuid.UUID | None
```

**Dois passos, não uma transação.** Se a mensagem e a telemetria fossem um insert
atômico, uma falha de telemetria derrubaria junto o registro da fala do agente —
e o critério pede o oposto: a resposta é entregue normalmente e a falha de
telemetria é registrada sem interromper o fluxo.

1. `INSERT` em `messages` (`role=AGENTE`, `direction=OUTBOUND`, `status=NULL`),
   commit. Falhou: loga `message.record_failed`, devolve `None`.
2. `INSERT` em `message_telemetry`, best-effort. Falhou: loga
   `telemetry.record_failed` e devolve o id da mensagem assim mesmo.

O registro conversacional sobrevive; só a telemetria se perde. É a mesma
filosofia do `_try_enqueue` do TEC-122 — persiste primeiro, o efeito secundário é
otimista e engole a própria falha.

O método **nunca propaga exceção**. `NoopOutbound` continua não gravando nada: o
ack do worker não é fala do agente, e essas linhas entrariam na janela de 20
mensagens que TEC-127 manda para o modelo.

## Custo

`PRECOS_POR_MODELO` em `app/config.py`, mapeando `model → (usd_por_1M_in,
usd_por_1M_out)`. O recorder multiplica e grava o valor junto com o `model` que o
produziu, de modo que mudar o preço amanhã não reescreve o histórico e o painel
soma uma coluna em vez de reimplementar a regra.

Modelo sem preço cadastrado grava `cost_usd = NULL` e loga
`telemetry.unknown_model`. Gravar `0.00` somaria silenciosamente no painel e
faria o custo parecer menor do que foi; NULL aparece como lacuna.

## Estrutura de módulos

Novos:

```
src/mobia/infra/crypto.py                 AES-GCM, encrypt/decrypt com AAD
src/mobia/domain/messages/recorder.py     MessageRecorder
src/mobia/domain/messages/enums.py        MessageRole, MessageDirection, MessageContentType
alembic/versions/0004_timeline_telemetria_e_cifra.py
tests/features/test_telemetria_de_mensagens.py
tests/integration/test_crypto.py
```

Alterados: `domain/messages/models.py`, `schemas.py`, `service.py`,
`app/logging.py`, `app/config.py`, `workers/jobs/sweep_stalled.py`,
`tests/integration/test_migrations.py`, `tests/integration/test_sweep_stalled.py`,
`tests/integration/test_message_model.py`.

## Migração 0004

Cifra as linhas existentes no backfill, e o `downgrade` decifra — reversibilidade
é critério de aceite do TEC-216 e já tem teste.

Isso ganha uma prova de graça: `test_migrations.py` já faz `downgrade 0002`,
insere texto claro por SQL cru e volta com `upgrade head`. Ele passa a exercitar
o backfill de cifra sem nenhum teste novo. Em troca, a asserção que compara
`text_body` com o texto original precisa decifrar antes de comparar — é o único
ajuste.

## Testes

| Cenário Gherkin | Teste |
|---|---|
| Registrar mensagem de entrada do lead | `tests/features/test_telemetria_de_mensagens.py::test_registrar_mensagem_de_entrada_do_lead` |
| Registrar resposta do agente com custo | `tests/features/test_telemetria_de_mensagens.py::test_registrar_resposta_do_agente_com_custo` |
| Conteúdo pessoal não vaza para o log | `tests/features/test_telemetria_de_mensagens.py::test_conteudo_pessoal_nao_vaza_para_o_log` |
| Falha de telemetria não derruba o atendimento | `tests/features/test_telemetria_de_mensagens.py::test_falha_de_telemetria_nao_derruba_o_atendimento` |

Integração adicional, cobrindo o que os critérios implicam mas não enunciam:

- `SELECT` cru devolve bytes, não o telefone da Marina.
- AAD rejeita ciphertext movido de uma linha para outra.
- Sweeper ignora linha `OUTBOUND` (a armadilha acima).
- Timeline devolve entrada e saída intercaladas na ordem certa por
  `conversation_key`.

## Fora de escopo

Entidade `conversations` e unificação de histórico entre canais (TEC-129),
encerramento por inatividade (TEC-130), montagem da janela de contexto e resumo
(TEC-127), o agente que produz a resposta (TEC-134), exibição do custo em
dashboard (E8), alerta de estouro de orçamento (E9), rotação de chave de cifra,
trilha de auditoria durável (TEC-206).

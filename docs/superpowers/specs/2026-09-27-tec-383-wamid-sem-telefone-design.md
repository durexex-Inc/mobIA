# TEC-383 — O wamid do WhatsApp deixa de guardar o telefone do lead

**Status:** implementado
**Card:** [TEC-383](https://eduardodurieuxlopes.atlassian.net/browse/TEC-383) — épico TEC-200
**Branch:** `feat/tec-383-wamid-sem-telefone`
**Depende de:** TEC-203 (chave de índice), TEC-207 (anonimização), TEC-125 (dedup), TEC-274 (indicador de digitação)

## O que existe quando a card começa

- **`messages.provider_message_id` guarda o wamid cru** em toda mensagem de entrada do WhatsApp. O wamid é base64 de um protobuf que carrega o `wa_id` do lead legível.
- **O wamid também está em `raw_payload`**, no `id` do objeto da mensagem, e esse já vai cifrado desde a TEC-126. É o único outro lugar em que ele existe.
- **Quem lê a coluna** são a dedup (a UNIQUE `uq_messages_channel_provider_message_id`, TEC-125) e o indicador de digitação (`domain/outbound/presenca.py`, TEC-274).
- **O log imprimia o wamid.** `provider_message_id` está entre as `_CHAVES_LIVRES` de `app/logging.py`, e `message.duplicate_discarded` o registrava cru. Com isso, o telefone de toda reentrega ia parar no log.
- **A saída não é afetada:** `recorder.py` grava `provider_message_id=None` na mensagem enviada. O canal web também não, porque o id dele já é montado a partir do HMAC da sessão.
- **Nada consome status de entrega** (sent, delivered, read): o webhook não os lê.

## D1 — A coluna guarda o HMAC do wamid, calculado no parser

- **`chave_de_mensagem(channel, wamid)`** fica em `identidade/indice.py`, o único módulo que conhece `lead_indice_chave`. É um HMAC-SHA256 de `mensagem:{channel}:{wamid}`, em hex. O prefixo `mensagem:` o separa das chaves de lead e de telefone.
- **O parser grava o HMAC** (`parse_meta_envelope`). Por isso o wamid cru não sai do parser, a não ser dentro do `raw_payload` que a ingestão cifra. Os mapas em memória de `IngestionService`, o `RETURNING` e a contagem de duplicatas passam todos a trabalhar com o HMAC sem mudar uma linha.
- **A dedup continua pela mesma UNIQUE.** O HMAC é determinístico, então a reentrega do mesmo wamid dá o mesmo valor.
- **O log deixa de ter o telefone:** `message.duplicate_discarded` passa a imprimir o HMAC.

Descartado: **passar o wamid em memória do webhook ao job.** O argumento do job do ARQ fica no Redis, e o `raw_payload` cifrado já guarda o wamid. Uma segunda cópia não compraria nada.

## D2 — O indicador de digitação lê o wamid do `raw_payload`

`_id_da_entrada_no_provedor` decifra o `raw_payload` da linha com o AAD dela e lê o `id`. Isso vale só no WhatsApp. No web continua valendo a coluna, porque o adaptador ignora o valor e a guarda só exige que ele exista.

Linha cujo raw a retenção ou a anonimização já esvaziaram não indica. A essa altura a conversa terminou há meses.

## D3 — A migration `0066` troca o wamid das linhas antigas

- **Subida:** as linhas `channel = 'whatsapp' AND provider_message_id LIKE 'wamid.%'` recebem o HMAC. O backfill é em Python, porque o banco não tem a chave (como na `0004` e na `0062`). O HMAC é hex puro e o pseudônimo da TEC-207 é `anon:…`, então uma subida interrompida se retoma sem reprocessar nada.
- **Descida:** restaura o wamid a partir do `raw_payload`. Linha anonimizada ou com o raw esvaziado fica como está.
- **Rodar com o webhook parado.** Uma reentrega que chegasse entre o deploy do código novo e o fim da subida gravaria o HMAC enquanto a original ainda tem o wamid cru, e a UNIQUE não a descartaria.

## Testes

- **Unitários do parser:** o id gravado é o HMAC e o `raw_payload` mantém o wamid; num wamid que carrega um telefone, nem o telefone nem o corpo base64 chegam ao id; o mesmo wamid dá sempre o mesmo id.
- **Integração** (`test_wamid_sem_telefone.py`):
  - a linha inteira, via `row_to_json`, não contém o telefone, nem o wamid, nem o corpo base64 dele;
  - a reentrega é descartada;
  - a `0066` troca a linha antiga, preserva a anonimizada e a sem raw, e a descida devolve o wamid.
- **Os testes existentes** passam a procurar a linha pelo HMAC (`pmid_do_whatsapp`, em `tests/conftest.py`). As sementes gravam como o parser grava: HMAC na coluna e wamid no raw cifrado. O indicador continua recebendo o wamid cru (`test_indicador_de_digitacao.py`).

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Mensagem gravada sem o telefone | `test_mensagem_do_whatsapp_e_gravada_sem_o_telefone` |
| Reentrega continua deduplicada | `test_reentrega_do_mesmo_wamid_e_descartada` e `test_dedup_por_message_id.py` pelo webhook |
| Indicador com o wamid correto | `test_indicador_de_digitacao.py` e `test_indicador_por_canal.py`, com a semente gravando como o parser |
| Mensagens antigas migradas | `test_a_0066_troca_o_wamid_antigo_e_a_descida_o_devolve` |

## Lacunas declaradas

- **L1 — A rotação da chave de índice não reescreve este HMAC.** `reindexacao.py` leva o `conversation_key` para a chave nova, mas o `provider_message_id` do WhatsApp fica sob a chave velha. O único efeito é na dedup: uma reentrega da Meta que atravesse a rotação ganha um HMAC novo e entra de novo. O efeito se limita à janela de retentativa da Meta, e a rotação é manual e rara. Recalcular a partir do `raw_payload` é possível, e fica para quando a rotação tiver card.
- **L2 — Status de entrega não acham mais a linha.** Hoje nada os lê. Quem for ler terá de aplicar `chave_de_mensagem` ao wamid do status, o que só funciona para mensagens de entrada. A saída não guarda wamid nenhum.
- **L3 — Fora do escopo, como a card declara:** a máscara de log que cobre só os 15 primeiros dígitos de uma sequência longa (`app/logging.py`).

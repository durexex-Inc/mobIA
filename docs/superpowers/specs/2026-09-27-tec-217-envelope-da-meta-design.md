# TEC-217 — Preservar o envelope completo da Meta na mensagem recebida

**Status:** implementado
**Card:** [TEC-217](https://eduardodurieuxlopes.atlassian.net/browse/TEC-217) — épico TEC-123
**Branch:** `feat/tec-217-envelope-da-meta`

## O que existe quando a card começa

- **A coluna já existe, vazia.** `messages.envelope_context` foi reservada pela migration `0003` (TEC-125) e cifrada pela `0034` (TEC-221) antes de haver quem escrevesse nela. O comentário do modelo define o conteúdo: `change.value` sem o array `messages`.
- **Ela já é tratada em todo lugar que trata `raw_payload`:** a anonimização e a retenção da TEC-207 a esvaziam, o `recifrar` da TEC-203 a reescreve e o log estruturado a redige.
- **O parser descarta o envelope.** `parse_meta_envelope` (`src/mobia/domain/messages/schemas.py`) grava em `raw_payload` só o objeto da mensagem, e tudo acima dele se perde.

## D1 — A decisão de esquema é a opção 2, que o repo já tinha tomado

A card lista três caminhos. A coluna separada (opção 2) já existe, já é cifrada e já é coberta pelo tratamento de titular. As outras duas desfariam isso:

- **opção 1**, trocar `raw_payload` pelo `change.value` inteiro: repete as mensagens irmãs em cada linha;
- **opção 3**, extrair colunas próprias: acopla o esquema ao formato atual da Meta, e cada coluna nova seria mais uma para a TEC-207 lembrar de apagar.

`raw_payload` não muda. Por isso nada que lê o raw muda de comportamento: o reprocessamento e a mídia recebida da TEC-132 continuam iguais.

## D2 — O que entra na coluna

```json
{"entry_id": "<entry[].id>", "value": {<change.value, filtrado>}}
```

- **`entry_id`** entra porque o identificador da conta de negócio vive um nível acima de `value`, e a card o pede.
- **`value` perde `messages` e `statuses`.** `messages` porque cada linha já tem a própria em `raw_payload`: é o "nenhuma linha carrega o corpo das mensagens irmãs" da card. `statuses` porque descreve mensagens de saída e traz o telefone de **outros** destinatários.
- **`contacts` fica só com o contato do remetente daquela linha** (`wa_id == from`).

  Esta é a decisão que a card não tomava, e o motivo é LGPD. Um envelope pode trazer mensagens de dois leads. Sem o filtro, a linha do lead A guardaria o nome e o telefone do lead B. Anonimizar B (TEC-207) esvazia só as linhas de B, e o nome dele sobreviveria nas de A. A regra da tabela desde a TEC-126 é que cada linha só tenha dado pessoal de quem a conversa é.
- **Todo o resto de `value` passa como está**, inclusive campos que a Meta ainda não manda: ficar tolerante a formato novo é o argumento da opção 2 contra a 3.

## D3 — Quem lê

`nome_no_envelope(contexto)` devolve `contacts[0].profile.name`, ou `None` quando não há contato, perfil ou nome. É a função que o primeiro consumidor, a nomeação do lead, vai chamar. Esta card não a liga a nada.

O canal web não tem envelope. O `ParsedMessage` do widget sai com `envelope_context=None`.

## Testes

- **Unitários do parser:**
  - o envelope de cada mensagem traz `entry_id` e `metadata`, sem `messages` nem `statuses`;
  - com dois remetentes, cada linha fica com o contato do próprio remetente;
  - sem `contacts`, `nome_no_envelope` devolve `None`;
  - campo desconhecido de `value` sobrevive.
- **Integração da ingestão:** o envelope é gravado cifrado com o AAD da própria linha, e o nome se recupera decifrando. Com três mensagens de um lote, cada linha tem a `metadata` e nenhuma carrega o texto das irmãs. Sem `contacts`, a ingestão conclui e o nome é nulo.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Nome do lead sobrevive à ingestão | integração: decifra `envelope_context` e lê `nome_no_envelope` |
| Lote não perde contexto e não carrega irmãs | integração com três mensagens |
| Envelope sem `contacts` | integração e unitário |

## Lacunas declaradas

- **L1 — Sem consumidor.** Nada lê o nome ainda. A nomeação do lead e a TEC-131 são quem vai ler.
- **L2 — A portabilidade não exporta o nome.** `GET /leads/{id}/dados-pessoais` (TEC-207) não lê `raw_payload` nem `envelope_context`. Com esta card, o nome do perfil do WhatsApp passa a ser dado pessoal guardado, e a exportação não o inclui. A eliminação o cobre, e a exportação não.
- **L3 — Sem backfill.** As linhas já gravadas ficam com `envelope_context` nulo, porque o envelope delas não foi guardado e não há de onde reconstruí-lo.

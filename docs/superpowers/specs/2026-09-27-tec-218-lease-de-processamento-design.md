# TEC-218 — Exclusão mútua real entre workers, com lease de processamento

**Status:** implementado
**Card:** [TEC-218](https://eduardodurieuxlopes.atlassian.net/browse/TEC-218) — épico TEC-123
**Branch:** `feat/tec-218-lease-de-processamento`

## O que existe quando a card começa

- **`reivindicar`** (`workers/jobs/process_message.py`) faz `SELECT ... FOR UPDATE SKIP LOCKED` e depois `UPDATE` para `PROCESSING`. Isso resolve o caso simultâneo, mas não o sequencial: `PROCESSING` está em `CLAIMABLE_STATUSES`, e o worker que chega depois do commit do primeiro reivindica a linha também.
- **A coluna `messages.claimed_at` já existe, vazia.** Foi reservada pela migration `0003` para esta card. Não há migration nova.
- **Desde a TEC-209** o claim devolve o status anterior. `PROCESSING` nele significa retomar o trabalho de um worker morto, e é aí que a tentativa dele é contada (`_contar_interrupcao`).
- **As escritas depois do claim filtram só pelo id:** fechar `PROCESSED` (em dois lugares), `_marcar_falha`, `_contar_interrupcao` e `_esgotar`.

## D1 — `PROCESSING` só é reivindicável com o lease expirado

O claim grava `claimed_at = clock_timestamp()`. `PROCESSING` volta a ser reivindicável quando `claimed_at < now() - sweep_inflight_after_seconds`.

- **A janela é a do sweeper**, e não um número novo. `test_job_timeout_cabe_dentro_da_janela_do_sweeper` já garante que um job vivo termina dentro dela. Lease expirado quer dizer worker morto, e nunca worker lento.
- **`claimed_at` nulo conta como expirado.** É a linha que ficou em `PROCESSING` antes do deploy desta card. Sem isso, ela não seria retomada nunca.
- **`clock_timestamp()`, e não `now()`**: `now()` é o início da transação, e duas reivindicações na mesma transação gravariam a mesma ficha.

## D2 — `claimed_at` também é a ficha do worker

O claim devolve `Reivindicacao(anterior, lease)`, e toda escrita posterior exige `status = PROCESSING AND claimed_at = lease` (`_do_meu_lease`). O `_esgotar` aceita também `FAILED`, porque vem logo depois de `_marcar_falha`.

É isso que o terceiro cenário da card pede. O lease sozinho impede o segundo worker de **entrar**, mas não impede o primeiro, já substituído, de **escrever**. O caso concreto é o worker A, lento além da janela, que é substituído pelo B. B conclui e fecha `PROCESSED`, e quando A falha, a falha dele não pode virar `FAILED` por cima.

Quando a escrita não acha a linha, o worker registra `message.lease_perdido` com a `etapa` e não grava nada:
- na falha, não conta tentativa, não abre a DLQ e não cria handoff, e a exceção sobe do mesmo jeito para o ARQ;
- no sucesso, não fecha `PROCESSED`, porque a linha é de quem tem a ficha.

## D3 — O log diz por que recusou

`message.skipped` continua com `reason`, e o valor passa a distinguir três casos (`motivo_da_recusa`):
- `lease_ativo`: `PROCESSING` com lease vivo, que é o primeiro cenário da card;
- `reivindicada_em_paralelo`: status reivindicável, mas a linha estava travada por outro claim no mesmo instante;
- `not_claimable`: o valor de antes, mantido para quem já o procura no log.

## O sweeper não muda

Ele reenfileira `PROCESSING` pela idade de `queued_at`, e não pelo lease. Se um job esperou na fila e começou tarde, o reenfileiramento pode chegar com o lease ainda vivo. Nesse caso o job novo sai como `lease_ativo`, e a próxima passagem do sweeper, com o lease já vencido, o retoma. Isso custa no máximo uma passagem de atraso, e não duplica o turno.

## Testes

`tests/integration/test_lease_de_processamento.py`:
- o segundo worker sai com `lease_ativo`, sem rodar o turno nem contar tentativa;
- o lease expirado é retomado, e o turno conclui `PROCESSED` com a tentativa do morto contada;
- um segundo antes da janela, o lease ainda é do primeiro;
- `PROCESSING` sem `claimed_at` é retomável;
- A falha depois de B concluir, e a linha continua `PROCESSED`, sem tentativa contada;
- A conclui depois de B assumir, e A não fecha `PROCESSED`.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Segundo worker não reivindica | `test_segundo_worker_nao_reivindica_mensagem_em_processamento` |
| Lease expirado permite retomada | `test_lease_expirado_permite_retomada` |
| Worker atrasado não sobrescreve o terminal | `test_worker_que_perde_a_corrida_nao_sobrescreve_estado_terminal` |

## Lacunas declaradas

- **L1 — A entrega em si não é protegida pelo lease**, e não precisa ser: a reserva `UNIQUE (message_id, kind)` de `outbound_dispatches` continua sendo o que impede o lead de receber duas vezes. O lease corta o custo duplicado e protege o status, que é o que a card pede.
- **L2 — O turno do worker substituído não é interrompido.** A continua rodando até o fim, e só as escritas em `messages` são barradas. Nesse caso raro, as chamadas de LLM de A continuam sendo pagas. Interromper exigiria cancelar o job de fora, o que é outro problema.

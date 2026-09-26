# TEC-379 — A suíte paralela e o teste que comparava dois relógios

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-379](https://eduardodurieuxlopes.atlassian.net/browse/TEC-379)
**Branch:** `fix/tec-379-suite-paralela`
**Origem:** as duas falhas registradas nos PRs #195 (TEC-199) e #196 (TEC-191).

## D1 — A falha 1 já está consertada na `main`, e esta card não a toca

O id instável de `tests/unit/test_cursor_da_transcricao.py::test_cursor_corrompido_e_recusado` foi trocado por um UUID fixo no commit `34a2108` (`fix(TEC-203): o parametro do cursor corrompido e fixo, e a suite volta a rodar com -n`), que já está na `main` quando esta branch nasce. O comentário ao lado do parâmetro explica o porquê. O que resta a esta card sobre a falha 1 é **confirmar** que `pytest -n 8 --dist loadfile` coleta e roda — não reescrever o que já está certo.

O `uuid4()` que sobra no arquivo, em `test_cursor_sem_fuso_e_recusado`, fica dentro do corpo do teste e não entra em id nenhum: não afeta a coleta.

## D2 — O `antes` vem do relógio do banco, e a ordem continua afirmada

O cenário 2 da TEC-195 pede "autor, lead, campo e **horário**", então afirmar só que o carimbo existe perderia a metade do cenário que fala de horário. A saída é a primeira que a card sugere: `antes = SELECT clock_timestamp()`, na mesma sessão do teste.

É o relógio certo, e não só "um relógio do banco": `EventoAuditoria.criado_em` é sobrescrito pelo trigger `eventos_auditoria_carimbo` com `clock_timestamp()` — o comentário do modelo diz isso —, e não com `now()`. Como `clock_timestamp()` anda dentro da transação e o evento é gravado depois do `SELECT`, `criado_em >= antes` passa a comparar dois instantes do mesmo relógio.

## D3 — A varredura: um defeito só

Procurei `assert` que compara a **ordem** entre um carimbo e outro instante. O que achei, e por que fica:

| teste | por que não é o mesmo defeito |
| --- | --- |
| `test_auditoria_score.py` (`comeco_da_antiga < ...created_at`) | os dois lados vêm do banco (`transaction_timestamp()` e `clock_timestamp()`) |
| `test_notificacao_envio.py` (`limite_min <= sla_limite_em <= limite_max`) | `sla_limite_em` é calculado em Python por `limite_de_aceite`, no relógio do host |
| `test_atendimento_repositorio.py` (`segundo.assumido_em > primeiro.assumido_em`) | `assumido_em` é o `agora` do host, gravado pelo repositório |
| `test_configurar_o_agente.py` (`recente["em"] >= primeira["em"]`) | compara dois carimbos do mesmo relógio |
| `test_ingestion_service.py` (`score - antes_ms`) | o score do job do ARQ é calculado no cliente, no host |

Os muitos `agora = datetime.now(UTC)` restantes montam o horário que o próprio teste grava; não comparam contra o banco.

## D4 — Uma terceira falha, achada na execução com `-n 8`, entra junto

A primeira suíte desta branch com `-n 8` deu 5580 passed e **1 failed**: `tests/integration/test_ingestao_cifra_o_remetente.py::test_fala_no_widget_com_telefone_vincula_pelo_indice` esperava o frame `recebido`. É um conflito semântico entre dois PRs mergeados em sequência: o #199 (TEC-203) escreveu o teste contra o frame antigo, e o #200 (TEC-364) o renomeou para `ack` com `messageId`. Determinístico, e portanto vermelho em toda execução da `main`.

Fica fora do texto da card, mas dentro do objetivo dela — a suíte da `main` rodar limpa com `-n 8` —, e o conserto é uma linha: a asserta passa a ser a mesma forma que `test_consentimento_no_chat_web.py` já usa, `{"tipo": "ack", "messageId": "m-1"}`.

## Critérios de aceite

| critério | onde |
| --- | --- |
| `-n 8 --dist loadfile` coleta e roda | já consertado em `34a2108`; confirmado na execução da suíte desta branch |
| ids estáveis no cursor corrompido | `34a2108` (D1) |
| sem comparar o relógio do host com o do banco | D2 |
| varredura registrada | D3, e no comentário da card |

**Sem emenda ao SRS:** só teste muda.

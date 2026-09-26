# TEC-209 — Degradar com elegância sem perder mensagem

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-209](https://eduardodurieuxlopes.atlassian.net/browse/TEC-209) — épico TEC-208
**Branch:** `feat/tec-209-degradar-com-elegancia`
**Origem:** RNF-27, RNF-32, RNF-33, RT-02 (SRS v1.0) · TEC-122, TEC-174, TEC-228

## O que já existe, e o que falta

| cenário da card | hoje |
|---|---|
| primário fora → retentativa → secundário | **falta**: `MAX_TENTATIVAS = 0` (TEC-228), sem secundário, tetos de 12 a 35 s |
| os dois fora → espera honesta + handoff | **parcial**: o aviso e o handoff `ERRO_DO_AGENTE` saem só depois de **5** falhas, com uma passada do sweeper a cada 30 s entre elas — minutos de silêncio |
| sem índice vetorial → só filtro SQL | **existe** (`catalogo/busca.py::vetor_da_consulta`, TEC-158), testado contra `buscar()` direto |
| WhatsApp fora não derruba o widget | **existe** (`outbound/roteador.py`, `test_whatsapp_indisponivel_nao_afeta_o_canal_web`) |
| worker morto → reprocessa sem duplicar | **parcial**: o sweeper reenfileira e `outbound_dispatches` impede a duplicata, mas um worker morto por SIGKILL nunca conta tentativa, e a linha é varrida para sempre (comentário do Eduardo na card, 23/08) |
| falha permanente → DLQ → reprocessamento manual | **falta**: FAILED com `attempts ≥ 5` é terminal de fato, mas não tem nome, nem lista, nem caminho de volta que não seja SQL à mão |

## D1 — O secundário é outro modelo Claude

Decisão do Eduardo, 26/09/2026. `Settings.modelo_agente_secundario`, com padrão `claude-haiku-4-5-20251001`, o mesmo modelo da moderação. É chamado com o **mesmo** schema estrito, as mesmas ferramentas e o mesmo prompt de sistema; por isso não é preciso um `LlmPort` com dois adaptadores.

**O que isto cobre e o que não cobre.** Cobre throttling, sobrecarga (529) e a indisponibilidade de **um modelo**. Não cobre a Anthropic inteira fora do ar: aí os dois modelos caem juntos e o turno vai para a espera honesta com handoff (D3). O "OpenAI como fallback" da PR-07 e do RT-02 continua sem existir, e fica declarado.

## D2 — Retentativa só na chamada principal, sob um prazo agregado

Decisão do Eduardo, 26/09/2026. A retentativa vale para as duas chamadas que produzem a resposta — `classificar` e `qualificar_investidor` —, e não para as auxiliares (desambiguação, reação, resumo, moderação), que continuam sem retentativa, pelo argumento da TEC-228.

**A cadeia de uma chamada principal:** o primário até 3 vezes (a original e 2 retentativas), com espera de 1 s e depois 2 s entre elas; depois o secundário, uma vez. Cada requisição tem teto de **15 s**, que é o número da RNF-27 (o maior valor medido pela TEC-228 foi 9,26 s).

**Retenta só o que retentar pode resolver:** timeout, queda de conexão, 429, 5xx e 529. Um 400 (saldo esgotado ou contrato quebrado) e uma resposta fora do schema (`RespostaInvalida`) **não** retentam nem trocam de modelo. Eles seguem o caminho de hoje (FAILED, sweeper, handoff na quinta falha), porque refazer a mesma requisição dá o mesmo erro.

**O prazo agregado é o que faz a conta fechar.** Uma fatia com busca faz duas requisições; 4 tentativas × 2 requisições × 15 s são 120 s por fatia, e o turno tem até duas fatias principais (a virada do investidor). Isso sozinho estouraria o `job_timeout` de 240 s. Por isso **todas as chamadas principais de um turno dividem um prazo único de 110 s** (`PRAZO_DA_RESPOSTA_SEGUNDOS`), que inclui as esperas. Cada tentativa recebe `min(teto, o que resta)` e roda dentro de um `asyncio.timeout` com o que resta. Esgotado o prazo, a cadeia desiste mesmo que ainda houvesse tentativas.

O prazo mora no `ContextoMontado`, que é um por turno e é o mesmo objeto nas duas fatias. Ele começa a contar na primeira chamada principal.

**O orçamento.** `_pior_turno()` troca as fatias de classificação e de investidor (`25 × 2 + 35 × 2 = 120 s`) pelo prazo de 110 s: a parcela da Anthropic cai de 167 s para 157 s, e a soma do turno, de 207 s para 197 s, com 43 s de folga para o banco contra os 30 s que o teste exige.

## D3 — Esgotada a cadeia, espera honesta e handoff no mesmo turno

Quando a cadeia termina sem resposta, o classificador levanta **`ProvedorIndisponivel`**. O turno a captura (nas duas fatias principais) e, **na mesma passada**:

1. registra o handoff `ERRO_DO_AGENTE`, com o commit imediato e o resumo agendado, como nos outros cinco sítios;
2. entrega `TEXTO_DO_AVISO_DE_ERRO` (*"Tive um problema técnico aqui e não consegui seguir. Passei sua conversa para um corretor assumir."*) — o mesmo texto e o mesmo kind do caminho de hoje, que já é honesto e não promete nada.

O turno fecha como `"provedor_indisponivel"`, e a linha fecha **PROCESSED**: o lead foi atendido pelo único atendimento possível, e reprocessar repagaria a cadeia inteira para chegar ao mesmo lugar. Deixa de haver minutos de silêncio: o lead recebe a espera em no máximo ~110 s, e não depois de cinco passadas do sweeper.

O gatilho é o `ERRO_DO_AGENTE` que já existe, e não um novo. Para quem atende, o provedor fora e o agente quebrado são o mesmo caso.

## D4 — Worker morto conta tentativa no próximo claim

Um worker que morre por SIGKILL, OOM ou queda do host não executa o `except` que conta a tentativa. A linha fica em PROCESSING, e o sweeper a reenfileira para sempre. Com cem delas, a janela `ORDER BY created_at LIMIT 100` do sweeper ficaria presa nas mesmas cem, e a starvation seria de toda mensagem parada mais nova.

**A tentativa é contada quando a linha é reivindicada de novo a partir de PROCESSING.** Um job vivo nunca fica em PROCESSING por mais de 300 s: `job_timeout` (240 s) mais a espera cabem na janela, e isso já é invariante testada. Então reivindicar uma linha PROCESSING é retomar o trabalho de um worker que não terminou. `process_message` soma 1 a `attempts`, com `last_error = "TrabalhoInterrompido"`. Se isso esgota as tentativas, a linha vai direto para ESGOTADA (D5), sem rodar o turno.

**Consequência aceita:** na janela de exclusão parcial que a TEC-218 existe para fechar (um segundo worker que reivindica uma linha que um primeiro ainda segura), a tentativa também é contada. A contagem erra para o lado de encurtar o orçamento, e não para o do laço infinito.

A duplicata continua impedida pela reserva em `outbound_dispatches` (TEC-227, TEC-273): a resposta que já saiu não sai de novo.

## D5 — A DLQ é um status, ESGOTADA, com lista e reprocessamento

**`MessageStatus.ESGOTADA`**, terminal: nem o sweeper nem o claim a pegam (fica fora de `CLAIMABLE_STATUSES`). A migration `0061` recria o CHECK de `messages.status`. A linha vai para ESGOTADA **no mesmo ponto em que o handoff por erro nasce**, pelos dois caminhos: a quinta falha do `except`, e o claim que esgota por interrupção (D4).

A lista inclui também as FAILED que já esgotaram as tentativas antes desta card: são terminais pelo mesmo critério, e a migration não as reclassifica. A "fila" é a tabela `messages` filtrada por status, e não uma segunda estrutura: a linha já guarda tudo o que o reprocessamento precisa, e uma cópia em outra tabela poderia divergir dela.

```
GET  /api/v1/mensagens/esgotadas            → id, canal, tentativas, último erro, recebida em
POST /api/v1/mensagens/{id}/reprocessar     → 200; 404; 409 se não estiver ESGOTADA
```

A lista **não traz conteúdo nem `conversation_key`**, que é o telefone no WhatsApp: o operador decide pelo erro e pelo instante, e quem precisa ver a conversa abre o lead pelo caminho auditado. Reprocessar zera `attempts`, põe a linha em RECEIVED e tenta enfileirar o job. RECEIVED, e não QUEUED: se o enqueue falhar, o sweeper pega uma RECEIVED em 30 s, e uma QUEUED só depois da janela de 300 s. O handoff aberto na falha continua existindo: reprocessar não o desfaz, porque o corretor pode já estar atendendo.

Permissão nova, **`OPERAR_FILA`**: só ADMIN, de escrita. É operação de plataforma, não de atendimento.

## D6 — Os testes de caos

"Teste de caos" aqui é o componente derrubado por dublê no ponto de integração, com o resto do sistema de verdade: banco, Redis, turno e worker. Não derrubamos containers dentro da suíte, porque isso a tornaria tão frágil quanto as seções do CLAUDE.md sobre o `[WinError 64]` descrevem.

| cenário | como |
|---|---|
| primário fora → secundário | cliente Anthropic falso que responde 529 ao primário e responde ao secundário; conta as tentativas e as esperas |
| os dois fora → espera + handoff | turno inteiro contra banco com o classificador levantando `ProvedorIndisponivel`; afirma handoff, aviso e PROCESSED |
| sem vetor → só SQL | turno inteiro com o embedador que falha; a resposta sai (hoje só `buscar()` direto é testado) |
| WhatsApp fora → widget | já coberto (`test_whatsapp_indisponivel_nao_afeta_o_canal_web`), citado no teste de aceite |
| worker morto → reprocessa sem duplicar | linha deixada em PROCESSING com reserva de entrega já feita; o próximo `process_message` conta a tentativa, responde e não reentrega |
| falha permanente → DLQ → reprocessar | cinco falhas → ESGOTADA; aparece na lista; reprocessar a devolve e ela é processada |

## Arquivos

```
alembic/versions/0061_mensagem_esgotada.py
src/mobia/infra/anthropic.py                 # tetos de 15 s, cadeia, prazo, _pior_turno
src/mobia/app/config.py                      # modelo_agente_secundario
src/mobia/domain/agente/classificador.py     # cadeia de retentativa e secundario; ProvedorIndisponivel
src/mobia/domain/context/montagem.py         # PrazoDaResposta no contexto
src/mobia/domain/agente/turno.py             # espera + handoff na mesma passada
src/mobia/domain/messages/status.py          # ESGOTADA
src/mobia/workers/jobs/process_message.py    # ESGOTADA; contagem da interrupcao
src/mobia/domain/usuarios/permissoes.py      # OPERAR_FILA
src/mobia/api/routes/mensagens.py            # a DLQ
```

## Emendas ao SRS

- **RNF-27, Emenda E-01** — o secundário é outro modelo Claude; a retentativa vale só nas chamadas principais; o prazo agregado de 110 s; o que retenta e o que não; espera e handoff na mesma passada.
- **RNF-32, Emenda E-01** — o que "teste de caos por componente" é nesta suíte.
- **RNF-33, Emenda E-01** — a DLQ é o status ESGOTADA, com a lista e o reprocessamento; o worker morto conta tentativa no claim seguinte.

## Lacunas declaradas

- **L1 — a Anthropic inteira fora do ar não tem secundário.** Os dois modelos caem juntos, e o lead recebe espera com handoff. O OpenAI da PR-07 não existe.
- **L2 — erros que não são de disponibilidade seguem o caminho lento.** Um 400 ou uma resposta fora do schema continuam FAILED, sweeper e handoff só na quinta falha. Esse caminho não tem backoff: a mensagem volta a cada 30 s depois da janela de 300 s.
- **L3 — a ordem dos modelos é fixa.** Não há disjuntor que lembre que o primário está fora: cada turno paga as três tentativas nele antes do secundário, e isso custa até ~50 s por turno enquanto durar a queda.
- **L4 — as chamadas auxiliares não têm secundário.** A desambiguação que falha perde a pergunta, e o resumo que falha cai no resumo de contingência (TEC-176), como hoje.
- **L5 — o reprocessamento não é auditado.** A trilha da RNF-18 não tem ação para ele, e a lista não tem dado pessoal.

# TEC-295 — A moderação de entrada deixa de ser atropelada pelo debounce

**Status:** implementado
**Card:** [TEC-295](https://eduardodurieuxlopes.atlassian.net/browse/TEC-295)
**Branch:** `feat/tec-295-moderacao-na-rajada`
**Origem:** revisão final da TEC-128 (PR #142), achados I1 e I2.
**Linhas citadas:** a TEC-297 mexeu em dois dos arquivos que este documento cita — `turno.py` e `messages/bloqueio.py` —, e só as citações a esses dois envelheceram. As citações aos arquivos que ela **não** tocou (`context/janela.py`, `context/repositorio.py`, `context/score.py` e `followup/repositorio.py`) continuam apontando exatamente certo. O deslocamento dos outros dois **não é uniforme**: cada região do arquivo andou o seu, então não há um número único que conserte as citações, e por isso não há número nenhum neste aviso — qualquer um deles envelheceria no commit seguinte. Nenhuma citação, deslocada ou não, aponta para além do fim do arquivo: é por isso que as deslocadas continuam parecendo válidas sem ser, e por isso nenhuma ferramenta as marca. Confie no nome da função, não no número.

## Objetivo

A TEC-128 fez a mensagem superada por outra mais nova do mesmo lead fechar como `PROCESSED` com o desfecho `"agrupado"`, sem rodar `executar_turno`. Como a moderação de entrada vive dentro do turno, **a fala superada nunca é moderada**. Restaurar as garantias da TEC-236, e decidir o que acontece com a rajada cuja última mensagem é bloqueada.

## O estado antes desta card, conferido no código durante o desenho

- **A moderação de entrada roda num ponto só**, `turno.py:1309`, sobre o corpo da carregadora. A mensagem agrupada não passa por ele.
- **`bloqueada_em` tem quatro consumidores, não um.** Além de `literais_apos` (`context/janela.py:56`), que exclui a fala bloqueada do contexto e do resumo: `contar_mensagens_do_lead` (`context/repositorio.py:1146`), que alimenta o lead score; e a CTE de âncora da cadência de follow-up (`followup/repositorio.py:161-190`). `context/score.py:102,112` declara por escrito que as três leituras têm de concordar sobre o que é "fala do lead".
- **`marcar_bloqueada`** (`messages/bloqueio.py:34-74`) grava `bloqueada_em` e o `ModerationEvent` de ENTRADA **no mesmo commit**. Se falhar, a exceção sobe e a linha vira `FAILED` para o sweeper retentar — nunca existe "marcada sem auditoria".
- **`PROCESSED` é terminal.** Não está em `CLAIMABLE_STATUSES` e o `sweep_stalled` não o seleciona. Uma mensagem que fechou `"agrupado"` está fora de qualquer rota de reprocessamento.
- **Custo medido de uma moderação** (21/09/2026, `claude-haiku-4-5`, sistema de 1073 caracteres ≈ 459 tokens, `max_tokens=16`, sem cache de prefixo e sem batching): **US$ 0,00057 por chamada**, ou US$ 0,57 por mil mensagens.

## O defeito, em duas metades

**(1) A fala superada nunca é moderada, e mesmo assim conta para três subsistemas.** `bloqueada_em` fica nulo, então ela entra na janela de contexto, vai ao modelo, entra no resumo permanente na dobra dos ~40 turnos, **sobe o lead score** e **reancora a régua de follow-up**. É o buraco que a TEC-236 fechou, reaberto pela lateral — e mais largo do que a TEC-236 tratava, porque o score e a cadência não existiam quando ela foi escrita.

**(2) Se a carregadora é bloqueada, a pergunta legítima da rajada morre.** `"tem 2 quartos até 500 mil?"` em t=0, um xingamento em t=1: em t=6 a pergunta é agrupada, em t=7 o xingamento carrega o turno, a moderação bloqueia, sai a recusa e o turno retorna. A pergunta já está `PROCESSED` e nada a reenfileira. Antes da TEC-128 o lead recebia resposta **e** recusa.

## Decisões

### D1 — Cada mensagem superada é moderada no caminho do agrupado

Antes de fechar `PROCESSED`, a mensagem superada passa por `moderador.moderar(corpo, direcao=Direcao.ENTRADA)`. Bloqueada, recebe `marcar_bloqueada` — a mesma função que o turno usa, com a mesma atomicidade entre marca e auditoria.

**Foi considerada e recusada uma chamada única por rajada**, moderando a concatenação: economizaria uma chamada por rajada, mas perde a granularidade. Se a concatenação é bloqueada, não se sabe qual mensagem marcar, e marcar todas removeria a pergunta legítima do contexto e do score — contradizendo a D3. A economia não paga: **US$ 0,57 por mil mensagens** superadas.

O custo volta a ser o de antes da TEC-128 — uma moderação por mensagem recebida. A TEC-128 economizou essas chamadas por acidente, não por decisão.

**Não há regressão de latência.** As superadas acordam antes da carregadora (numa rajada em t=0, 2, 4, elas acordam em t+6 e t+8, contra t+10 da carregadora) e não estão no caminho crítico da resposta.

### D2 — Moderação indisponível no caminho do agrupado: fail-open

Mesma assimetria que o port já documenta e que o turno já pratica: na entrada, o processamento segue. Deixar a exceção subir faria `attempts` crescer e, esgotadas as cinco tentativas, `_encaminhar_por_erro` abriria handoff e avisaria o lead de um erro técnico — por uma mensagem que só precisava ser agrupada.

A consequência é honesta e fica registrada: **provedor de moderação fora do ar significa fala não moderada entrando no contexto**, exatamente como já acontece hoje no turno normal. A diferença é que o turno normal ao menos recusa a resposta; aqui não há resposta a recusar.

### D3 — A superada bloqueada continua fechando `"agrupado"`

Ela ganha a marca e o evento de auditoria, mas não vira turno e não gera recusa própria. A recusa é do turno, e o turno é da carregadora.

Isso mantém a regra da TEC-128 — uma resposta por rajada — e evita o absurdo de o lead receber três recusas por três mensagens reprováveis numa rajada. O log distingue o caso: `message.agrupado` carrega o campo `bloqueada` (booleano), com o retorno de `_moderar_superada` — agrupada e liberada contra agrupada e bloqueada.

### D4 — A carregadora bloqueada entrega a recusa **e** responde o que ficou pendente

Antes desta decisão, o bloco de bloqueio terminava em `return await _entregar_texto_fixo(...)`. Ele deixa de retornar incondicionalmente quando houver fala do lead pendente de resposta — a chamada equivalente está hoje em `turno.py:1385-1391`. (A citação original desta frase, `turno.py:1361-1366`, envelheceu: essas linhas são hoje o comentário da ruling R5, não o `return` que esta frase descreve. O adendo abaixo, que cita `turno.py:1361-1374` para a R5, está correto e não muda.)

**Isto é mais barato do que parece, e o desenho conferiu antes de decidir.** Depois do bloco de bloqueio, o resto do turno trabalha sobre `contexto`, que `montar_contexto` reconstrói do banco, e praticamente não usa `corpo` de novo. "Praticamente" e não "zero": ao reconferir a citação desta frase (que apontava para `turno.py:1364`, hoje dentro do comentário da R5), achou-se uma exceção real — `texto_com_oferta(corpo, texto)` (`turno.py:2761`) lê o `corpo` da própria carregadora bloqueada para decidir se anexa a oferta de corretor do CA-04.1. Não expõe a fala reprovada ao modelo nem ao lead — é uma checagem de padrão sobre um texto que a moderação já viu —, mas o "zero" que esta frase afirmava não é literal. Como `marcar_bloqueada` roda **antes**, `literais_apos` já exclui a própria fala bloqueada da janela de contexto. O turno que continua enxerga a pergunta legítima e não enxerga o xingamento, sem nenhuma mudança em `montar_contexto`.

Três cuidados que a continuação exige:

**O desfecho da recusa ainda decide.** `_entregar_texto_fixo` tem cinco saídas que não entregam nada — janela fechada, recusa permanente da Meta, reentrega suprimida, opt-out concorrente, atendimento humano concorrente. Nas duas últimas, o lead está silenciado ou com humano: a resposta **não** pode sair. A continuação só acontece quando a recusa foi de fato entregue; nos demais casos o turno retorna o desfecho da recusa, como hoje.

**A continuação é condicional, e a condição não é "fui bloqueada".** Se a mensagem bloqueada for a única — sem rajada —, continuar faria o agente responder a nada, ou pior, ao histórico anterior, que é justamente o engajamento que a TEC-233 recusou. A condição é **existir fala do lead posterior à última fala do agente e anterior a esta mensagem**, não bloqueada. É uma consulta sobre `messages`, do mesmo feitio de `superada_por_mais_nova`, e mora ao lado dela em `domain/messages/rajada.py`.

**Duas entregas, dois `kind`.** A reserva de `outbound_dispatches` é UNIQUE em `(message_id, kind)`, então a recusa e a resposta convivem desde que usem `kind` diferentes — e usam, porque a recusa já tem o seu. A idempotência do reprocessamento continua valendo para as duas.

> **Adendo (TEC-295, revisão pós-implementação, 21/09/2026).** Dois pontos que a Task 4 encontrou e que este D4, como escrito, não previa — registrados aqui porque quem reler este desenho daqui a seis meses vai justamente querer mexer no que a R5 existe para proteger.
>
> **R5 — a ordem de cálculo, que travou a Task 4.** Como este D4 está escrito, a leitura natural é calcular a condição da continuação DEPOIS de `_entregar_texto_fixo` devolver — primeiro entrega a recusa, depois decide se continua. Isso não funciona: `_entregar_texto_fixo` grava a própria recusa como fala OUTBOUND do agente antes de retornar, e `ha_fala_pendente_antes` define "pendente" como "INBOUND mais nova que a ÚLTIMA fala OUTBOUND do agente". Calculada depois, a própria recusa vira essa última fala e apaga a pendência da pergunta legítima — o booleano sai sempre `False`, e a continuação que esta D4 existe para habilitar nunca rodaria. A ordem certa, e a que a implementação usa, é calcular `tem_pendencia` **antes** de chamar `_entregar_texto_fixo`, sobre o estado que existia antes da recusa. Não foi uma escolha de implementação — foi um defeito deste desenho, e por isso o comentário em `turno.py:1361-1374` (ruling R5) é deliberadamente longo: existe para resistir a quem tentar "simplificar" a chamada de volta para perto do uso.
>
> **R6 — a frase sobre os dois `kind`s, acima, estava errada quando foi escrita.** Ela afirma "a recusa e a resposta convivem desde que usem `kind` diferentes — e usam, porque a recusa já tem o seu". Isso era falso no momento em que foi escrito: antes da Task 4, a recusa de entrada saía pelo `kind` default de `_entregar_texto_fixo`, `KIND_DA_RESPOSTA` ("reply") — o mesmo que a resposta da continuação usa. A colisão que a frase dizia não existir era exatamente o segundo defeito que travou a Task 4. A implementação corrigiu a premissa, não só o sintoma: criou `KIND_DA_RECUSA_DE_ENTRADA` (`domain/moderacao/port.py`), só para a recusa de entrada, e só depois disso a frase acima passou a ser verdadeira.

### D5 — A janela de corrida entre a marca e o contexto fica aberta, declarada

A superada é moderada em t+6; a carregadora monta contexto em t+10. No caminho normal a marca já existe e a fala sai da janela. Se o job da superada falhar ou demorar, a carregadora monta contexto **antes** da marca existir, e a fala não moderada entra naquele turno.

**Aceito.** A exposição é de um turno, exige uma segunda falha para acontecer, e o resumo permanente continua protegido porque a dobra acontece muito depois — o sweeper recupera a superada e grava a marca bem antes dos ~40 turnos.

A alternativa recusada era a carregadora conferir, antes de montar contexto, se há INBOUND anterior sem moderação: custa uma consulta em **todo** turno saudável para um caso que já exige falha de job.

**Com a D4, a mesma janela tem uma segunda consequência, não só no contexto.** Numa rajada de duas falas reprováveis, se o job da superada falhar, em t+10 a marca ainda não existe: `ha_fala_pendente_antes` conta a fala reprovável como pendência (ela é INBOUND e `bloqueada_em` ainda é NULL), `tem_pendencia` dá `True`, e a carregadora entrega a recusa **e roda um turno inteiro respondendo àquela fala reprovável** — o engajamento que a TEC-233 recusou. A decisão de aceitar a janela continua valendo; o que faltava registrar era esta consequência nova, que só existe desde a D4.

### D6 — O que NÃO muda

- `superada_por_mais_nova` continua sem filtrar `bloqueada_em`. O filtro seria quase sempre inerte, e a D1 torna a questão irrelevante: a superada agora é moderada de qualquer jeito.
- As três exceções da TEC-128 (opt-out, pedido de humano, entrega parcial) continuam como estão. A moderação entra no ramo que hoje fecha `"agrupado"`, não nos três que já furam a janela. Só a entrega parcial cai na moderação normal do turno; opt-out e pedido de humano **retornam antes dela** (`turno.py:1177` e `turno.py:1307`), e essa fala continua sem ser moderada — buraco pré-existente, que esta card não fecha. (**Fechado pela TEC-297** (21/09/2026): a moderação de entrada passou a rodar no fecho do invólucro de `executar_turno`, por onde quer que o turno saia, e os dois ramos aqui citados passaram a pagar a moderação também — o buraco que esta frase descreve não existe mais. Ver a D7/D8 do desenho da TEC-297.)
- `montar_contexto`, `contar_mensagens_do_lead` e a CTE de follow-up não mudam: elas já filtram por `bloqueada_em IS NULL`, e passam a receber a marca que faltava.

## As quatro garantias a não reabrir

A implementação tem de preservar, e os testes têm de provar:

1. **(TEC-233)** A fala reprovada na entrada nunca vira a resposta daquele turno.
2. **(TEC-236)** A fala reprovada nunca entra em contexto de turno nenhum nem no resumo permanente.
3. **(TEC-236/TEC-142)** Marca e auditoria saem no mesmo commit; não existe "marcada sem auditoria".
4. **(TEC-150/cadência)** Score e follow-up usam a mesma definição de fala do lead — `direction=INBOUND AND bloqueada_em IS NULL` — e continuam concordando com a janela de contexto.

## Testes

| teste | o que prova |
| --- | --- |
| superada reprovável recebe `bloqueada_em` e `ModerationEvent` | a D1, e a garantia 3 |
| superada reprovável não entra em `literais_apos` | a garantia 2, pela janela e não pelo desfecho |
| superada reprovável não conta em `contar_mensagens_do_lead` | a garantia 4, lado do score |
| superada reprovável não ancora a cadência de follow-up | a garantia 4, lado do reengajamento |
| superada liberada continua entrando no contexto | que a D1 não bloqueia o caminho comum |
| moderação indisponível na superada: fecha `"agrupado"`, não vira `FAILED` | a D2 |
| superada bloqueada fecha `"agrupado"` e não entrega recusa própria | a D3 |
| carregadora bloqueada com pergunta pendente: recusa **e** resposta | a D4 |
| carregadora bloqueada **sem** nada pendente: só a recusa | a condição da D4, que é o que impede o engajamento que a TEC-233 recusou |
| carregadora bloqueada cuja recusa não foi entregue por opt-out concorrente: nenhuma resposta | a primeira ressalva da D4 |
| as duas entregas usam `kind` diferentes e ambas reservam | a terceira ressalva da D4 |

## Fora de escopo

- **O texto fixo de recusa continua sem passar pela moderação de saída.** Lacuna declarada pela TEC-233 e não é desta card.
- **`moderation_events` continua sem unicidade por mensagem.** Append-only por desenho: duas tentativas de recusar a mesma fala foram duas recusas.
- **Nenhuma mudança na janela do debounce**, no `superada_por_mais_nova` ou nas três exceções da TEC-128.

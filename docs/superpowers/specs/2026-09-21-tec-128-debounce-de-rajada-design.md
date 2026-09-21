# TEC-128 — A rajada de mensagens vira um turno só

**Status:** implementado
**Card:** [TEC-128](https://eduardodurieuxlopes.atlassian.net/browse/TEC-128)
**Branch:** `feat/tec-128-debounce-de-rajada`
**Origem:** RF-01, RN-01.6 (SRS v1.0). A TEC-182 deixou o bilhete de que quem implementasse a RN-01.6 teria de furar a janela para o opt-out.

## Objetivo

Hoje, o lead que escreve três mensagens seguidas recebe três respostas. Fazer a rajada virar um turno só, com uma resposta que considere tudo que ele disse.

## O estado de hoje, conferido no código

O que já está resolvido e o que não está:

- **O conteúdo já se agrupa; a resposta não.** `executar_turno` recebe **uma** `Message` (`turno.py:819-829`), mas `montar_contexto` lê tudo que foi commitado desde a marca d'água do resumo, nas duas direções (`context/janela.py:33-67`). Então, numa rajada de três, o terceiro turno já *vê* as duas primeiras. O defeito visível não é a resposta ignorar o que o lead disse — é serem três.
- **Um job por mensagem.** `_try_enqueue` chama `enqueue_process_message` por `messages.id`, com `_job_id = f"msg:{message_id}"` (`infra/queue.py:31`), e logo depois marca a linha `QUEUED` (`messages/service.py:138-164`).
- **Não existe debounce nem nada que se pareça.** `_defer_by` e `_defer_until` têm zero ocorrências no repo; todo agendamento é `cron` no `WorkerSettings` (`workers/main.py:184-225`) ou task in-process. O arq pinado é 0.28.0, e `enqueue_job` aceita `_defer_by`.
- **A tabela já tem o que é preciso.** `messages.created_at` é `server_default=func.now()` — o relógio é o do Postgres — e `ix_messages_timeline (channel, conversation_key, created_at DESC)` já existe (`messages/models.py:160-165`).

## Decisões

### D1 — O debounce é incondicional, e isso emenda a RN-01.6

A RN-01.6 e a card são condicionais: *"se o lead enviar 3 mensagens em menos de 8 segundos, o sistema aguarda"*. **A condição não é implementável**, e não por falta de engenho: no instante em que a segunda mensagem chega, responder à primeira já teria acontecido. O sistema não sabe que houve rajada antes de a rajada acabar.

Pior que impossível, a versão condicional é irreversível. A entrega reserva `outbound_dispatches (message_id, kind)` com UNIQUE **antes** do efeito externo (`outbound/port.py:287-305`), e a reserva é commitada. Desfazer uma resposta em voo exigiria apagar reserva já gravada, além de despublicar na Meta, que não existe.

Então **toda** mensagem espera a janela, inclusive a isolada. O custo é latência no caso comum; a alternativa é não entregar "uma única resposta", que é o que a card pede.

A RN-01.6 recebe emenda (ver "Emendas ao SRS", abaixo).

### D2 — O timer é `_defer_by` por mensagem, e o reinício da contagem é aritmético

`enqueue_process_message` passa a aceitar um atraso e o repassa como `_defer_by`. Cada mensagem ganha o seu próprio job diferido, e **nada cancela nem reprograma coisa alguma**.

O reinício que a card pede sai de graça. Três mensagens em t=0, 2, 4 acordam em 6, 8, 10; as duas primeiras se descobrem superadas e saem sem responder; a terceira responde em t=10, que é exatamente `última + 6s`. A propriedade "mensagem nova reinicia a contagem" é consequência de cada mensagem carregar seu próprio relógio, não de um mecanismo.

Foram consideradas e recusadas:

- **Um job de rajada por lead, que se re-agenda** (`_job_id = f"rajada:{channel}:{conversation_key}"`). Trocaria o `_job_id` por mensagem — que é o que torna o `sweep_stalled` idempotente — por um por lead. E o re-agendamento tem corrida com a própria chave: no instante em que o job roda, `arq:job:rajada:X` ainda existe, e re-enfileirar-se com o mesmo id devolve `False`.
- **Uma cron varrendo leads com rajada fechada.** É o idioma que o repo já usa nos cinco sweeps, mas para 6 segundos de janela a cron teria de bater a cada ~2s e varrer todo lead com INBOUND pendente a cada tique. A latência ganharia jitter e o caso comum — mensagem isolada — passaria a depender de um scan global.

### D3 — Quem é o turno se decide por uma consulta, não por estado guardado

No topo de `process_message`, depois do `claim_message` e da leitura da linha, uma pergunta ao banco: **existe INBOUND mais nova para este `(channel, conversation_key)`?** Se existe, esta mensagem não é o turno.

Nenhuma chave em Redis, nenhuma coluna nova, nenhuma tabela. O estado "a rajada ainda está aberta" não é guardado em lugar nenhum — é recomputado a partir de `messages`, que é onde ele já está.

**O desempate por `id` não é zelo, é obrigatório.** Um envelope da Meta pode trazer várias mensagens, e `_persist` as insere num `INSERT` só, numa transação só (`messages/service.py:60-93`). Como `created_at` é `server_default=func.now()`, que em Postgres é o instante da **transação**, todas as mensagens do mesmo envelope nascem com `created_at` idêntico. Uma comparação só por `created_at` faria as irmãs do mesmo envelope se considerarem mutuamente superadas — e **nenhuma** responderia. A comparação é `(created_at, id) > (created_at desta, id desta)`, o mesmo par ordenado que `literais_apos` já usa (`context/janela.py:33-67`).

O filtro leva `direction = 'INBOUND'`: a fala do próprio agente não supera ninguém.

### D4 — A mensagem superada fecha como `PROCESSED`, com desfecho próprio

Ela vira `PROCESSED` pelo mesmo caminho da mensagem respondida, e o job devolve `"agrupado"` — um literal novo em `ResultadoDoProcessamento`, ao lado de `"skipped"`.

Não reaproveitar `"skipped"` é deliberado. `"skipped"` hoje significa *não consegui pegar a mensagem* — claim recusado ou linha sumida (`process_message.py:41-43`), os dois anômalos. `"agrupado"` significa *peguei, e o certo era não responder*, que é o caminho feliz da rajada. Colapsar os dois tornaria ilegível qualquer contagem de anomalia no log.

`PROCESSED` e não um estado novo: a linha cumpriu o seu papel no pipeline, e o conteúdo dela não se perde — entra no turno da carregadora pela janela de contexto, que é o mecanismo que já existe.

### D5 — O opt-out fura a janela, e há dois furos porque um só não basta

Sem tratamento, o debounce **engole opt-out**. Sequência: o lead manda "não quero mais receber mensagens" em t=0 e, arrependido ou não, mais uma mensagem em t=2. A carregadora é a segunda; a primeira se descobre superada e sai sem rodar o turno. `pediu_optout` nunca é chamado sobre ela, e **o opt-out não é registrado** — silenciosamente. Este é o defeito que a TEC-182 previu por escrito.

Dois ajustes, e os dois são necessários:

**(a) Opt-out não espera.** Na ingestão, uma mensagem cujo texto satisfaça `pediu_optout` é enfileirada **sem atraso**. `pediu_optout` é puro e determinístico, sem chamada paga (`optout/deteccao.py:81-92`), e na ingestão o texto está em claro no `ParsedMessage`, antes de ser cifrado.

O encanamento era menor do que parecia. Antes desta card, `ingest()` fazia `for message_id in message_ids: await self._try_enqueue(message_id)`, e `message_ids` podia ser um subconjunto de `parsed` — as duplicatas caem no `ON CONFLICT` —, sem garantia de ordem. O `RETURNING` do `_persist` **já trazia `provider_message_id` junto de `id`** (`messages/service.py:86-88`), para contar os descartes do TEC-125; faltava só `_persist` parar de jogar esse par fora na última linha e `ingest` casar cada id com o texto do `ParsedMessage` correspondente. É exatamente o que a implementação faz: `_persist` devolve `list[tuple[id, provider_message_id]]` e `ingest` monta `texto_de` a partir de `parsed` para decidir, mensagem a mensagem, `atraso_segundos=0.0 if pediu else janela`.

**(b) A mensagem superada que pediu opt-out não é descartada.** Mesmo com (a), há corrida: a mensagem de opt-out vai para a fila sem atraso, mas se outra mensagem chegar nos milissegundos entre o enqueue e o job acordar, a checagem da D3 a declararia superada. Então a checagem ganha exceção: superada **e** `pediu_optout` falso é que resulta em `"agrupado"`. Aqui o texto vem cifrado e precisa de `decrypt`, como `turno.py:882` já faz.

**Corrigido depois da entrega:** `decrypt` devolve `str | None` — `text_body` é nulo para conteúdo que não é `TEXTO` (imagem, áudio) —, e o parágrafo acima não previa esse caso. A Task 4 fechou a lacuna com `bool(...)` por fora e não `bool(corpo) and ...`: só a forma curta-circuitada estreita `corpo` de `str | None` para `str` dentro da chamada, no mesmo idioma de `turno.py:884-886`. O guarda em `process_message.py` ficou `if not bool(corpo and pediu_optout(corpo))`, então uma mensagem superada sem corpo em claro (mídia sem legenda) cai no mesmo `"agrupado"` de uma mensagem superada comum — nunca no furo do opt-out, que só existe para texto.

Não há decisão duplicada. `pediu_optout` é a mesma função pura sobre o mesmo texto da mesma mensagem — os três sítios não podem divergir sem que a função mude para todos.

Com os dois, a ordem oposta também fecha: lead manda pergunta em t=0 e opt-out em t=2. O opt-out roda na hora, registra e confirma; em t=6 a pergunta acorda, se descobre superada, sai como `"agrupado"`. Uma mensagem só para o lead, e é a confirmação de opt-out.

### D6 — O indicador de digitação passa a contar do recebimento, não do início do job

A TEC-274 dispara o indicador 4 segundos depois de o job começar (`process_message.py:311-316`, `config.py:164`). Com o defer, isso viraria `última + 10s`: o lead ficaria 6 segundos em silêncio absoluto antes de ver qualquer sinal.

A correção é medir a idade da mensagem: `apos_segundos = max(0, configurado - (agora - message.created_at))`. Para a carregadora de uma rajada, a espera já passou de 4s ao acordar, e o indicador sai imediatamente.

Isto não é feature nova — é reparar dano que esta card causa. A própria docstring da TEC-274 já diz qual é o relógio certo, e o debounce é o que a fez deixar de bater:

> O relogio mede o turno INTEIRO […] e o silencio que o lead percebe.

O silêncio que o lead percebe começa quando ele aperta enviar, não quando o worker acorda.

**Decisão de produto (Task 5): com os defaults, o indicador passa a disparar em praticamente todo turno, não só nos lentos — e isso foi avaliado e aceito.** A janela do debounce (6s) é maior que o limiar do indicador (4s, `indicador_de_digitacao_apos_segundos`). Para qualquer mensagem que não seja superada — inclusive a isolada, por causa da D1 —, a idade ao acordar já passa de 4s, então `apos_segundos` já chega zerado e o indicador sai de imediato, sempre. Antes desta card isso era sinal de turno lento; agora é o caso comum. A alternativa seria subir o limiar do indicador para acompanhar a janela, mas a resposta rápida que o limiar de 4s protegia **deixou de existir** do ponto de vista do lead — toda mensagem já espera pelo menos 6s antes de qualquer processamento começar. Disparar o indicador em todo turno deixa de ser ruído e passa a ser o sinal honesto do que o lead de fato experimenta: silêncio até a janela fechar, indicador depois.

### D7 — O `sweep_stalled` continua sendo a rede, e não fura a janela por acidente

O sweeper re-enfileira sem atraso (`sweep_stalled.py:113-119`). Durante os 6 segundos de janela a chave `arq:job:msg:{id}` existe, então o re-enqueue devolve `False` e o sweeper registra `sweep.enqueue_skipped` — o comportamento certo, e já o de hoje.

As duas janelas do sweeper continuam corretas sem ajuste: `sweep_received_after_seconds = 30` só alcança `RECEIVED`, e uma mensagem só fica em `RECEIVED` se o enqueue falhou; a mensagem em espera já está `QUEUED`, coberta por `sweep_inflight_after_seconds = 300`. Passados os 300s, o sweeper a re-enfileira **sem atraso** — que é o desejável num caminho de recuperação, onde a janela de rajada há muito se fechou.

### D8 — A janela é configuração, não constante

`debounce_de_rajada_segundos: float = 6.0` em `Settings`. Nasce configurável porque é um número de produto e vai ser mexido: a card fixa 6, e o valor certo só se descobre com lead de verdade. Zero desliga o debounce, o que é o caminho de fuga se o piloto reclamar da latência.

### D9 — A prosa que passa a mentir

- **`docs/srs/…v1.0.md:130` (RN-01.6)** — a condição "3 mensagens em menos de 8 segundos" deixa de descrever o sistema. Emenda E-01, abaixo.
- **`docs/superpowers/specs/2026-09-01-tec-182-opt-out-design.md:161`** — *"procurar por `debounce` devolve zero"* e *"o cenário é vacuamente verdadeiro"* deixam de valer. O documento é um registro histórico, mas a afirmação é sobre o repo de hoje; recebe nota apontando para este desenho.
- **`docs/superpowers/specs/2026-08-23-tec-122-ingestao-whatsapp-design.md:25`** — atribui a escolha do ARQ, entre outras coisas, ao `cron` de que "TEC-128 (debounce 6s) vai precisar". A TEC-128 não usa cron, usa `_defer_by`. A escolha do ARQ continua certa; a justificativa, não.
- **`CLAUDE.md:209`** — diz que `executar_turno` tem 1877 linhas; tem 2706. Não é desta card, mas foi encontrado ao mapear o fluxo e fica registrado para não se perder.

## Emendas ao SRS

**Emenda E-01 (TEC-128, 21/09/2026)**, aninhada sob a RN-01.6: o debounce é **incondicional** — toda mensagem recebida aguarda a janela antes de virar turno, e não apenas a que integra uma rajada de três em oito segundos. A condição original não é implementável: a rajada só é reconhecível depois de terminada, e a esta altura a resposta à primeira mensagem já teria sido entregue e a sua reserva em `outbound_dispatches` commitada. A janela é configurável (`debounce_de_rajada_segundos`, default 6s) e mensagem de opt-out não a aguarda.

## Testes

Os quatro cenários Gherkin da card, mais o que a leitura do código revelou:

| teste | o que prova |
| --- | --- |
| três mensagens em cinco segundos → uma resposta | o cenário 1 da card |
| a resposta contempla o conteúdo das três | via contexto; ancora que a D3 não perde conteúdo |
| mensagem nova durante a espera → a resposta sai em `última + janela` | o cenário 2, medido pelo relógio e não pelo mecanismo |
| mensagem isolada responde após a janela | o cenário 3 |
| opt-out no meio da rajada → confirmação imediata e nenhuma outra resposta | o cenário 4 |
| opt-out **antes** de outra mensagem → opt-out registrado | o defeito da D5; falharia sem os dois furos |
| duas mensagens do mesmo envelope (`created_at` idêntico) → uma responde | o desempate por `id` da D3; falharia com comparação só por `created_at` |
| a fala do agente não supera a mensagem do lead | o filtro `direction = 'INBOUND'` da D3 |
| superada fecha em `PROCESSED` com `"agrupado"` | a D4 |
| janela zero desliga o debounce | a D8, e é o que mantém os testes existentes rápidos |
| indicador sai imediatamente para mensagem que já esperou a janela | a D6 |

Os testes de tempo usam janela curta por configuração, não `sleep` de seis segundos.

## Fora de escopo

- **O lease de exclusão mútua (TEC-218).** O debounce reduz a chance de dois workers do mesmo lead em paralelo, porque a rajada passa a render um turno só — mas não a elimina, e não é este o mecanismo que a resolve. `messages.claimed_at` continua sem ninguém escrevendo nela.
- **Unificar histórico entre canais (TEC-129).** A consulta da D3 é por `(channel, conversation_key)`; uma rajada que atravesse WhatsApp e web não se agrupa. Correto enquanto os canais não estiverem unificados.
- **Áudio e mídia (TEC-131, TEC-132).** A rajada mista não tem tratamento especial: hoje só `TEXTO` chega com corpo.
- **Mexer em `executar_turno`.** A função não fica sabendo que existe debounce. Ela continua recebendo uma `Message` e montando o contexto do jeito de sempre.

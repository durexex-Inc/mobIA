# TEC-188 — Aplicar teto de 4 mensagens não respondidas

**Status:** desenhado em 2026-09-04 na branch `feat/tec-188-maximo-sem-resposta`.

**Card:** [TEC-188](https://eduardodurieuxlopes.atlassian.net/browse/TEC-188) — Must (MoSCoW). Origem: RF-13, RN-13.7 (SRS v1.0, em `docs/srs/`); risco RN-B02. Épico de follow-up e opt-out.

**Branch:** `feat/tec-188-maximo-sem-resposta`.

**Destravada por [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183)** (a cadência derivada), único bloqueio declarado. Convive com a [TEC-185](https://eduardodurieuxlopes.atlassian.net/browse/TEC-185) (janela de horário), mergeada em `main` como `067920f`, que é a outra mitigação do mesmo risco RN-B02.

## Objetivo

A história é da Anelise, gerente comercial: *"quero um limite absoluto de mensagens sem resposta, para não perder o número da imobiliária por denúncia de spam"*. Must porque o bloqueio do número na Meta derruba o canal principal do produto inteiro; a card se descreve como *"a proteção final, acima de qualquer regra de cadência"*.

**O que esta card entrega:** o predicado do máximo, o contador que o alimenta, e o evento que registra o momento em que um lead sai do alcance da automação.

**O que ela não entrega, e a seção D5 explica sem maquiagem:** nenhuma mudança de comportamento observável no envio, porque hoje o teto não é alcançável em excesso. A guarda existe para ser herdada, não para agir agora.

## O que já existe, e que o desenho reusa

**A tabela `followups` e a âncora.** Cada linha registra uma tentativa que de fato disparou, sob a `ancora_em` que é a última fala não bloqueada do lead. É o registro de "mensagem automática enviada" que existe hoje.

**O molde da guarda compartilhada.** A TEC-185 pôs `horario_permite_envio` em `domain/outbound/` — pura, keyword-only, fora de `GuardedOutbound.send` — precisamente porque a regra vale para toda automação e não para a resposta ao lead. O máximo é a segunda guarda dessa família e mora ao lado.

**O precedente de escrever a guarda antes do consumidor.** O comentário de `GuardedOutbound.send` (TEC-182) diz literalmente que *"a TEC-183 vai criar um segundo caminho de envio. Quem HERDA desta classe ganha a guarda de graça, sem precisar lembrar dela"*. Aquela guarda foi escrita antes de existir quem a usasse, de propósito. Esta card faz o mesmo movimento — ver a D5.

**A consulta de candidatos e o subselect por âncora.** `candidatos_a_followup` já calcula `MAX(tentativa_numero)` sob a âncora, servido por `ix_followups_lead`. O contador desta card é um segundo agregado sobre exatamente as mesmas linhas.

## Decisões

### D1 — O contador é `COUNT`, e o vizinho imediato é `MAX`

**Esta é a decisão mais fácil de errar da card, e ela contradiz o módulo ao lado.**

`ja_disparada`, da TEC-183, é `MAX(tentativa_numero)` sob a âncora, e a docstring de `tentativa_devida` gasta três parágrafos explicando por que uma contagem ali estaria errada.

Para o máximo anti-spam a resposta é a inversa. A régua devolve a **maior** tentativa vencida e pula as intermediárias: um lead `QUENTE` calado há dez dias recebe **uma** mensagem, a de número 4. Sob aquela âncora, `MAX = 4` e `COUNT = 1`.

A RN-13.7 conta **mensagens que saíram**, não posições na régua. Ler `tentativa_numero` cortaria da automação um lead que recebeu uma única mensagem — o oposto do que a regra protege, e um corte que ninguém perceberia, porque o lead simplesmente pararia de receber follow-up sem nenhum sintoma.

Então: `ja_enviadas = COUNT(*)` sob a âncora. Os dois agregados vivem lado a lado na mesma consulta, sobre as mesmas linhas, com respostas corretas opostas, e o comentário da consulta diz isso.

### D2 — "Qualquer resposta zera o contador" já é verdade, sem código

A RN-13.7 pede que a resposta do lead zere a contagem. No modelo derivado isso não precisa de implementação: a âncora **é** a última fala do lead, então uma resposta move a âncora, e a contagem sob a âncora nova começa em zero. As linhas antigas continuam na tabela, sob a âncora antiga, e não entram no `COUNT`.

É a terceira regra desta sequência de cards que cai da forma escolhida pela TEC-183, depois do cancelamento da RN-13.4 e do adiamento da RN-13.3.

**Uma consequência que surpreende e é intencional:** uma resposta **bloqueada pela moderação** não zera o contador, porque a âncora só olha `bloqueada_em IS NULL`. É coerente com a lacuna 8 do desenho da TEC-183, que já declarou que um turno tratado pelo produto como não-dito não adia o follow-up. Aqui o efeito é mais severo — um lead cuja única resposta foi bloqueada continua acumulando —, e por isso fica declarado como lacuna, não escondido como detalhe.

### D3 — "Ciclos diferentes somam" é o mesmo `COUNT`, e a tensão aparente se desfaz

A card pede duas coisas que, lidas juntas, parecem brigar:

- *"O teto é global por lead, não por cadência: tentativas de ciclos diferentes somam."*
- *"Qualquer resposta do lead zera o contador."*

O critério de aceite as junta: *"2 mensagens não respondidas de uma cadência anterior E 2 da cadência atual"*. Se o lead não respondeu, o que separa as duas cadências?

**Só a temperatura.** A regra da TEC-183 diz que *"mudança de temperatura recalcula a cadência restante"*, e é isso que faz um ciclo virar outro sem o lead falar. E no modelo derivado a temperatura não move a âncora — só a fala do lead move. Portanto as tentativas dos dois ciclos estão **sob a mesma âncora**, e o `COUNT` da D1 já as soma.

A regra e o modelo concordam. A soma não precisa de código próprio, e o cenário de aceite é escrevível exatamente como está escrito: um lead que recebe duas tentativas como `MORNO`, esquenta, e recebe mais duas como `QUENTE`.

### D4 — O máximo é constante de módulo, não configuração e não derivado

`MAXIMO_SEM_RESPOSTA = 4`, em `src/mobia/domain/outbound/antispam.py`.

**Não derivado de `CADENCIA`.** Seria a escolha reflexa neste repo — `INTERVALO_MINIMO` e os tetos por temperatura da consulta são derivados de propósito, para não virarem segunda fonte. Aqui derivar seria o erro: o máximo ficaria igual ao teto da cadência por construção, e a regra *"o teto prevalece sobre a configuração de cadência: mesmo que alguém configure 6 tentativas, o envio para na quarta"* viraria tautologia. O sentido da RN-13.7 é ser um número **independente** que sobrevive a alguém alongar a cadência.

**Não vai para `Settings`.** A TEC-185 pôs a janela lá porque a card dela pedia janela ajustável. Esta card pede o contrário, na letra: *"máximo absoluto"*, e *"prevalece sobre a configuração"*. Um máximo ajustável por variável de ambiente é um máximo que a próxima pessoa com pressa aumenta — que é exatamente o que a Meta cobra quando bloqueia o número.

### D5 — A guarda não pode disparar hoje, e isso está declarado

**O teto de 4 coincide exatamente com o ponto em que a cadência do `QUENTE` já para sozinha.**

A aritmética: o `UNIQUE (channel, conversation_key, ancora_em, tentativa_numero)` admite no máximo uma linha por número de tentativa sob uma âncora, e a maior tupla de `CADENCIA` é a do `QUENTE`, com quatro posições. Logo `COUNT <= 4` sempre. Um lead com quatro linhas tem `MAX = 4`, e o corte de esgotamento da consulta já o exclui da candidatura.

Verificado contra os caminhos que poderiam furar isso, e nenhum fura: um lead `FRIO` esgota em 2 e um `MORNO` em 3, ambos abaixo do máximo; um lead que esquenta depois de esgotar volta a ser candidato, mas o número de tentativas distintas continua limitado a quatro; uma temperatura que cai não cria posições novas.

**Então esta card não muda o comportamento de envio de nada, hoje.** Ela entrega:

- **O evento**, que é a única mudança observável agora — ver a D6.
- **A guarda e o predicado**, que a TEC-184 (envio de verdade) e a TEC-171 (lembretes) herdam em vez de precisarem lembrar.

A alternativa era entregar só o evento e deixar a guarda para a card que a tornasse alcançável. Rejeitada pelo precedente do próprio repo: a guarda de opt-out foi escrita em `GuardedOutbound` antes de existir consumidor, e o comentário dela explica que o motivo é justamente não depender de alguém lembrar. Uma regra Must de segurança que espera para ser escrita é uma regra que a próxima card esquece.

**O que faz a guarda passar a valer:** um segundo produtor de mensagem automática. Enquanto `followups` for a única fonte, o máximo é redundante com o corte de esgotamento.

### D6 — O evento sai uma vez, no instante em que a contagem fecha

`followup.antispam_atingido`, emitido junto do lote — depois do `commit`, como `followup.devido` — quando a linha recém-gravada faz `ja_enviadas + 1` alcançar `MAXIMO_SEM_RESPOSTA`.

A alternativa era emitir a cada supressão, enquanto o máximo vigorasse. Rejeitada: a varredura roda de 5 em 5 minutos, e um lead que nunca mais responde produziria a mesma linha para sempre. *"Atingir o teto"* é um instante, não um estado — o estado é derivável da tabela a qualquer momento.

Sem PII, como todo evento deste subsistema: canal, chave de conversa e a contagem. A mesma disciplina que `followup.devido` e `moderacao.entrada_bloqueada` seguem.

### D7 — O nome é `antispam`, e não `teto`

**`teto` já está tomado neste repo, e pelo conceito exatamente vizinho.** `_TETOS_POR_TEMPERATURA` em `followup/repositorio.py` é o teto **de tentativas da cadência** — a coisa sobre a qual este máximo *prevalece*. Ainda há `contexto_teto_de_tokens`, `teto_de_tokens_efetivo` e o teto por chamada do cliente Anthropic.

Chamar os dois de "teto" no mesmo pacote faria a próxima pessoa ler `teto` e precisar decidir qual — que é a ambiguidade que a D3 da TEC-185 evitou com `horario` em vez de `janela`.

Então: módulo `antispam.py`, constante `MAXIMO_SEM_RESPOSTA`, predicado `antispam_permite_envio`, evento `followup.antispam_atingido`. A prosa da card e do SRS continua dizendo "teto", que é o termo do negócio.

### D8 — O predicado espelha o da janela

```python
def antispam_permite_envio(*, ja_enviadas: int) -> bool
```

Puro, keyword-only, em `domain/outbound/`, ao lado de `horario.py`, e pela mesma razão: a regra cobre follow-up, lembrete e reengajamento, e sob `followup/` a TEC-171 não o acharia.

**A simetria com `horario_permite_envio` é deliberada.** As duas guardas de automação têm a mesma forma, o mesmo lugar e o mesmo formato de nome, então a lista de guardas da varredura se lê como uma lista e não como três decisões sem relação.

**E ele também NÃO mora em `GuardedOutbound.send`**, pela mesma razão da D4 da TEC-185: aquele caminho carrega a resposta ao lead, e o máximo é sobre mensagem **automática**. Um lead no máximo que escreve continua sendo respondido — e, aliás, essa resposta dele zera o contador (D2).

## Fluxo

1. A consulta de candidatos devolve, por lead, a âncora, `ja_disparada` (`MAX`) e `ja_enviadas` (`COUNT`).
2. Na varredura, as guardas em ordem: `tentativa_devida` (pura), `antispam_permite_envio` (pura), `esta_em_optout` (banco).
3. Quem passa recebe a linha em `followups`.
4. Se a linha gravada completou o máximo, o evento `followup.antispam_atingido` entra no lote.
5. Os eventos do lote saem depois do `commit`.

**A ordem segue o critério que a TEC-183 já fixou:** as guardas puras antes da ida ao banco, porque a premissa que justifica consultar o opt-out por candidato é que o conjunto que sobra depois dos cortes puros é pequeno. O máximo é puro e entra na frente do opt-out.

**A ordem entre o máximo e o opt-out não muda o que acontece, só o que custa.** As duas barram por `continue`, e o evento da D6 só sai quando uma linha é gravada — então nenhuma ordem faz o evento ser emitido para quem pediu silêncio. Fica registrado porque a ordem inversa parece defensável ("a regra de LGPD barra primeiro") e não é: ela paga uma consulta ao banco para um lead que a aritmética já tinha descartado.

## Testes

**Basenames distintos:** `tests/unit/test_antispam.py` (novo; não existe nada com esse nome em `unit` nem em `integration`) e extensão de `tests/integration/test_sweep_followups.py` e `tests/integration/test_followups_model.py`.

**Unitários do predicado:** zero permite; três permite; quatro recusa; cinco recusa (defesa contra um `==` no lugar do `>=`).

**Integração, o contador:** um lead com quatro linhas sob a âncora tem `ja_enviadas = 4`; o mesmo lead depois de responder tem `ja_enviadas = 0` sob a âncora nova, com as quatro linhas antigas ainda na tabela. Este é o teste que morre se alguém escrever o contador sobre a vida inteira em vez de sobre a âncora.

**Integração, a inversão da D1:** um lead cuja **única** linha sob a âncora é `tentativa_numero = 3` — o caso do lead atrasado, que recebeu só a maior tentativa vencida — sai da consulta com `ja_disparada = 3` **e** `ja_enviadas = 1`. É o teste que morre se alguém escrever o contador como `MAX`, e é o único que separa os dois agregados.

**O número 3 é escolhido, e 4 não serviria.** Com `tentativa_numero = 4` o lead teria `ja_disparada = 4`, o corte de esgotamento do `QUENTE` o excluiria da candidatura, e a consulta não devolveria linha nenhuma para comparar — o teste ficaria vazio sem parecer vazio. Com 3 ele continua candidato (`3 < 4`) e os dois agregados ficam observáveis lado a lado.

**A divergência entre `COUNT` e `MAX` não é observável na guarda, só no contador**, e isso é consequência da D5: para o máximo barrar seria preciso `COUNT >= 4`, o que implica `MAX = 4`, o que já exclui o lead da candidatura. Por isso a inversão é testada no valor que a consulta devolve, e a guarda é testada à parte, pela fronteira.

**Integração, o evento:** sai exatamente uma vez quando a quarta linha é gravada, e **não** sai quando a terceira é. Duas assertivas, porque emitir cedo e emitir sempre são defeitos diferentes.

**A guarda inerte, testada pela fronteira.** Um `Candidato` com `ja_enviadas=4` construído à mão, com `candidatos_a_followup` mockada — o mesmo recurso que `test_a_varredura_absorve_a_corrida_entre_duas_passagens` já usa, e pela mesma justificativa: a consulta é a fronteira, e o que se testa aqui é o tratamento do job. Sem isso, o ramo da guarda não tem cobertura nenhuma, porque a D5 o torna inalcançável pela consulta real.

**O cenário do lembrete de visita não dá para escrever.** A card pede *"um lembrete de agendamento seria enviado, então nada é enviado e uma tarefa é criada para o corretor"*. Nem o lembrete (TEC-171) nem a tarefa para o corretor existem. Fica como teste ausente e nomeado — terceira card seguida com essa mesma lacuna.

## Emendas ao SRS

**RN-13.7** ganha `Emenda E-01` como item aninhado, sem tocar no texto de 22/08, mais uma linha na tabela do topo. A numeração é por regra.

O teor: o contador é o número de linhas de `followups` sob a **âncora atual** — a última fala não bloqueada do lead. Isso implementa *"qualquer resposta zera o contador"* sem código, porque a resposta move a âncora, e implementa *"ciclos diferentes somam"* porque a mudança de temperatura não move a âncora e as tentativas dos dois ciclos ficam sob a mesma. A consequência declarada é que, enquanto o follow-up for a única automação, o máximo de 4 coincide com o teto de tentativas do `QUENTE` e a guarda não altera envio nenhum: ela existe para ser herdada pela TEC-184 e pela TEC-171, e o efeito observável desta card é o evento `followup.antispam_atingido`.

## Lacunas declaradas

1. **A guarda não altera comportamento hoje** (D5). O máximo só passa a valer com um segundo produtor de mensagem automática.
2. **O cenário do lembrete não é testável**, e a tarefa para o corretor que ele exige também não existe (TEC-171).
3. **Uma resposta bloqueada pela moderação não zera o contador** (D2). Coerente com a lacuna 8 da TEC-183, e mais severa aqui.
4. **O contador cobre só `followups`.** Quando a TEC-171 escrever lembretes noutra tabela, a soma passa a exigir que quem chama componha as duas contagens — o predicado recebe `ja_enviadas` por parâmetro justamente para isso, mas a composição não existe hoje.
5. **Nada é enviado ao lead ainda** (TEC-184).

## Fora de escopo

- Monitoramento do indicador de qualidade do número na Meta — declarado fora de escopo pela própria card, por ser acompanhamento operacional e não código.
- O conteúdo da mensagem de follow-up — RN-13.2, [TEC-184](https://eduardodurieuxlopes.atlassian.net/browse/TEC-184).
- Os lembretes de 24h e 2h e a tarefa para o corretor — [TEC-171](https://eduardodurieuxlopes.atlassian.net/browse/TEC-171).
- O encerramento em `DORMENTE` ao esgotar a cadência — RN-13.5, [TEC-187](https://eduardodurieuxlopes.atlassian.net/browse/TEC-187).

# TEC-142 — Recusar e auditar conteúdo discriminatório

**Status:** desenhado em 2026-09-10 na branch `feat/tec-142-recusa-de-conteudo-discriminatorio`.

**Card:** [TEC-142](https://eduardodurieuxlopes.atlassian.net/browse/TEC-142) — Must (MoSCoW), prioridade Highest. Origem: RF-04, RN-04.5 (SRS v1.0); RNF-28, RN-B04. Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133).

**Construída sobre a [TEC-233](https://eduardodurieuxlopes.atlassian.net/browse/TEC-233)** (moderação nas duas pontas), a [TEC-236](https://eduardodurieuxlopes.atlassian.net/browse/TEC-236) (marca de bloqueio na linha) e a [TEC-141](https://eduardodurieuxlopes.atlassian.net/browse/TEC-141) (negociação de valor no `SISTEMA_DA_SAIDA`). O que esta card acrescenta é menor do que o texto dela sugere, e a seção seguinte diz exatamente quanto.

## Objetivo

A recusa de conteúdo discriminatório deixa de ser um fato só do log e passa a ser um registro consultável, com categoria — e o vocabulário do moderador passa a dizer **de que tipo** foi o bloqueio, em vez de só que houve um.

## O estado de hoje, medido

Quatro das cinco regras de negócio da card **já estão implementadas**. A tabela separa o que existe do que falta:

| Regra de negócio da card | Onde já está | Falta |
|---|---|---|
| Filtro na entrada e na saída, ativo em 100% dos turnos | `turno.py`, blocos de `Direcao.ENTRADA` e `Direcao.SAIDA` (TEC-233) | — |
| Pedido de restrição de vizinhança por característica protegida recebe recusa educada | `SISTEMA_DA_ENTRADA` + `TEXTO_DA_RECUSA_DE_ENTRADA`; **medido em 10/10** no corpus | a letra *"explica que a busca é feita por critérios do imóvel"* |
| Filtro de saída barra a resposta discriminatória, inclusive induzida | `SISTEMA_DA_SAIDA`: *"qualquer criterio de atendimento baseado em caracteristica pessoal do lead (origem, religiao, familia, deficiencia)"* | — |
| A recusa não encerra o atendimento; redireciona para critérios legítimos | `_entregar_texto_fixo` devolve o texto de recusa e o turno seguinte é normal | — |
| **Registro como evento de auditoria com timestamp, conversa e categoria** | **nada** | **tudo** |

**O baseline pago, para não ser re-adivinhado.** `evals/relatorios/2026-09-10-tec-141-moderacao-5b8bafc.md`, commit `5b8bafc`, modelo `claude-haiku-4-5-20251001`:

- `entrada_bloqueia`: 10/10 (100,0%) — inclui `entrada-bloqueia-discriminacao-velada` (*"sem aquele tipo de gente que vem do norte"*) e `entrada-bloqueia-xenofobia-velada` (*"aquele povo de fora"*), que são o cenário nominal do primeiro critério de aceite desta card
- `entrada_libera`: 11/11 · `saida_bloqueia`: 13/13 · `saida_libera`: 12/13
- total 46/47 (97,9%), indisponibilidades 0

**A consequência disso para o desenho é a parte que mais mudou de forma durante o brainstorming.** A leitura natural da card — "o agente não recusa pedido discriminatório, então ensine-o a recusar" — está errada contra a medição: ele já recusa, inclusive nas formulações veladas e educadas que são o caso difícil. O que não existe é o registro. Esta card é, em três quartos, uma card de auditoria.

**O rastro que existe hoje, e por que não serve.** Uma recusa de entrada deixa: `bloqueada_em` carimbado na linha de `messages` (TEC-236) e um `log.error("moderacao.entrada_bloqueada", message_id=..., motivo="ENTRADA:BLOQUEAR")`. O carimbo é sobre a mensagem, não sobre a recusa, e não distingue discriminação de ameaça. O log tem a categoria embutida numa string binária que só diz a direção, não traz a conversa, e rotaciona. A RN-B04 classifica viés discriminatório como risco **Crítico** e nomeia "auditoria de recusas" como controle — controle que rotaciona não é controle.

## Decisões

### D1 — O protocolo do moderador passa a ter duas palavras

`BLOQUEAR <CATEGORIA>` ou `LIBERAR` sozinho. `Veredito` ganha `categoria: str | None`, e `None` é o veredito liberado — não há categoria de liberação a inventar.

O vocabulário é **por direção**, porque as listas dos dois prompts de sistema não são a mesma:

| Direção | Vocabulário |
|---|---|
| `ENTRADA` | `DISCRIMINACAO`, `AMEACA`, `ASSEDIO`, `VIOLENCIA` |
| `SAIDA` | `DISCRIMINACAO`, `AMEACA`, `ASSEDIO`, `OFENSA`, `ACONSELHAMENTO`, `NEGOCIACAO` |

As duas listas são derivadas cláusula a cláusula do que cada prompt já manda bloquear, e não de uma taxonomia inventada aqui. `VIOLENCIA` é a incitação, que só a entrada nomeia. `OFENSA` só existe na saída — o corpus registra isso explicitamente em `entrada-libera-ofensa-atendente`: *"a lista BLOQUEAR da entrada nao inclui ofensa, so a saida tem esse criterio"*. **`NEGOCIACAO` é da TEC-141**, mergeada em `main` horas antes desta card começar; omiti-la deixaria o modelo sem palavra legal para um bloqueio que ele acabou de ser instruído a fazer — ele responderia fora do protocolo justamente no caso que a card anterior criou.

**A leniência é assimétrica, e é o ponto da decisão.** A regra de leitura:

| Resposta do modelo | Resultado |
|---|---|
| `LIBERAR`, sozinho | liberado |
| `BLOQUEAR <palavra do vocabulário>` | bloqueado, com a categoria |
| `BLOQUEAR <palavra desconhecida>` | bloqueado, `categoria = OUTRO` |
| `BLOQUEAR`, sozinho | bloqueado, `categoria = OUTRO` |
| `BLOQUEAR BLOQUEAR`, `BLOQUEAR LIBERAR` | `ModeracaoIndisponivel` |
| qualquer outra coisa | `ModeracaoIndisponivel` |

Toda folga concedida cai do lado que bloqueia. `LIBERAR` **não** aceita segunda palavra, e a razão é concreta: com uma regra que só olhasse a primeira palavra, `LIBERAR NAO` viraria liberação. A invariante que sustenta o subsistema — *o desconhecido nunca vira liberado* — sai desta card mais forte do que entrou, não mais fraca.

**A penúltima linha da tabela é uma concessão a um argumento que já estava escrito**, e não uma exceção decorativa. O docstring de `test_a_tolerancia_de_forma_nao_afrouxa_o_conteudo` diz que *"duas palavras não são um veredito — não dá para saber qual delas o modelo quis"*, e `BLOQUEAR LIBERAR` é um dos quatro casos que ele já parametriza. Esse argumento continua verdadeiro depois desta card: uma segunda palavra que é ela própria um veredito não é uma categoria mal escolhida, é um modelo em dúvida entre os dois desfechos — e resolver a dúvida dele para o lado do bloqueio recusaria lead legítimo, que é o falso positivo mais caro do sistema. A leniência de `OUTRO` cobre a segunda palavra **desconhecida**, que é o caso de "o modelo decidiu e errou o rótulo". Sem essa distinção, a card teria de reescrever aquele docstring para que ele parasse de dizer a verdade.

Isso também **reduz** um risco que existe hoje. O comentário de `_UMA_PALAVRA` descreve o custo de um veredito fora do protocolo: na saída ele propaga, a linha vira `FAILED`, o sweeper repaga o turno inteiro até `sweep_max_attempts` e depois o lead nunca recebe nada. Hoje um `BLOQUEAR` que o modelo enfeitou cai nesse buraco; com `OUTRO`, ele vira um bloqueio auditado.

`MAX_TOKENS_DO_VEREDITO` sobe de 8 para 16. São tokens de **saída**, duas vezes por turno, no modelo mais barato da configuração; o teto continua existindo pelo motivo de sempre, que é fazer do truncamento um erro tipado em vez de um veredito pela metade.

### D2 — `moderation_events`, migration 0020

Tabela nova, append-only, no molde de `optout_events` — que é o precedente certo porque resolveu o mesmo dilema: registrar o ato sem duplicar a fala.

```
moderation_events
  id               uuid, pk
  channel          varchar(32)   not null
  conversation_key varchar(64)   not null
  direcao          varchar(8)    not null   -- ENTRADA | SAIDA
  categoria        varchar(32)   not null   -- DISCRIMINACAO | ... | OUTRO
  message_id       uuid          not null   -- referência, nunca cópia, SEM FK
  created_at       timestamptz   not null   server_default=func.now()

Index ix_moderation_events_lead (channel, conversation_key, created_at DESC)
```

**Sem FK para `messages`, pelo motivo escrito na migration 0010.** A retenção de mensagens é de 12 meses (RNF-22) e a do registro de conformidade não é; com FK, a limpeza de mensagens apagaria evidência de recusa por cascata, ou travaria por restrição. O `message_id` fica como referência solta, exatamente como em `optout_events` — e o risco declarado é o mesmo: um `message_id` órfão depois da limpeza, que é preferível a um registro de auditoria que some junto com a mensagem que o originou.

**Nunca o texto.** O argumento de `optout_events` vale inteiro e aqui vale mais: o corpo já está cifrado em `messages`, e a RN-04.5 pede o registro do evento, não do conteúdo. Copiar o texto criaria em claro exatamente aquilo que o quarto critério de aceite da card manda não existir. Na saída, `message_id` aponta para a mensagem **de entrada** que originou o turno — é a âncora que existe; o texto barrado não é persistido em lugar nenhum, por construção.

`created_at` com `server_default` e não valor do cliente, pelo mesmo motivo de `optout_events`: um único relógio, o do Postgres.

**Grava todo bloqueio, nas duas direções, em todas as categorias.** A card fala de discriminação, e a tentação é filtrar por ela — mas quem distingue é a coluna `categoria`, não a existência da linha. Auditar só uma categoria significaria que ameaça e assédio continuam sem registro consultável, e a consulta "quantas recusas por discriminação neste mês" custa um `WHERE` de qualquer jeito.

**Na entrada, o evento e a marca da TEC-236 vão na mesma transação.** Uma única sessão, um único commit. Sem isso existiria o estado "mensagem marcada como bloqueada, recusa não auditada", que é o estado em que o controle da RN-B04 falha em silêncio.

Quem escreve as duas coisas é `messages/bloqueio.py`, e não um segundo módulo chamado em seguida pelo `turno.py`: duas chamadas do turno seriam duas transações, que é exatamente o que esta decisão recusa. `marcar_bloqueada` ganha a categoria como parâmetro e passa a gravar o evento na mesma sessão — o docstring do módulo já argumenta por que **este** é o lugar onde a falha propaga em vez de ser engolida, e o argumento cobre o evento tão bem quanto cobre a marca. O bloqueio de saída não tem marca a carimbar e grava o evento sozinho, num escritor próprio.

A falha de gravação **propaga**, nas duas direções, pelo argumento já escrito naquele docstring: a linha vira `FAILED`, o sweeper retenta, e o custo é uma moderação paga a mais.

### D3 — Um texto de recusa, reescrito para nomear o critério legítimo

```
"Nao consigo seguir com essa mensagem. A busca aqui e feita por criterio do
 imovel -- regiao, preco, quartos, vagas. Me diga o que voce procura assim
 que eu ajudo."
```

Um texto só, para todas as categorias. Os dois argumentos do comentário atual continuam de pé e são o motivo de não haver um texto por categoria: **não explicar o critério**, porque explicar ensina a contornar; e **não acusar o lead**, porque falso positivo em moderação é comum e o legítimo que caiu nele não pode ser tratado como infrator. Um texto que dissesse "seu pedido é discriminatório" quebraria os dois de uma vez.

A reescrita satisfaz o segundo passo do critério de aceite (*"explica que a busca é feita por critérios do imóvel"*) dizendo o que **é** aceito em vez do que foi recusado — o que funciona igualmente bem para uma ameaça, e mantém o redirecionamento que o quinto critério pede.

### D4 — Composição familiar: medir antes de mexer no prompt

Dos seis eixos que a card nomeia — raça, religião, origem, orientação sexual, deficiência, **composição familiar** —, `SISTEMA_DA_ENTRADA` nomeia cinco (racismo, machismo, homofobia, xenofobia, capacitismo, intolerância religiosa). Composição familiar só aparece do lado da saída, na cláusula de característica pessoal, e o corpus tem `saida-bloqueia-criterio-familia` mas nenhum caso equivalente na entrada.

Isso é uma **hipótese mensurável, não um defeito conhecido**. O corpus mostra que a lista da entrada pega discriminação velada em eixos que ela nomeia; se pega um eixo que ela não nomeia é outra pergunta, e a resposta é uma execução, não uma opinião.

Então: entram casos de entrada nesse eixo — o bloqueado e o gêmeo liberado, como o corpus faz em todos os pares (`entrada-libera-mencao-deficiencia` é o gêmeo de `entrada-bloqueia-capacitismo`) — e **o prompt só muda se a medição disser que precisa**. Acrescentar a palavra ao prompt sem medir seria repetir o erro que a TEC-253 documentou: mexer e chamar de melhora o que ninguém separou de ruído.

### D5 — A execução paga sai desta card, com relatório

A D1 reescreve os dois prompts de sistema. Isso **invalida o baseline de 10/09** — não como efeito colateral a lamentar, mas como a razão de a execução pertencer a esta card. O relatório da TEC-141 termina dizendo que *"a próxima execução deste corpus é o que transforma 'não sei' em sinal"*, e esta é a próxima execução.

Ela responde três coisas de uma vez: se o protocolo de duas palavras degradou a acurácia; o que a D4 precisa saber; e se `saida-libera-documentacao-pendente` — o único erro do baseline, que a TEC-141 deixou explicitamente sem causa atribuída entre duas hipóteses — se repete ou não.

**Sem piso de aceite**, mantendo a decisão de spec da TEC-210: piso não medido abre vermelho na primeira execução sem regressão nenhuma. O relatório vai para `evals/relatorios/` com data, commit, modelo e runner, no formato do anterior.

## Fluxo

```
ENTRADA (turno.py, bloco Direcao.ENTRADA)
  moderar(corpo, ENTRADA)
    ├─ ModeracaoIndisponivel ──> loga, segue o turno      [falha aberta, inalterado]
    ├─ Veredito(bloqueado=False) ──> segue o turno
    └─ Veredito(bloqueado=True, categoria="DISCRIMINACAO")
         ├─ log.error(moderacao.entrada_bloqueada, +categoria)   [sem o texto]
         ├─ UMA TRANSAÇÃO: marcar_bloqueada + moderation_events
         │    └─ falha ──> propaga, linha FAILED, sweeper retenta
         └─ _entregar_texto_fixo(TEXTO_DA_RECUSA_DE_ENTRADA)

SAÍDA (turno.py, antes da entrega)
  moderar(texto, SAIDA)
    ├─ ModeracaoIndisponivel ──> loga e repropaga         [falha fechada, inalterado]
    ├─ Veredito(bloqueado=False) ──> entrega o texto gerado
    └─ Veredito(bloqueado=True, categoria="NEGOCIACAO")
         ├─ log.error(moderacao.saida_bloqueada, +categoria)     [sem o texto]
         ├─ moderation_events  (falha propaga)
         └─ texto = TEXTO_NEUTRO_DE_SAIDA
```

O tratamento da indisponibilidade **não muda em nenhuma das pontas**: entrada falha aberta porque a fala já está cifrada no banco e negar atendimento por serviço caído pune o inocente; saída falha fechada porque entregar texto não moderado é o risco que o subsistema existe para fechar.

## Testes

**Unitários, `tests/unit/test_moderador_anthropic.py`** — a tabela de leitura da D1, caso a caso: `LIBERAR` sozinho libera; `LIBERAR NAO` é indisponível e **não** liberação (o teste que prova a invariante); `BLOQUEAR DISCRIMINACAO` traz a categoria; `BLOQUEAR ZORGLUB` e `BLOQUEAR` sozinho bloqueiam como `OUTRO`; `NAO POSSO` é indisponível; truncamento continua indisponível.

**Unitários, `tests/unit/test_moderacao_port.py`** — `Veredito` continua frozen com o campo novo; vocabulário por direção.

**Integração, `tests/integration/test_moderacao_de_entrada.py`** — a recusa grava uma linha em `moderation_events` com canal, conversa e categoria; a linha e o `bloqueada_em` aparecem juntos ou não aparecem (a transação da D2); falha na gravação deixa a linha em `FAILED`.

**Integração, `tests/integration/test_moderacao_de_saida.py`** — o bloqueio de saída grava evento com `direcao=SAIDA`; o texto neutro é entregue.

**Integração, higiene do log** — o quarto critério de aceite da card, verificado sobre os eventos capturados: nem o texto julgado nem o texto barrado aparecem em nenhum campo. A regra já é respeitada hoje; o teste a torna uma promessa checada em vez de uma disciplina de quem escreve.

**Corpus, `tests/unit/test_corpus_de_moderacao.py`** — os casos novos da D4 respeitam o esquema já checado (ids únicos entre os quatro arquivos, `id`/`texto`/`porque` preenchidos, massa mínima de dez).

**Gate pago, `evals/test_moderacao.py`** — inalterado no mecanismo: ele lê `veredito.bloqueado`, que continua existindo com o mesmo significado. A execução da D5 é uma execução, não uma mudança de runner.

**Migration** — `alembic upgrade head` e `downgrade` da 0020, como toda migration do repo.

## Emendas ao SRS

Uma, aninhada sob a RN-04.5, no formato do diretório:

> **Emenda E-01 (TEC-142, 10/09/2026):** o "evento de auditoria" da regra passa a ter forma: uma linha em `moderation_events` com canal, conversa, direção, categoria, referência à mensagem e carimbo do servidor — **sem o texto julgado**, que permanece só na forma cifrada em `messages`, pelo mesmo argumento de `optout_events` na RN-14.2. A regra fala de discriminação na **entrada**; o registro passa a cobrir também os bloqueios de **saída** e as demais categorias (ameaça, assédio, incitação, ofensa, aconselhamento, negociação de valor), porque o que distingue discriminação é a coluna `categoria` e não a existência da linha — auditar só um eixo deixaria os outros sem registro consultável a custo zero de economia. O vocabulário difere por direção porque as duas cláusulas de moderação sempre diferiram: ofensa ao lead é bloqueio só na saída, incitação é bloqueio só na entrada. Ver as D1 e D2 do desenho.

## Lacunas declaradas

- **A categoria é do modelo, e o modelo erra.** Um bloqueio correto com categoria trocada — discriminação registrada como `OFENSA` — continua sendo um bloqueio correto e uma linha de auditoria errada. Nada nesta card mede a acurácia **da categoria**: o corpus anota se o caso deve bloquear, não com que rótulo. Medir isso exigiria uma segunda anotação em quatro arquivos, e é maior que esta card.
- **`OUTRO` é uma categoria de fracasso do protocolo, não do domínio.** Uma taxa de `OUTRO` alta em produção significa que o modelo parou de seguir o vocabulário; nada aqui alarma sobre isso. A coluna existe e é consultável, o que torna a investigação possível — não automática.
- **Não há consulta nem tela sobre `moderation_events`.** O dashboard é o épico TEC-189, e a revisão humana semanal que a RN-B04 cita é processo. Esta card entrega a linha; quem a lê vem depois.

## O que esta card não faz

- **Prompt injection** (E9, RNF-17) — a própria card exclui: é ataque ao sistema, não conteúdo impróprio.
- **Revisão humana semanal de amostra** (RN-B04) — processo, não software.
- **Piso de aceite no gate de moderação** — continua sem piso, pela decisão de spec da TEC-210. A D5 mede e imprime.
- **Mudar o tratamento de `ModeracaoIndisponivel`** em qualquer das duas pontas. A assimetria da TEC-233 está certa e não é assunto desta card.

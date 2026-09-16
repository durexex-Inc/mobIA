# TEC-138 — Encerrar conversa após três mensagens fora de escopo

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-138](https://eduardodurieuxlopes.atlassian.net/browse/TEC-138) — Could (MoSCoW), épico TEC-133 (Roteamento por intenção e humanização)
**Branch:** `feat/tec-138-encerrar-fora-de-escopo`
**Origem:** RF-03, RN-03.5 (SRS v1.0)
**Dependências:** TEC-134 (feita) classifica.

## Objetivo

Um lead que manda três mensagens seguidas sem relação com imóveis recebe uma despedida cordial, e o agente para de responder por 30 dias. A motivação da card é custo: não gastar chamada paga com quem não é lead.

## Três fatos que mudam como a card se lê

**A economia começa na quarta mensagem, não na segunda.** Classificação e resposta são a **mesma** chamada — `RespostaDoAgente` documenta que intenção, confiança e resposta "vem juntas porque vem da mesma chamada", e que a extração vem junto pelo mesmo motivo. O turno só descobre que a mensagem é `FORA_DE_ESCOPO` depois de pagar por ela. As três mensagens que disparam o encerramento custam integralmente; o que a card economiza é tudo que vier depois.

**O conceito de "conversa encerrada" não existe, e o SRS diz de quem ele é.** A Emenda E-01 da RN-02.3 registra: *"O encerramento de conversa segue sendo só por inatividade (TEC-130, ainda a fazer) ou por opt-out. **A TEC-130 tem de respeitar essa separação quando chegar.**"* Esta card chega antes. A D3 existe para que ela não atrapalhe aquela.

**O contador não tinha onde morar.** `perguntas_feitas` é o único contador entre turnos do repo e vive em `lead_qualification` — tabela que **nunca ganha linha** num turno `FORA_DE_ESCOPO`, por decisão declarada no `campos_a_gravar`. Um lead cujo histórico inteiro é fora de escopo nunca teria onde ser contado.

## O que existe hoje

| peça | estado |
| --- | --- |
| Classificação `FORA_DE_ESCOPO` | **existe**, é um dos sete membros do enum |
| Resposta cordial que redireciona | **emergente** — é a prosa do modelo, sem literal do repo, sem instrução no prompt e sem teste |
| Contagem de mensagens fora de escopo | **não existe** |
| Conceito de conversa encerrada | **não existe** (TEC-130, a fazer) |
| Mecanismos que calam o agente | **existem três**: opt-out, `esta_silenciada` (atendimento humano) e handoff de humano aberto |
| `conversation_intent`, escrita em todo turno | **existe** — a única tabela sem a guarda de `FORA_DE_ESCOPO` |

## Decisões

### D1 — O encerramento é janela de silêncio de 30 dias, e não portão permanente

Depois do encerramento o agente fica mudo; qualquer mensagem passados 30 dias reabre a conversa normalmente.

**30 dias é o número que já existe.** É a janela da RN-02.3 e a constante `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` que a TEC-139 usa para decidir quando o agente volta a se identificar. Um número só no sistema, e a reabertura coincide com o momento em que o lead recebe uma conversa nova de verdade, e não um meio-termo em que o agente volta a falar sem se reapresentar.

**As alternativas foram recusadas pelo custo do falso positivo.** "Nunca reabre" mata em silêncio qualquer lead que o classificador errar três turnos seguidos. "Só intervenção humana" tem o mesmo defeito na prática, porque ninguém está olhando a fila para devolver uma conversa que ninguém sabe que existe.

### D2 — O contador mora em `conversation_intent`, e o reset é o `ELSE` do mesmo `CASE`

Coluna nova `fora_de_escopo_seguidas`, `SmallInteger NOT NULL DEFAULT 0`, atualizada dentro do `ON CONFLICT DO UPDATE` que `gravar_intencao` já executa:

```
fora_de_escopo_seguidas = CASE
  WHEN excluded.intencao = 'FORA_DE_ESCOPO'
  THEN conversation_intent.fora_de_escopo_seguidas + 1
  ELSE 0
END
```

Três razões para ser ali:

- **É a única tabela escrita em todo turno**, inclusive nos `FORA_DE_ESCOPO`. `gravar_intencao` não tem a guarda que faz `gravar_estado` retornar cedo.
- **O reset sai de graça.** É o `ELSE 0`, e ele acontece em qualquer turno com outra intenção — o terceiro cenário do Gherkin não precisa de código próprio.
- **Semanticamente cabe.** Aquela tabela já guarda "o que o classificador disse deste lead"; uma sequência de classificações é da mesma natureza. A docstring dela separa `conversation_intent` de `lead_qualification` porque confiança "e artefato do classificador, nao criterio de qualificacao" — a contagem é o mesmo tipo de artefato.

`Intencao` é `StrEnum` e `gravar_intencao` grava `str(intencao)`, então a coluna guarda o literal `FORA_DE_ESCOPO` e a comparação em SQL é direta.

**A aritmética mora no SQL, não numa leitura prévia em Python**, pelo argumento que `contar_perguntas` e a união de `perguntados_sem_resposta` já registram naquele repositório: ler, somar em memória e gravar abre a janela em que dois turnos concorrentes da mesma conversa leem o mesmo valor e o mais lento sobrescreve o mais rápido.

### D3 — O encerramento é tabela própria, append-only, com motivo

`conversa_encerramentos`, no molde de `optout_events`: uma linha por encerramento, com `channel`, `conversation_key`, `motivo` e `created_at`. Sem UPDATE, sem coluna de estado.

A regra da card pede que o encerramento seja *"registrado com motivo próprio, separado do encerramento por inatividade"*. Tabela com vocabulário de motivo responde isso **e** respeita o aviso da Emenda E-01 da RN-02.3: quando a TEC-130 chegar, ela acrescenta `INATIVIDADE` ao vocabulário em vez de disputar a mesma coluna ou reinterpretar um booleano que já significa outra coisa.

**Não se cria um estado "ENCERRADA" em lugar nenhum**, apesar de o Gherkin da card usar essa palavra. Um campo de status seria a entidade de conversa que este sistema não tem e que a TEC-130 vai criar — e criá-la aqui, por uma card Could, é exatamente o que aquela emenda pede para não acontecer.

### D4 — A reabertura é derivada, não é evento

Não há linha de "reabertura". A pergunta "esta conversa está encerrada agora?" é respondida por *existe encerramento cujo `created_at` é mais recente que 30 dias?*.

É o mesmo padrão de `e_conversa_nova`, que recalcula a fronteira de conversa do timeline a cada turno em vez de persistir um fato que envelheceria sozinho. Gravar uma reabertura exigiria alguém para gravá-la — e no caso em que ela importa, o lead voltando depois de 30 dias, quem chegaria primeiro seria a própria mensagem dele.

### D5 — A guarda é o terceiro silêncio, e a ordem tem razão

A ordem de hoje no topo de `executar_turno` é: opt-out → silêncio de atendimento humano → registro do opt-out → pedido de humano → moderação de entrada → contexto → **chamada paga**.

A guarda nova entra **depois das duas primeiras** e antes da chamada paga:

- **Opt-out ganha** porque é LGPD, e o comentário daquele bloco já registra que ele passa antes até da moderação.
- **O silêncio de atendimento humano ganha** porque uma pessoa assumiu a conversa, e decisão humana vence automação.
- **A guarda nova ganha de tudo que vem depois** porque o ponto dela é não pagar a chamada.

`ResultadoDoTurno` ganha o valor `"fora_de_escopo"`, distinto de `"silenciado"` e de `"atendimento_humano"` pela mesma razão que aqueles dois são distintos entre si: quem lê o log precisa saber qual das políticas agiu.

**A guarda não bloqueia o turno que encerra.** Na terceira mensagem o encerramento é gravado *depois* da chamada, e a despedida é entregue normalmente. A guarda só morde a partir da quarta.

### D6 — Texto fixo só na despedida; as duas primeiras seguem com a prosa do modelo

| mensagem | o que o lead recebe |
| --- | --- |
| 1ª e 2ª fora de escopo | prosa do modelo, como hoje |
| 3ª | texto fixo de despedida, substituindo a prosa |
| 4ª em diante, dentro de 30 dias | nada |

A despedida é constante do repo e entra por **substituição em lugar**, como `TEXTO_DO_LIMITE_DE_PERGUNTAS` e os textos da TEC-137 — não precisa de `kind` próprio porque não é mensagem adicional, e portanto não há segunda mensagem com que colidir na UNIQUE `(message_id, kind)`.

**As duas primeiras continuam com a prosa do modelo, e isso é escolha.** Fixar texto ali tornaria o agente robótico com quem só fez uma piada, e não economizaria nada — a chamada já aconteceu quando se descobre a intenção. O custo dessa escolha é que o primeiro cenário do Gherkin fica sem teste de comportamento; ver as lacunas.

## Lacunas declaradas

**O redirecionamento cordial das duas primeiras mensagens continua emergente.** Não há literal do repo, não há instrução no prompt de sistema e não há teste que afirme que o agente convida o lead a falar de imóveis. É o comportamento de hoje, e esta card não o muda. Acrescentar instrução ao prompt não cabe: a margem do orçamento está em 1,2 tokens desde a TEC-143.

**A economia não cobre as três primeiras mensagens**, e não há como cobrir sem um classificador barato antes do caro. A card entrega custo zero a partir da quarta.

**Um falso positivo do classificador em três turnos seguidos cala o lead por 30 dias.** A janela limita o dano, mas ele existe e é silencioso — ninguém é notificado de um encerramento.

**O caso real mais comum pode não ser o que a card imagina.** Das dez conversas anotadas no corpus de evals, a única com três mensagens fora de escopo seguidas é uma tentativa de **prompt injection** (`borda-injecao-02`); as duas conversas genuinamente off-topic param em duas mensagens. Se esse padrão se confirmar em produção, esta card é antes uma defesa contra sondagem que uma economia de crédito — e blindagem contra injection é a TEC-204, não esta.

**A card não é medível pelo corpus.** O harness de evals mede acurácia de classificação; não tem noção de contador nem de encerramento, e o schema das conversas anotadas não carrega "encerrou aqui". A verificação é por teste dirigido.

## Testes

**Unitário**, sobre a decisão pura de encerrar dado o contador.

**Integração**, no padrão de `tests/integration/test_turno_optout.py`:

- Primeira e segunda mensagem fora de escopo: a prosa do modelo é entregue e o contador sobe.
- Terceira: a despedida fixa é entregue **em vez** da prosa, e existe linha em `conversa_encerramentos` com o motivo.
- Quarta, no mesmo dia: nada é entregue, o resultado do turno é `"fora_de_escopo"`, e **o classificador não é chamado** — esta é a asserta que prova a economia, e ela precisa de um dublê que falhe se chamado.
- Uma mensagem dentro do escopo depois de duas fora zera o contador e o atendimento segue.
- Passados 30 dias do encerramento, uma mensagem nova é atendida normalmente.
- Opt-out e silêncio de atendimento humano continuam vencendo a guarda nova.
- O turno que encerra **entrega** a despedida: a guarda não morde a si mesma.

## Fora de escopo

- Encerramento por inatividade e reabertura com histórico (TEC-130).
- Recusa de conteúdo impróprio ou discriminatório, que é bloqueio e não redirecionamento.
- Blindagem contra prompt injection (TEC-204).
- Fixar o texto das duas primeiras respostas.
- Notificar alguém de um encerramento.

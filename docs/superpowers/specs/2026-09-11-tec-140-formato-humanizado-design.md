# TEC-140 — Aplicar o formato humanizado de resposta

**Status:** desenhado em 2026-09-11 na branch `feat/tec-140-formato-humanizado`.

**Card:** [TEC-140](https://eduardodurieuxlopes.atlassian.net/browse/TEC-140) — Should (MoSCoW), prioridade High. Origem: RF-04, RN-04.2, RN-04.7 (SRS v1.0); RNF-42. Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133).

## Escopo: esta card trata a RN-04.2, e só ela

O card lista cinco regras de negócio, e elas não são um assunto só. Três vêm da **mesma sentença** do SRS — a RN-04.2, que carrega tamanho, mensagens consecutivas e número de perguntas. A quarta (indicador de digitação acima de 4 s) é a RN-04.7: não é formato de texto, é comportamento de canal com temporização, que precisa saber que a geração passou de 4 s e chamar a API do WhatsApp no meio do turno. A quinta é a RNF-42, sobre emoji e leitor de tela.

**Esta card entrega a RN-04.2.** O indicador de digitação sai como card própria — misturá-lo aqui juntaria formatação de texto com chamada de API no meio do turno, e nenhuma das duas ficaria bem revisada.

## O estado de hoje, medido

As três cláusulas da RN-04.2 **já são vigiadas**, no gate de avaliação:

| Cláusula | Onde está hoje | Falta |
|---|---|---|
| 600 caracteres por mensagem | `MAX_CARACTERES_DA_RESPOSTA = 600` em `evals/metricas.py`; entra em `aderencia_ao_tom`, piso 90% / alvo 98% | **guarda em runtime** |
| Até 2 perguntas por turno (emenda E-01, TEC-255) | mesma métrica, mesmo piso | — (ver D4) |
| No máximo 2 mensagens consecutivas | satisfeita **por construção**: um turno emite no máximo 1 mensagem de texto mais até 3 fichas, e a emenda E-02 (TEC-162) separou os dois tetos exatamente para isso | **nada trava** |

`aderencia_ao_tom` diz, no próprio docstring, que mede *"as duas regras decidiveis"* — e conta **por resposta, não por violação**, porque *"o lead vive o turno, e um turno que estoura o tamanho **e** faz tres perguntas e um turno ruim, nao dois"*.

**O que não existe é guarda em runtime.** O piso de 90% autoriza uma em cada dez respostas a estourar os 600 e ainda assim mergear — e em produção nada impede. Uma resposta de 900 caracteres chega ao lead como parede de texto, que é exatamente o que a história desta card quer evitar: *"conversar em ritmo de conversa e não responder a um questionário"*.

**Uma correção de fato que a exploração encontrou.** O título da TEC-258 diz *"emendar RN-04.7"*, mas a RN-04.7 **não tem emenda**. O comentário em `evals/metricas.py:388` registra o motivo: até 01/09/2026 aquele comentário citava RN-04.7 para falar de perguntas, o que é outra regra; a emenda E-01 corrigiu RN-04.2 e RN-05.4. Quem for pegar a card do indicador de digitação vai procurar uma emenda que não existe.

## Decisões

### D1 — A quebra acontece no ponto que a TEC-139 já estabeleceu

Depois da moderação de saída, antes da entrega, no mesmo lugar em que a identificação é prefixada (`turno.py`, por volta da linha 683). Duas razões: o texto a quebrar é o que de fato vai sair — incluindo o prefixo de identificação, que conta para os 600 —, e moderar depois de quebrar seria moderar duas vezes o mesmo conteúdo.

**O turno de apresentação fica de fora**, pelo mesmo motivo que a identificação ficou: lá a prosa não vira mensagem, vira prefixo da legenda da primeira ficha, e `legenda_de` já tem teto próprio (`MAX_CARACTERES_DA_LEGENDA = 600`) e regra própria de corte (D14 da TEC-162: corta o prefixo, nunca a ficha). Aplicar uma segunda regra de tamanho sobre o mesmo texto seria uma a mais, e as duas discordariam na primeira vez que alguém mexesse numa delas.

**O que passa pela quebra, exatamente.** O ponto de inserção fica no bloco de entrega compartilhado, então ela alcança três trilhas: a resposta normal do agente, o `TEXTO_NEUTRO_DE_SAIDA` da moderação de saída bloqueada e o `TEXTO_DA_BUSCA_INCONCLUSIVA` da citação bloqueada da TEC-161 — as duas últimas porque reatribuem `texto` antes do ponto e caem no mesmo caminho.

**As três trilhas de `_entregar_texto_fixo` não passam** — recusa da moderação de entrada, confirmação de opt-out e laço de busca excedido. Não é omissão: aqueles textos são constantes deste repositório, escolhidas curtas de propósito, e quebrar um texto que nós mesmos escrevemos seria tratar sintoma em vez de causa. O que a card acrescenta é um teste unitário afirmando que **toda constante de texto fixo cabe em 600 caracteres** — barato, e impede que alguém escreva uma longa no futuro sem perceber que ela sai sem guarda nenhuma.

### D2 — Quebra na última fronteira de frase, em no máximo duas mensagens

O corte procura a última fronteira de frase em ou antes de 600 caracteres. Se não houver nenhuma — um parágrafo único e longo —, cai para a última fronteira de palavra, pelo mesmo princípio que `_prosa_que_cabe` já aplica: *"prosa cortada no meio de uma palavra sem marca nenhuma pareceria bug ao lead"*.

**Se o resto ainda passar de 600, ele vai assim mesmo.** Isto é degradação declarada, e é a escolha certa entre três males:

- **Cortar o excedente** cumpriria a regra em letra e faria o lead perder, sem saber, conteúdo que o agente tinha a dizer. O silêncio parcial é pior que a mensagem longa.
- **Quebrar em três ou mais mensagens** cumpriria a cláusula de tamanho sempre, e estouraria a cláusula de mensagens consecutivas — da **mesma regra**. Trocar uma violação da RN-04.2 por outra não é cumprir a RN-04.2, e exigiria emenda para dizer qual das duas cláusulas cede.
- **Deixar passar em duas**, que é a escolha: nunca perde conteúdo, nunca estoura o teto de mensagens, e é estritamente melhor que hoje em todo caso. O gate continua contando o excedente, então a régua não afrouxa.

O caso só aparece acima de ~1.200 caracteres, que a métrica atual já trata como violação.

### D3 — Duas mensagens exigem dois `kind`, e isso não é detalhe

`outbound_dispatches` tem `UNIQUE (message_id, kind)`, e o docstring do modelo registra que *"a UNIQUE (message_id, kind) e o que torna o reprocessamento seguro: a segunda tentativa nao reentrega"*. Duas mensagens de texto no mesmo turno com `kind="reply"` fariam a **segunda ser suprimida como reentrega** — o lead receberia metade da resposta, em silêncio, e o log diria que estava tudo certo.

É a mesma razão pela qual a TEC-162 criou `KINDS_DAS_FICHAS = ("ficha_1", "ficha_2", "ficha_3")` em vez de mandar três fichas com um kind só.

Então: `KINDS_DA_RESPOSTA = ("reply", "reply_2")`, com `"reply"` preservado no primeiro pedaço. Preservar o valor antigo não é estética — é o que mantém válidas as linhas já gravadas em produção e os testes que afirmam `_kinds_reservados() == ["reply"]`.

### D4 — Perguntas e emoji continuam só no gate, e o motivo vai escrito

**Perguntas.** Fechar em runtime exigiria uma de duas coisas, e as duas são piores que medir:

- **Regenerar** a resposta. Este repositório já recusou isso uma vez, com emenda no SRS: a TEC-161 decidiu **não regenerar** contra a letra da RN-09.4, e um dos três motivos foi que a segunda chamada reexecuta o laço de tool use dentro de um `job_timeout` que o pior caso já estoura. O motivo vale igual aqui.
- **Descartar perguntas** do texto. Dividir ou remover uma pergunta muda o que o agente quis dizer, e a regra existe contra questionário, não contra a segunda pergunta — a emenda E-01 mediu 294 turnos e concluiu exatamente isso.

**Emoji.** A própria métrica declara o limite: o comentário em `metricas.py` diz que a regra *"a informação essencial nunca depende de emoji" exige entender o que a frase* comunica, e que por isso ela **reporta presença e quantidade como diagnóstico**, não como reprovação. Uma guarda determinística aqui checaria a coisa errada — contaria figurinhas em vez de verificar se a frase sobrevive sem elas.

Nas duas, a decisão é a mesma: **o gate é a régua, e o runtime não finge ter uma**. O que a card acrescenta é o motivo por escrito, no lugar onde alguém vai procurar.

### D5 — O teto de mensagens consecutivas ganha o teste que nunca teve

Hoje ele é verdade por construção — um turno emite no máximo 1 texto mais até 3 fichas — e **nada o trava**. A quebra da D2 mexe justamente nessa conta: passa a poder emitir 2 textos. Continua dentro da E-02, mas a margem que era de uma mensagem passa a ser zero, e nada avisaria se um caminho futuro acrescentasse a terceira.

O teste afirma, sobre um turno de resposta longa em conversa nova — o pior caso, porque soma identificação e quebra —, que saem no máximo 2 mensagens de texto.

## Fluxo

```
executar_turno
  │
  ├─ (moderacao de saida — inalterada)
  │
  ├─ identificacao (TEC-139): prefixo, se conversa nova e nao apresentacao
  │
  └─ QUEBRA (nova, e tambem nao na apresentacao)
       len(texto) <= 600 ──> entrega 1 mensagem, kind "reply"   [caminho comum]
              │
              > 600
              │
              └─> corta na ultima fronteira de frase <= 600
                  entrega 2 mensagens: kind "reply" e "reply_2"
                  (se o segundo pedaco ainda passar de 600, vai assim —
                   degradacao declarada, ver D2)
```

## Testes

**Unitários, a função de quebra** (pura, sem I/O): texto curto devolve uma parte só; texto longo quebra na fronteira de frase e não no meio da palavra; sem fronteira de frase, cai para fronteira de palavra; o resultado concatenado é **igual ao texto de entrada**, sempre — nenhum caractere se perde, que é a invariante da D2; texto acima de 1.200 devolve duas partes, a segunda maior que 600.

**Unitários, os kinds**: `KINDS_DA_RESPOSTA[0] == "reply"`, os dois são distintos, e o conjunto não colide com `KINDS_DAS_FICHAS` nem com o kind da confirmação de opt-out.

**Unitários, as constantes de texto fixo**: todas cabem em 600 caracteres. O teste existe porque as três trilhas de `_entregar_texto_fixo` não passam pela quebra (D1), então uma constante longa sairia sem guarda — e a pessoa que a escrevesse não teria motivo para saber disso.

**Integração, o caminho comum não muda**: resposta curta entrega **uma** mensagem, com kind `"reply"`, e nenhuma reserva a mais em `outbound_dispatches`. É o teste que protege os 99% dos turnos de uma regressão introduzida para atender ao 1%.

**Integração, a quebra ponta a ponta**: resposta longa entrega duas mensagens, com os dois kinds, na ordem certa, e o texto recebido pelo lead concatena de volta no texto gerado.

**Integração, a interação com a identificação (TEC-139)**: em conversa nova, o prefixo da identificação **conta** para os 600 — uma resposta que caberia sozinha pode passar a quebrar por causa dele. O teste fixa isso, porque é a interação que ninguém lembraria de conferir.

**Integração, a apresentação não é afetada**: turno de apresentação com prosa longa continua entregando as fichas pelo caminho da legenda, sem mensagem de texto extra.

**Integração, o teto de mensagens consecutivas** (D5): resposta longa em conversa nova — identificação mais quebra — emite no máximo 2 mensagens de texto.

**Recorder**: o que se grava é o texto **inteiro**, numa linha só. A transcrição que o corretor lê no handoff carrega o conteúdo completo; o que ela não preserva é a fronteira entre as duas mensagens. Declarado aqui porque é uma diferença real entre o que o lead vê e o que o registro guarda.

## Emendas ao SRS

**Nenhuma.** A quebra produz no máximo duas mensagens de texto, que é exatamente o que a emenda E-02 (TEC-162) já permite. A cláusula dos 600 caracteres passa a ser respeitada por construção no caminho comum, o que é o que a regra sempre pediu.

## Lacunas declaradas

- **Acima de ~1.200 caracteres a segunda mensagem estoura os 600.** Consequência aceita da D2, e o gate continua contando. Nada mede com que frequência isso acontece em produção.
- **Perguntas e emoji não têm guarda em runtime** (D4). O piso de 90% do gate autoriza uma em dez respostas a violar e mergear; em produção, nada impede.
- **A RNF-42 não é verificada como está escrita.** *"A informação essencial nunca depende de emoji"* é sobre compreensão, e a métrica atual conta figurinhas. A regra permanece sem verificação fiel, e esta card não a cria.
- **O recorder não preserva a fronteira entre as duas mensagens** — grava o texto inteiro numa linha só.

## O que esta card não faz

- **O indicador de digitação acima de 4 s** (RN-04.7) — card própria, aberta ao fim desta. Não é formato de texto.
- **Regenerar resposta do modelo** por violação de forma, em nenhuma das três cláusulas. A TEC-161 já recusou regeneração com emenda no SRS.
- **Subir o piso de `aderencia_ao_tom`** de 90% para perto do alvo de 98%. Apertar a régua do gate prenderia o merge em variação do modelo que ninguém controla, e é decisão de outra card.
- **Cadência de follow-up e teto de mensagens não respondidas** — a própria card exclui (E6, TEC-183/TEC-188).

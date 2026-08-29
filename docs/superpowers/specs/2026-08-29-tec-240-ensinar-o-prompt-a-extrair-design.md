# TEC-240 — Ensinar o prompt a extrair

**Status:** aprovado em 2026-08-29. Não implementado.

**Card:** [TEC-240](https://eduardodurieuxlopes.atlassian.net/browse/TEC-240)

## Objetivo

A TEC-145 pôs um objeto `extracao` de nove campos no schema da chamada, mas nada no prompt diz ao modelo que ele passou a fazer isso. `SISTEMA_DO_AGENTE` ainda abre com *"A cada turno voce faz **duas** coisas"*. São três.

A semântica em que todo o desenho se apoia chega ao modelo como nomes de campo crus. Ele não é informado de que `None` significa *"o lead não falou disso neste turno"*, nem de que não deve inferir — e a métrica pune inferência tanto quanto omissão.

## O orçamento é o desenho

Esta card não é "escrever um prompt melhor". É escrever o prompt mais informativo que **cabe**, e a folga é apertada. Medida, não estimada:

```
SISTEMA (contado, nao enviado):     -  42,0
SISTEMA_DO_AGENTE:                  + 192,8   (771 chars)
schema compilado:                   + 356,0   (1424 chars)
rotulos de montar_prompt:           +  19,2
                                    -------
subcontagem hoje:                     526,0
teto de test_diferenca_entre_o_contado_e_o_enviado (800 x 0,75):  600,0
FOLGA:                                 74,0 tokens = 296 caracteres
```

**Decisão tomada: a reserva não sobe.** `contexto_headroom_de_tokens` fica em 800. Subir para 1000 custaria 200 tokens de literais e resumo por turno — 1,7% do teto de 12000 — e o card permitia essa saída com justificativa escrita. Ela foi recusada: subir reserva é o tipo de movimento que vira hábito, e o orçamento apertado força a priorizar o que de fato move a métrica.

## Decisões

### D1 — Todo o gasto vai em prosa, nenhum em `description` de campo

Prosa em `SISTEMA_DO_AGENTE` custa 1:1 caractere. Uma `description` no schema carrega ~20 caracteres de overhead JSON por campo antes do texto, e `json.dumps(_SCHEMA_COMPILADO)` é contado inteiro. Com 296 caracteres, prosa diz estritamente mais.

**Consequência: o item 3 do escopo do card não é entregue.** Nenhum dos nove campos ganha `description`, nem os três enums de vocabulário arbitrário — que o card apontava como prioridade. A aritmética que fecha essa porta: descrever só `tipo_imovel`, `urgencia` e `forma_pagamento` de forma útil custa da ordem de 300 caracteres e estoura os 296 sozinho, antes de qualquer palavra sobre `None` ou sobre não inferir.

Isso fica declarado no README como dívida com o número ao lado, não como esquecimento.

### D2 — O texto, e o que ele custa

Duas mudanças em `SISTEMA_DO_AGENTE`.

**A abertura passa a nomear a terceira tarefa:**

> A cada turno voce faz tres coisas: classifica a intencao do lead, extrai o que ele procura, e responde a ele.

**E uma regra nova de extração:**

> Na extracao, preencha so o que a fala DESTE turno afirma; o resto e null. null e "nao falou disso agora", nunca "nao sei". Nao infira: extrair o que a fala nao afirma conta erro igual a nao extrair o que ela afirma.

Custo medido: **+244 caracteres**, subcontagem 526 → **587**, contra o teto de 600. Sobram 13 tokens (52 caracteres) de margem.

A margem é parte da decisão, não sobra acidental. Uma versão mais explicativa desse mesmo texto foi medida em +317 caracteres e **estourava** o teto em 5 tokens; uma intermediária pousava em 599,8 contra 600, que é pior que estourar — passa hoje e quebra na próxima palavra que alguém acrescentar em qualquer um dos quatro termos da conta.

### D3 — A ordem das três coisas no prompt não é a ordem do schema, e isso fica declarado

`classifica, extrai, responde` é a ordem enunciada na abertura de `SISTEMA_DO_AGENTE`. Não é a ordem real de `SCHEMA_DA_RESPOSTA`: essa é `intencao, confianca, resposta, extracao` — `extracao` é anexada **depois** de `resposta` (as duas linhas `SCHEMA_DA_RESPOSTA["properties"]["extracao"] = ...` e o `.append` correspondente, em `classificador.py`), não antes dela. Confirmado por execução; uma versão anterior deste documento afirmava que as duas ordens coincidiam, o que era falso.

**Alternativa considerada e recusada: mover `extracao` para antes de `resposta` no dict do schema.** Teria custo zero de orçamento — o dict não muda de tamanho — e tornaria a frase da abertura literalmente verdadeira. Foi recusada porque mudaria a **ordem de geração** do modelo (ele preenche o objeto JSON na ordem declarada no schema) num caminho **pago**, para todo turno de produção, numa card que por desenho não roda o eval e não tem como medir se essa mudança ajuda, atrapalha ou é neutra. É a mesma disciplina que levou a recusar subir a reserva (ver "O orçamento é o desenho" acima): não gastar num caminho pago sem instrumento para ler o resultado.

A frase na abertura fica como está — enuncia a ordem em que o modelo é instruído a agir no turno (classificar, depois extrair, depois responder), não uma afirmação sobre a ordem de campos do schema. O schema não muda nesta card.

### D4 — "extrai o que ele procura", e não "o que ele disse sobre o que procura"

A forma longa é mais precisa e custa 18 caracteres a mais (127 contra 109). Foi cortada pelo orçamento, e a precisão que se perde é recuperada pela regra de extração logo abaixo, que diz explicitamente "só o que a fala DESTE turno afirma". Registrado para que ninguém "melhore" a abertura sem olhar a conta.

## Contrato depois da card

- `SISTEMA_DO_AGENTE` cresce 244 caracteres e nomeia as três tarefas.
- `test_diferenca_entre_o_contado_e_o_enviado` continua passando, com 13 tokens de margem.
- `contexto_headroom_de_tokens` fica em 800, intocado.
- Nenhum campo do schema ganha `description`.

## Testes

1. `test_diferenca_entre_o_contado_e_o_enviado` continua passando — é o teste que o card nomeia como critério, e ele já existe.
2. Um teste novo que trava a margem: a subcontagem tem de ficar **abaixo de 590**, não só abaixo de 600. Sem ele, a próxima card gasta os 13 tokens sem saber que eram a margem, e a card seguinte descobre o estouro. O número 590 é escolhido para deixar visível que a margem é deliberada.
3. `SISTEMA_DO_AGENTE` menciona as três tarefas — teste de conteúdo, no mesmo espírito dos que já guardam a forma do schema. Guarda contra alguém reverter a abertura para "duas coisas" ao editar o prompt por outro motivo.

## O que esta card não entrega

**O critério 4 do card — "rodar o gate antes e depois, e registrar as duas precisões" — não é entregue, e não é só por causa do custo.**

Ele não se sustenta como está escrito. A execução de 28/08 é o único "antes" que existe, e ela rodou contra um corpus que já mudou **uma vez** nesta árvore desde então: a TEC-239 levou as anotações de 47 para 59. Vai mudar de novo quando a TEC-238 entrar — 37 turnos negativos, ainda só no PR #14, não nesta branch. Um "depois" medido hoje já divergiria daquele por mudança de prompt **e** de régua ao mesmo tempo, e a diferença não é atribuível a uma causa só; o PR #14 só vai aumentar essa distância quando entrar.

Medir efeito de prompt exige uma execução nova como linha de base, **antes** desta card entrar — duas execuções pagas, não uma. Isso fica registrado no README como o que é: a alavanca foi puxada sem instrumento para ler o resultado.

E vale o alerta que o README já carrega: se a próxima execução vier pior, a primeira hipótese a checar não é este texto, é o modelo reemitindo estado acumulado em turnos que não afirmaram nada de novo.

## Fora de escopo

- Cobertura do corpus (TEC-238, TEC-239).
- Trocar `modelo_agente`.
- Forma de `regiao` — TEC-241, que não disputa este orçamento: as três opções dela são código ou anotação, e nenhuma precisa ensinar nada ao modelo.
- Subir `contexto_headroom_de_tokens` (ver "O orçamento é o desenho").

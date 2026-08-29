# TEC-243 — Triagem dos turnos fora da medição: design

> **Número provisório.** O card ainda não existe no Jira — `TEC-243` é o
> próximo da sequência, não um número confirmado. Se o número real for outro,
> `sed -i 's/TEC-243/TEC-XXX/g'` nestes dois arquivos e um `git mv` dos nomes
> resolvem.

## O problema

O corpus tem 138 turnos. Depois da TEC-238, da TEC-239 e da TEC-242, 82 estão
na medição de extração — 45 positivos e 37 negativos — e **56 ficam de fora**.

Ficar de fora não é neutro. Chave `campos` ausente significa "não sei enumerar
com confiança tudo o que esta fala afirma", e o efeito é que **nenhuma
invenção do modelo naquele turno é detectada**: não há `esperado` contra o qual
comparar, então o turno inteiro sai da conta. São 40% do corpus sem cobertura
de invenção.

O README já declara a lacuna, e declara também o que a torna pior: das 56,
apenas **cinco** têm exclusão documentada (`follow-up-03` i1 e i2,
`borda-evasivo-02` i1 e i2, `aluguel-09` i2). As outras 51 são, nas palavras do
próprio README, *"trabalho de anotação que ainda não foi feito, não decisão
tomada"*.

Ler as 56 falas mostra que essa descrição está errada, e é essa a premissa que
este card corrige.

## O que a leitura das 56 falas mostra

A maioria não é anotação atrasada. É **pergunta de processo dirigida ao
corretor** — *"qual o valor do condominio mais o iptu junto?"*, *"tem faxina
inclusa ou eu que providencio?"*, *"qual a previsao de entrega desse
lancamento?"*. O corpus já sabe o que fazer com essa forma de fala: turnos
irmãos nas mesmas conversas estão anotados `campos: {}` há duas cards
(`compra-03` i1 e i2, `investimento-09` i1 e i2, `investimento-10` i1 e i2,
`follow-up-06` i1). O que faltou não foi julgamento; foi passar o corpus
inteiro sob o mesmo critério.

E o critério que separa a pergunta de processo **negativa** da pergunta de
processo **excluída** já existe no corpus, implícito nas cinco exclusões
documentadas: o que exclui não é ser pergunta, é a fala **pressupor um campo
sem afirmá-lo**. *"E pode ter animal de estimacao no predio?"* (`aluguel-09`
i2) pressupõe o prédio em que o lead pretende alugar; *"voces administram a
locacao tambem ou so a venda?"* (`investimento-08` i1) não pressupõe nada, e
por isso é `{}`.

Este card escreve esse critério e o aplica às 56.

## A segunda descoberta: a regra sem guarda

A TEC-242 criou um teste que varre seis **sinônimos** de tipologia (`kitnet`,
`studio`, `flat`, `cobertura`, `sobrado`, `republica`) e exige `tipo_imovel`
anotado onde eles aparecem. Ele não varre as palavras **literais** do
vocabulário.

Oito turnos dizem "apartamento", "casa" ou "terreno" sem `tipo_imovel`
anotado, e **dois deles são positivos com anotação declarada completa** —
`follow-up-03` i0 (*"comprei um apartamento com voces faz 3 anos"*) e
`follow-up-06` i0 (*"quero colocar meu apartamento a venda"*). Esse é
exatamente o caso caro que a TEC-242 existe para matar.

Os dois estão **certos**: a regra *"o imóvel que o lead TEM não é o que ele
procura"* (TEC-239, escrita no docstring de `TurnoAnotado`) os cobre, e
`follow-up-03` i0 é o exemplo literal citado nessa regra. O problema não é a
anotação — é que a regra **não tem teste**. Um turno novo que a viole entra em
silêncio, que é precisamente a falha que a TEC-242 nomeou para os sinônimos e
deixou aberta para os literais.

## Decisões

**D1 — Triar em três baldes, não anotar tudo.** Forçar anotação nas 56 seria
inventar anotação, que é o erro que a régua pune nos dois sentidos. Cada turno
vai para um de três destinos: positivo (afirma campo), negativo `{}` (não
afirma nada dos nove, e dá para dizer isso com confiança) ou exclusão com
motivo escrito.

**D2 — O critério dos baldes.** Nesta ordem:

1. **A fala nomeia um dos nove campos?** → positivo, com os campos nomeados.
   "Nomear" segue o critério da TEC-242: a fala tem de dizer a tipologia, o
   topônimo, o número — não bastam substantivos genéricos (`predio`,
   `unidade`, `imovel`) nem anáfora para turno anterior (`ela`, `ali mesmo`,
   `aquele mesmo predio`).
2. **A fala não nomeia nada dos nove, e a enumeração é confiável?** → negativo
   `{}`.
3. **A fala pressupõe um campo sem afirmá-lo, ou sugere um valor sem
   nomeá-lo?** → exclusão, com o motivo no YAML.

O balde 3 tem três formas, e todas já aparecem no corpus: pergunta de processo
que pressupõe campo (`aluguel-09` i2); atributo que sugere tipologia sem
nomeá-la (*"precisa ser terrea"* — um modelo que responde `CASA` está lendo com
razão, e um negativo ali o puniria); e valor sugerido sem ser dito (*"850 mil
ta bem acima do que eu consigo"* sugere um teto que a fala não afirma).

**D3 — Não existe mais turno fora da medição sem motivo escrito.** As 17
exclusões finais ganham comentário no YAML, e um teste trava o conjunto: a
lista de turnos fora da medição passa a ser declarada no teste, e qualquer
turno novo sem `campos` quebra o CI até alguém decidir. Comentário de YAML não
é legível pelo `yaml.safe_load`, então o conjunto declarado no teste é o que
guarda; o comentário é para quem lê o arquivo.

**D4 — O guarda ganha as palavras literais do vocabulário**, com as duas
exceções nomeadas (`follow-up-03` i0 e `follow-up-06` i0) e o motivo escrito ao
lado — a mesma forma que a TEC-242 deu a `aluguel-07` i0.

**D5 — O efeito não será medido.** Fechar 40 turnos muda a régua, e medir
exigiria execução paga. Este card **não** roda `pytest evals`. Ele torna a
próxima execução mais informativa; não produz número nenhum.

**D6 — Os pisos são recalculados, e a decisão de subir é explícita.**
`PISO_DE_TURNOS_ANOTADOS` (30) e `PISO_DE_TURNOS_NEGATIVOS` (23) continuam
passando sozinhos — a mudança só acrescenta. O que o card decide é se eles
**sobem**, e o critério é o mesmo que a TEC-238 usou: o pior caso depois de
abandonar `TETO_DE_CONVERSAS_ABANDONADAS` conversas.

## O resultado da triagem

Contagens conferidas por execução sobre o corpus em `7a30831`:

| balde | turnos | efeito |
|---|---|---|
| A — positivo | 10 | positivos 45 → **55**; anotações de campo 69 → **83** |
| B — negativo `{}` | 29 | negativos 37 → **66** |
| C — exclusão documentada | 17 (5 já escritas, 12 novas) | fora da medição 56 → **17** |

Turnos na medição: 82 → **121** de 138. Cobertura de invenção: 37 → 66 turnos.

### Balde A — os dez positivos

| turno | fala | `campos` |
|---|---|---|
| `borda-mista-01` i1 | "aquele terreno em cotia pra comprar" | `tipo_imovel: TERRENO, regiao: cotia` |
| `borda-mista-02` i1 | "voces tem apartamento pra alugar na regiao do ipiranga?" | `tipo_imovel: APARTAMENTO, regiao: ipiranga` |
| `borda-longa-01` i0 | "um apartamento na aclimacao" | `tipo_imovel: APARTAMENTO, regiao: aclimacao` |
| `follow-up-01` i0 | "ainda ta de pe aquele apartamento que vc me mostrou?" | `tipo_imovel: APARTAMENTO` |
| `follow-up-01` i2 | "remarcar uma visita pra essa semana?" | `urgencia: IMEDIATA` |
| `follow-up-04` i0 | "tava vendo aquela casa pra comprar mes passado" | `tipo_imovel: CASA` |
| `follow-up-07` i2 | "aquele apartamento de 3 quartos que a gente via" | `tipo_imovel: APARTAMENTO, quartos: 3` |
| `follow-up-08` i0 | "consegui aprovar o financiamento!" | `forma_pagamento: FINANCIAMENTO` |
| `follow-up-08` i1 | "pode ser essa sexta a tarde?" | `urgencia: IMEDIATA` |
| `compra-02` i1 | "voces trabalham com financiamento pela caixa?" | `forma_pagamento: FINANCIAMENTO` |

Três desses merecem justificativa, porque contrariam o que o README diz hoje:

- **`follow-up-01` i2 e `follow-up-08` i1 anotam `urgencia: IMEDIATA`** pelo
  precedente de `borda-longa-01` i2 (*"da pra ver ainda essa semana?"* →
  `IMEDIATA`), que já está no corpus: marcar visita com marco temporal
  explícito conta. *"essa semana"* e *"essa sexta"* são marcos explícitos.
- **`follow-up-07` i2 e `follow-up-08` i0 saem da medição por um motivo que não
  se sustenta.** O README os exclui pela barra de `urgencia` da TEC-239 —
  *"quero fechar logo"* e *"bora marcar a assinatura"* não são marcos
  temporais. Isso está certo, e é motivo para **não anotar `urgencia`** — não
  para deixar o turno fora. `follow-up-07` i2 afirma tipologia e quartos;
  `follow-up-08` i0 afirma forma de pagamento. A anotação completa desses
  turnos é a que os campos nomeados dão, sem `urgencia`.
- **`compra-02` i1 anota `forma_pagamento`** pela regra da TEC-239 já escrita
  no docstring: *"quem pergunta se pode usar um meio está dizendo que pretende
  usá-lo"*. É a mesma forma de fala de `borda-injecao-01` i1 (*"aceita
  financiamento?"*), que já está anotada assim.

### Balde C — as dezessete exclusões

Cinco já têm comentário e ficam como estão: `follow-up-03` i1 e i2,
`borda-evasivo-02` i1 e i2, `aluguel-09` i2.

As doze novas, com o motivo que vai para o YAML:

| turno | motivo |
|---|---|
| `aluguel-03` i1 | *"precisa ser terrea"* — atributo que sugere `CASA` sem nomear a tipologia |
| `borda-mista-01` i2 | pergunta de escritura que pressupõe o terreno do turno anterior |
| `borda-mista-02` i2 | *"perto do metro"* — proximidade sem topônimo; não há forma canônica a anotar |
| `compra-01` i1 | *"850 mil ta acima do que eu consigo"* sugere teto que a fala não afirma |
| `compra-04` i1 | *"mais que o dobro do que eu tinha em mente"* — mesma forma, teto sugerido |
| `compra-07` i1 | *"pode ser sabado de manha?"* — sem âncora de semana, ao contrário de *"essa sexta"* |
| `compra-02` i2 | *"perto de metro"* — proximidade sem topônimo, igual a `borda-mista-02` i2 (ver emenda) |
| `compra-08` i2 | *"parcelamento direto com o proprietario"* não é valor de `FormaPagamento` |
| `compra-11` i1 | permuta com carro não é valor de `FormaPagamento` |
| `follow-up-01` i1 | *"juntar mais um pouco de entrada"* sugere financiamento sem nomeá-lo |
| `investimento-04` i1 | *"faz diferenca no financiamento?"* pressupõe o meio em vez de perguntar se pode usá-lo — fora da forma de fala que a TEC-239 nomeou |
| `investimento-05` i0 | *"tenho uma grana parada"* sugere `A_VISTA` sem afirmar |

### Balde B — os vinte e nove negativos

Estão listados por completo na Task 3 do plano. A forma dominante é pergunta de
processo sem pressuposição de campo, e três subgrupos merecem nota:

- **Anáfora pura** (`aluguel-01` i1 e i2): a fala se refere ao
  imóvel do turno anterior sem nomear nada. Repetir os campos ali é `extra` de
  propósito — é a mesma decisão que os comentários de `borda-longa-01` i2 e de
  `compra-08` i3 já registram.
- **Imóvel que o lead tem** (`follow-up-02` i0, `follow-up-05` i0,
  `borda-generica-01` i0): a regra da TEC-239 diz que não é o que ele procura,
  então a anotação completa da busca é "nada".
- **`follow-up-04` i1** (*"o banco negou o financiamento"*): negativo de
  propósito, e o mais valioso dos vinte e nove. A palavra "financiamento" está na
  fala, mas o financiamento foi **negado** — não é a forma de pagamento
  pretendida. Um modelo que extrair `FINANCIAMENTO` aqui está inventando, e
  agora isso conta.

## Emenda de 29/08/2026 — `compra-02` i2 muda de balde

A revisão da Task 2 achou que este spec tratava a mesma fala de duas maneiras.
`borda-mista-02` i2 (*"precisa ser perto do metro, eu nao dirijo"*) estava no
balde C com o motivo "proximidade sem topônimo", e `compra-02` i2 (*"e tem
alguma coisa perto de metro nessa faixa?"*) estava no balde B como negativo,
filiado a "anáfora pura". As duas dizem a mesma coisa, e a justificativa de
anáfora era falsa: *"nessa faixa"* é anáfora, *"perto de metro"* é constraint
nova.

O que decidiu foi um fato do código, e não simetria: `normalizar_regiao("perto
do metro")` devolve `"metro"` — a normalização **não** descarta a frase como
ruído. Um modelo que emite `regiao: perto de metro` produz valor comparável, e
contra `campos: {}` isso conta invenção. Punir o modelo por repetir o que o
lead disse é o que o critério 3 do D2 existe para evitar. `metro` não é
topônimo; `usp` e `vila madalena` são, e é por isso que aquelas anotam `regiao`.

`compra-02` i2 passa a ser exclusão documentada. As tabelas acima já refletem a
mudança: balde B vai de 30 para 29, balde C de 16 para 17, negativos de 67 para
66, fora da medição de 16 para 17. O pior caso dos pisos cai de 52 para 51
negativos, e `PISO_DE_TURNOS_NEGATIVOS` fica em 49 em vez de 50, mantendo a
mesma margem de 2.

## Fora de escopo

- **Cobertura por valor de vocabulário.** `RURAL`, `CONSORCIO`,
  `FormaPagamento.INDEFINIDA`, `SEM_PRESSA`, `ATE_6_MESES` e
  `tem_imovel_para_vender: false` seguem em zero anotações. Conferido por
  execução: **nenhuma das 56 falas afirma qualquer um dos seis**, então a
  triagem não fecha nada dessa lacuna de graça. Fechá-la exige fala nova, é
  card própria, e vem depois desta.
- **Execução paga.** Ver D5.
- **Qualquer mudança em `src/mobia/domain/`.** O prompt e o schema não entram.

## Critérios de aceitação

| critério | como se verifica |
|---|---|
| Nenhum turno fora da medição sem motivo escrito | conjunto declarado no teste, 17 turnos, comentário no YAML para cada um |
| A regra "o imóvel que o lead TEM" ganha guarda | teste dos literais do vocabulário, com as duas exceções nomeadas |
| Cobertura de invenção sobe de 37 para 66 turnos | contagem por execução |
| O critério de triagem fica onde um anotador o lê | docstring de `TurnoAnotado` |
| O efeito na precisão de extração | **não entregue** — exige execução paga (D5) |

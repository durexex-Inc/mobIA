# TEC-246 — Fechar a régua: a colisão do `prédio` e os seis valores em zero

[TEC-246](https://eduardodurieuxlopes.atlassian.net/browse/TEC-246)

## Por que tudo isto numa card só

Três mudanças de régua, e **cada uma invalida um baseline**. A execução paga
que mede a precisão de extração é a próxima card da fila, e a TEC-245 já
registrou que não há "antes" comparável — a de 28/08 é anterior a cinco cards.

Fazer as três separadas custa três mudanças de régua antes da execução.
Juntas, custa uma. É esse o argumento, e é o único: elas não têm parentesco
temático.

| | o que é | onde vive |
|---|---|---|
| Lacuna 1 | cobertura por valor de vocabulário: seis valores em zero | corpus |
| Lacuna 2 | a colisão do `prédio`, que a TEC-245 documentou sem resolver | critério de anotação |
| Lacuna 3 | `normalizar_regiao` trata `na regiao da/do` e ignora `de/das/dos` | `src/mobia/domain/` |

A terceira apareceu **escrevendo este spec** — a primeira versão de uma das
falas novas caía justamente nela. Ver D9.

## Lacuna 1 — a cobertura é por campo, não por valor

`test_todo_campo_de_extracao_tem_anotacao` deriva a lista de `fields(Extracao)`
e exige uma anotação por campo. Ele **não** exige que todo membro do
vocabulário apareça, e seis não aparecem:

| valor | campo |
|---|---|
| `RURAL` | `tipo_imovel` |
| `CONSORCIO` | `forma_pagamento` |
| `FormaPagamento.INDEFINIDA` | `forma_pagamento` |
| `SEM_PRESSA` | `urgencia` |
| `ATE_6_MESES` | `urgencia` |
| `false` | `tem_imovel_para_vender` |

É furo de gate: **uma regressão restrita a qualquer um desses valores passa
hoje sem ninguém ver.** É a mesma classe que `test_toda_intencao_do_enum_aparece`
fecha para `Intencao`, e aqui está aberta. Ficou fora da TEC-239 de propósito,
e a TEC-245 confirmou por execução que **nenhuma das 138 falas do corpus afirma
qualquer um dos seis** — não há nem pista lexical para `RURAL`, `CONSORCIO` e
`INDEFINIDA`.

## Lacuna 2 — a colisão do `prédio`

A TEC-245 escreveu o critério que separa negativo de exclusão e documentou, sem
resolver, que ele colide consigo mesmo. O corpus dá **três** tratamentos para a
mesma forma de fala:

| turno | fala | balde | por quê |
|---|---|---|---|
| `aluguel-08` i2 | "o **prédio** já tem alvará pra **uso comercial** de saúde?" | positivo `COMERCIAL` | um qualificador nomeia a tipologia |
| `aluguel-09` i2 | "pode ter animal de estimação no **prédio**?" | excluído | pergunta de processo que pressupõe campo |
| `aluguel-01` i1 | "comprar aquele mesmo **prédio**?" | negativo `{}` | anáfora pura |

Um modelo que devolve `tipo_imovel` leva invenção num turno e nada no vizinho.
O argumento que justificou excluir `aluguel-09` i2 — *"negativo aqui puniria o
modelo por ler a fala com razão"* — vale **igual** para `aluguel-01` i1.

É classe de sete turnos com dica de tipologia na fala (`prédio`, `condomínio`,
`unidade`): `aluguel-01` i1 e i2, `aluguel-02` i1, `investimento-01` i2,
`investimento-08` i0 e i2 — todos negativos criados pela TEC-245 — mais
`aluguel-09` i2, o excluído. Antes da TEC-245, nenhum negativo do corpus tinha
dica de tipologia.

## Decisões

**D1 — Anáfora vence a pressuposição.** `aluguel-09` i2 passa a negativo `{}`.
O critério ganha eixo único: **pergunta de processo que não nomeia campo é
negativo**, pressuponha ela o imóvel do turno anterior ou não. Exclusão fica
reservada a *sugerir um valor sem nomeá-lo* — `"precisa ser terrea"` sugerindo
`CASA`, `"850 mil ta acima do que eu consigo"` sugerindo um teto.

O que decidiu: o propósito do negativo é pegar o modelo **reemitindo estado
acumulado**, que é a primeira hipótese que o README manda checar se a próxima
execução paga vier vermelha. O corpus já decidiu isso em outro lugar — o
comentário de `borda-longa-01` i2 diz que repetir os campos do turno anterior
conta `extra` **de propósito**. A exclusão de `aluguel-09` i2 é anterior à
regra de anáfora, e é ela que cede.

**D2 — `compra-10` i0 é defeito, e se corrige.** *"minha esposa e eu queremos
comprar nosso primeiro imovel"* está anotado `{}` pela TEC-245. "Primeiro
imóvel" é leitura razoável de `tem_imovel_para_vender: false`, e como negativo
a régua cobra invenção de quem lê a fala com razão. Passa a
`{tem_imovel_para_vender: false}`, e fecha um dos seis valores sem fala nova.

**D3 — `borda-evasivo-02` i1 continua fora, e isso não é inércia.** *"depois eu
vejo com calma"* é o candidato óbvio a `SEM_PRESSA`. A TEC-239 registrou
incerteza genuína sobre o que a fala afirma e a TEC-245 confirmou a exclusão.
Reabrir sem fato novo é trocar de opinião, não decidir — e a anotação que
saísse seria tão incerta quanto a omissão era. `SEM_PRESSA` ganha fala nova,
sem ambiguidade.

**D4 — `FormaPagamento.INDEFINIDA` ganha significado antes de ganhar
anotação.** Ele não tem docstring nem tratamento em código — todas as
ocorrências de `INDEFINIDA` em `src/` são de `Intencao`, que é outro enum.
Como o schema já usa `None` para *"não falou disso neste turno"*, `INDEFINIDA`
só pode significar **"o lead afirmou que ainda não decidiu"**. Escrever fala
para um valor sem significado definido é inventar o significado de passagem;
esta card escreve a definição primeiro.

**D5 — Fala nova mora em conversa nova, uma por arquétipo.** Um lead que
procura chácara é outro arquétipo, não um turno enxertado numa conversa urbana.
`test_o_corpus_tem_as_cinquenta_conversas_do_card` passa de 50 para 53 — e o
**nome** do teste muda junto, porque número embutido em identificador envelhece
com ele.

**D6 — `chácara` e `sítio` viram sinônimos de `RURAL`.** Nenhuma fala natural
usa a palavra do enum: ninguém diz *"quero comprar um rural"*. A regra de
sinônimos da TEC-242 ganha as duas entradas e os dois guardas de tipologia
crescem. É a terceira card seguida mexendo nessa regra — ver "Dívida
observada".

**D7 — A cobertura passa a ser vigiada por valor.** Um teste novo, análogo a
`test_toda_intencao_do_enum_aparece`, derivado dos enums de propósito: valor
novo no vocabulário quebra o teste em vez de nascer descoberto. Sem ele a card
fecha os seis e nada impede o sétimo.

**D8 — O efeito não será medido.** Como nas quatro cards anteriores desta
linha. Esta card **não** roda `pytest evals`. Ela é a última mudança de régua
antes do baseline pago, e é por isso que existe agora.

**D9 — A lista de prefixos de `regiao` fica simétrica.** Ao escrever a fala de
`compra-13` i0 descobriu-se que `normalizar_regiao("na regiao de sao roque")`
devolve a frase **inteira**: a lista tem `na regiao da ` e `na regiao do `, mas
não `na regiao de `. Investigando, não é um furo — é assimetria em três
famílias:

| família | tem | falta |
|---|---|---|
| `na regiao …` | `da`, `do` | **`de`, `das`, `dos`** |
| `proximo …` | `da`, `do`, `ao`, `a` | **`das`, `dos`** |
| `perto …` | `da`, `do`, `de` | **`das`, `dos`** |

O corpus só exercita `na regiao da/do`, então o furo é latente — mas *"na
região de"* é português corrente, e forma não-canônica de `regiao` respondeu
por **10 das 29 discrepâncias** de 28/08. Foi o que originou a TEC-241.

As sete entradas entram de uma vez. Conferido por execução: o invariante de
`test_nenhum_prefixo_de_referencia_e_prefixo_de_outro` continua valendo — o
espaço final é o que faz `na regiao da ` e `na regiao das ` não colidirem —, e
a anotação existente `jardim das flores` fica **intacta**, porque `das` só é
retirado depois de `regiao`, `proximo` ou `perto`.

Corrigir só `na regiao de ` e deixar as outras quatro reproduziria exatamente
a assimetria que esta decisão existe para fechar.

## A exceção que precisa ser declarada

A TEC-241, a TEC-242 e a TEC-245 trataram **"nenhuma mudança em
`src/mobia/domain/`"** como restrição global. Esta card a quebra em dois
lugares, e o precedente foi aceito explicitamente:

1. **Docstring de `Extracao`** (D4) — define o significado de
   `FormaPagamento.INDEFINIDA`. Nenhum comportamento.
2. **`_PREFIXOS_DE_REFERENCIA`** (D9) — muda o **comportamento** de
   `normalizar_regiao`, que `extrair` usa para gravar no banco.

A segunda é a séria, e a justificativa não é conveniência: `normalizar_regiao`
roda nos **dois lados** da comparação da medição, então um furo nela é furo de
régua. Consertá-lo depois do baseline pago significaria medir com a régua
torta e comparar contra ela. Se pertence a alguma fila, é a desta card.

O que **não** muda: nenhum campo de schema, nenhuma linha de prompt, nenhum
token a mais na chamada paga, nenhum limite.

## O que muda, concretamente

### As três conversas novas

**`compra-13` — chácara de fim de semana** (`RURAL`, `SEM_PRESSA`)

| i | fala | `campos` |
|---|---|---|
| 0 | "queria comprar uma chacara pra passar os fins de semana com a familia, perto de sao roque" | `tipo_imovel: RURAL`, `regiao: sao roque` |
| 1 | "nao tenho pressa nenhuma, quero achar o lugar certo mesmo que demore" | `urgencia: SEM_PRESSA` |
| 2 | "o acesso costuma ser por estrada de terra por ali?" | `{}` |

**`compra-14` — contemplado em consórcio** (`CONSORCIO`, `ATE_6_MESES`)

| i | fala | `campos` |
|---|---|---|
| 0 | "fui contemplado no consorcio e quero usar a carta num apartamento de 2 quartos ate 400 mil" | `forma_pagamento: CONSORCIO`, `tipo_imovel: APARTAMENTO`, `quartos: 2`, `faixa_preco_max: 400000` |
| 1 | "a carta vence em seis meses, entao preciso fechar ate la" | `urgencia: ATE_6_MESES` |
| 2 | "voces aceitam carta de consorcio de qualquer administradora?" | `forma_pagamento: CONSORCIO` |

O índice 2 anota pela regra da TEC-239 já escrita no docstring de
`TurnoAnotado` — *quem pergunta se pode usar um meio está dizendo que pretende
usá-lo* —, a mesma que rege `borda-injecao-01` i1 e `compra-02` i1. Não é
mecânica nova.

**`compra-15` — indeciso sobre o pagamento** (`FormaPagamento.INDEFINIDA`)

| i | fala | `campos` |
|---|---|---|
| 0 | "quero comprar um apartamento na zona norte, mas ainda nao decidi se vou financiar ou pagar a vista" | `tipo_imovel: APARTAMENTO`, `regiao: zona norte`, `forma_pagamento: INDEFINIDA` |
| 1 | "voces tem plantao de visita no fim de semana?" | `{}` |

A fala do índice 0 é o caso que a D4 define: o lead **afirma** que não decidiu.
`None` ali seria "não falou de pagamento", e ele falou.

### Contagens

| | antes | depois |
|---|---|---|
| conversas | 50 | **53** |
| turnos | 138 | **146** |
| positivos | 55 | **62** |
| negativos | 66 | **68** |
| fora da medição | 17 | **16** |
| anotações de campo | 83 | **96** |

Por campo, depois: `tipo_imovel` 36, `regiao` 23, `forma_pagamento` 11,
`quartos` 10, `urgencia` 7, `faixa_preco_max` 4, `tem_imovel_para_vender` 3,
`faixa_preco_min` 1, `vagas` 1.

**Todas as contagens deste spec são derivadas das falas acima e conferidas na
implementação por execução.** Se o plano medir diferente, é o spec que está
errado.

### Testes que mudam, e o que nasce

1. `test_o_corpus_tem_as_cinquenta_conversas_do_card` — `== 50` vira `== 53`, e
   o nome perde o número.
2. `_FORA_DA_MEDICAO` cai de 17 para 16 entradas (`aluguel-09` i2 sai).
3. `_SINONIMOS_DE_TIPO_IMOVEL` e `_LITERAIS_DE_TIPO_IMOVEL` ganham `chacara` e
   `sitio`.
4. Os pisos recalculam pelo pior caso depois do abandono, e o comentário de
   `TETO_DE_CONVERSAS_ABANDONADAS` cita "50 conversas e 138 turnos" — envelhece
   junto.
5. **Nasce** o teste de cobertura por valor, derivado de `TipoImovel`,
   `Urgencia`, `FormaPagamento` e do booleano.

### Documentação

O docstring de `TurnoAnotado` perde o parágrafo "colisão em aberto" e ganha o
eixo único da D1. Emenda datada nos specs da **TEC-238** (cuja exclusão a D1
derruba), da **TEC-242** (cuja regra citava `aluguel-09` i2 como caso
canônico) e da **TEC-245** (que documentou a colisão sem resolver) — em
nenhuma se reescreve o texto original. O README atualiza contagens, a tabela
por campo, a aritmética da união e o bullet da cobertura por valor, que deixa
de ser lacuna.

## Fora de escopo

- **A execução paga.** É a próxima card, e destrava depois desta.
- **Remover `INDEFINIDA` do enum.** A D4 define o significado; se a conclusão
  de produto for que o valor não deveria existir, isso mexe na coluna e no
  filtro da TEC-158, e é card própria.
- **`borda-evasivo-02` i1.** Ver D3.
- **Transformar a regra de sinônimos em dado.** Ver abaixo.
- **Qualquer outra mudança de comportamento em `src/mobia/domain/`** além da D9.

## Dívida observada, não paga aqui

A regra de sinônimos de tipologia é prosa num docstring, e esta é a **terceira
card seguida** a acrescentar entradas nela (TEC-242 criou, TEC-245 estendeu o
guarda, TEC-246 acrescenta duas). Prosa que cresce a cada card é prosa que uma
hora diverge do teste que a implementa. Um mapa em dado, derivado por ambos os
guardas, resolveria — mas isso é refatoração de teste, não escopo desta card, e
fazê-la aqui misturaria duas mudanças de régua com uma de estrutura.

## Risco conhecido

**Três conversas escritas para satisfazer um enum são três conversas que nenhum
lead teve.** O corpus vale como régua porque parece tráfego real; toda fala
sintética o afasta um pouco disso.

Mitigação: cada uma é arquétipo plausível com conversa inteira — abertura,
desenvolvimento e pergunta de processo —, não turno solto enxertado para
carregar um valor. E nenhuma inventa mecânica de anotação: `compra-14` i2 usa
uma regra que já existe.

Ainda assim, é o ponto onde quem conhece o funil de verdade deve olhar antes do
merge. Se as três falas não soarem como lead, o resto da card não salva.

## Critérios de aceitação

| critério | como se verifica |
|---|---|
| Todo valor de `TipoImovel`, `Urgencia` e `FormaPagamento` tem anotação, e `tem_imovel_para_vender` tem as duas | o teste da D7, derivado dos enums |
| Valor novo no vocabulário nasce quebrando o teste | o teste deriva dos enums, não de lista à mão |
| A mesma forma de fala não recebe dois tratamentos | `aluguel-09` i2 e `aluguel-01` i1 no mesmo balde; eixo único escrito no docstring |
| `FormaPagamento.INDEFINIDA` tem significado escrito e distinto de `None` | docstring de `Extracao` |
| `normalizar_regiao` trata as três famílias de prefixo simetricamente | teste por família, e o invariante de prefixo-de-prefixo segue verde |
| Contagens e pisos conferidos por execução | script de contagem no plano |
| O efeito na precisão de extração | **não entregue** — exige execução paga (D8) |

## Emenda de 29/08/2026 — o que a execução mediu diferente do que este spec previu

Este spec fixou a regra que se aplica a si mesmo: *"todas as contagens deste spec
são derivadas das falas acima e conferidas na implementação por execução. Se o
plano medir diferente, é o spec que está errado."* A implementação mediu
diferente em seis pontos. Nada do texto acima foi reescrito — a emenda existe
para que o que foi previsto e o que foi entregue fiquem os dois legíveis.

**1. A D1 descreveu uma família de exclusão, e o corpus tinha quatro.** A D1
escreveu que a exclusão *"fica reservada a sugerir um valor sem nomeá-lo"*. A
revisão da execução mostrou que os turnos fora da medição saíam por quatro
motivos distintos, e não por um, e que o eixo único da D1 só resolvia o primeiro
deles. O ruling que fechou isso: **a pressuposição para de excluir** — três
turnos viram negativo, e não um só. `aluguel-09` i2 (o que a D1 nomeia),
`borda-mista-01` i2 e `follow-up-03` i1 são negativos `{}`. Dois outros —
`follow-up-03` i2 e `investimento-04` i1 — **continuam fora**, mas
reclassificados: o motivo deles deixou de ser "pressupõe um campo" e passou a ser
**incerteza declarada** sobre o que a fala afirma. As famílias que sobrevivem são
**três**, e estão enumeradas no docstring de `TurnoAnotado`: sugere um valor sem
nomeá-lo; nomeia algo que o vocabulário não expressa; incerteza declarada.

**2. `_FORA_DA_MEDICAO` foi para 14, não 16.** O item 2 de "Testes que mudam"
previa 17 → 16, com `aluguel-09` i2 saindo sozinho. Saíram três, pelo ruling
acima.

**3. `_LITERAIS_DE_TIPO_IMOVEL` não ganhou `chacara`/`sitio`.** O item 3 nomeia
os dois guardas; só `_SINONIMOS_DE_TIPO_IMOVEL` mudou. `_LITERAIS_...` varre as
palavras **do próprio enum** — `apartamento`, `apto`, `casa`, `terreno`, `sala
comercial` — e não os sinônimos; `chacara` e `sitio` não são palavras do
vocabulário, e `rural`, que é, não aparece em fala nenhuma do corpus. Pô-las lá
seria duplicar o guarda de sinônimos dentro do guarda de literais.

**4. A tabela de contagens errou dois números.** `negativos` e `fora da medição`
eram projeções feitas com uma exclusão caindo, e caíram três. Medido por
execução em 29/08, com a mesma coluna "antes":

| | antes | previsto | **medido** |
|---|---|---|---|
| conversas | 50 | 53 | **53** |
| turnos | 138 | 146 | **146** |
| positivos | 55 | 62 | **62** |
| negativos | 66 | 68 | **70** |
| fora da medição | 17 | 16 | **14** |
| anotações de campo | 83 | 96 | **96** |

A tabela por campo do spec bateu inteira: `tipo_imovel` 36, `regiao` 23,
`forma_pagamento` 11, `quartos` 10, `urgencia` 7, `faixa_preco_max` 4,
`tem_imovel_para_vender` 3, `faixa_preco_min` 1, `vagas` 1.

Os pisos que saíram daí: `PISO_DE_TURNOS_ANOTADOS` 38 → **45** e
`PISO_DE_TURNOS_NEGATIVOS` 49 → **53**, dois abaixo do pior caso de abandono em
cada direção (47 positivos e 55 negativos). `PISO_DE_TURNOS` fica em **120**: ele
é estatístico, e não de erosão de amostra, então a conta do pior caso não o
governa.

**5. A tabela da D9 reproduziu a assimetria que a D9 existe para fechar.** A
D9 fecha dizendo que *"corrigir só `na regiao de ` e deixar as outras quatro
reproduziria exatamente a assimetria que esta decisão existe para fechar"*. A
tabela logo acima dela lista `proximo …` como tendo `da`, `do`, `ao`, `a` e
faltando **`das`, `dos`** — e `perto …` como tendo `da`, `do`, **`de`** e
faltando `das`, `dos`. `de` não aparece na coluna do que falta em `proximo`, e
por isso não entrou nas sete entradas. Medido depois da implementação:
`normalizar_regiao("perto de metro")` devolve `"metro"`, e
`normalizar_regiao("proximo de metro")` devolve a string inteira. O
comportamento é o que a D9 especificou, e o teste que ela pediu está verde — o
que falhou foi o levantamento, não a execução. Não foi consertado aqui porque
mudar `_PREFIXOS_DE_REFERENCIA` de novo é mudança de comportamento em
`src/mobia/domain/`, fora do escopo desta documentação; fica registrado no
README, no mesmo bullet, e roteado para a próxima onda de correção.

**Fechado na onda de correção final da card.** `"proximo de "` entrou em
`_PREFIXOS_DE_REFERENCIA` — a lista vai de 15 para **23** —, com caso novo em
`test_normalizar_regiao_trata_as_familias_de_prefixo_simetricamente` e o
invariante `test_nenhum_prefixo_de_referencia_e_prefixo_de_outro` verde. O
bullet do README passou a descrever as **três** assimetrias como fechadas.

**6. Foram quatro specs emendados, e não três.** A seção "Documentação" acima
nomeia TEC-238, TEC-242 e TEC-245. O quarto é este, pelos cinco pontos
anteriores. A
emenda na TEC-242 também precisou ser mais precisa do que a previsão: o caso
canônico de `aluguel-09` i2 que a "regra da TEC-242" cita não mora no spec dela,
e sim no docstring de `TurnoAnotado`, que ela escreveu — e o que muda ali não é o
critério de *nomear a tipologia*, que continua de pé, mas o balde para onde vai o
turno que falha nele.

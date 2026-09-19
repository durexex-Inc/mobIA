# Sonda: o modelo já oferece corretor sozinho? (TEC-272)

- data: 2026-09-19
- modelo: `claude-sonnet-5` (`modelo_agente`, `config.py`)
- commit da árvore medida: `73b0111`
- runner: `evals/sonda_oferta_de_corretor.py`, chamando `ClassificadorAnthropic.classificar`
  direto com `SISTEMA_DO_AGENTE` atual e sem estado acumulado — cada texto é o único turno
  da sua própria conversa. Não passa por `executar_turno`, então não passa por
  `pediu_humano` nem pelo append desta card: mede o modelo cru.
- repetições por frasagem: 20
- chamadas: 60
- objetivo: medir com que taxa o modelo já oferece corretor sozinho ao confirmar ser
  assistente virtual, para saber se o append que esta card acrescenta é quem entrega o
  CA-04.1 ou se é redundante com o que o modelo já faz por conta própria

**Diagnóstico, não gate.** Nenhum número aqui vira piso ou métrica, e nenhum prova o
conserto — o conserto é determinístico e quem o prova são os unitários de
`texto_com_oferta`. O que estas chamadas compram é uma coisa só: saber se o append
dispara quase sempre ou quase nunca.

**Isto não é corpus.** As três frasagens abaixo são invenção da sondagem da TEC-139, não
fala real de lead. `grep -riE "rob(o|ô)|automatico|humano|maquina" evals/corpus/*.yaml`
devolve zero nos cinco arquivos (D3 do desenho) — não existe, em lugar nenhum do repo,
fala real deste eixo.

## O gasto pode ter estourado o orçamento, e não há como saber

Uma primeira tentativa de rodar esta sonda morreu sem escrever nada: o processo foi
lançado em background por um subagente e morreu quando ele terminou. Como a sonda só
grava no fim, não dá para saber se chamadas pagas saíram nessa tentativa e se perderam.
**Confirmado: 60 chamadas** (a rodada que produziu este relatório). **Possível e não
medido: até 60 a mais**, na rodada morta. Teto autorizado: 80.

É o mesmo modo de falha que a sondagem da TEC-139 registrou — lá, uma quinta chamada
paga e respondida se perdeu para um `UnicodeEncodeError` ao imprimir num console
`cp1252` antes de gravar em disco — só que por outro mecanismo (processo em background
morto junto com o subagente que o lançou, em vez de uma exceção não tratada). O repo
registra esse tipo de coisa em vez de escondê-la.

## Resultado por frasagem

Critério de "ofereceu": `ja_oferece_corretor`, o mesmo detector que roda em produção —
não um critério paralelo escrito só para a sonda.

| frasagem | ofereceu | indisponíveis |
| --- | --- | --- |
| `vc e um robo?` | 0/20 (0%) | 0 |
| `to falando com uma pessoa?` | 17/20 (85%) | 0 |
| `isso e automatico ou tem alguem ai?` | 20/20 (100%) | 0 |

Nenhuma linha teve chamada indisponível — as 60 chamadas confirmadas mediram, todas.

### Primeira resposta de cada frasagem

#### `vc e um robo?`

> Oi! Sou o assistente virtual da imobiliária, isso mesmo 😊 Estou aqui pra te ajudar a
> encontrar um imóvel ou tirar dúvidas. Me conta, você está buscando comprar, alugar,
> investir ou vender algum imóvel?

#### `to falando com uma pessoa?`

> Oi! Sou o assistente virtual da imobiliária, mas pode ficar tranquilo(a) que vou te
> ajudar direitinho e, se precisar, te conecto com um corretor de verdade. Me conta, você
> está procurando comprar, alugar ou investir em um imóvel?

#### `isso e automatico ou tem alguem ai?`

> Oi! Eu sou um assistente virtual da imobiliária, mas fico aqui justamente pra te ajudar
> a começar o atendimento rapidinho :) Se precisar, um corretor de verdade entra em
> contato depois. Me conta, você está procurando um imóvel pra comprar, alugar, investir,
> ou quer vender algo que já tem?

## Leitura: a card não é no-op

As três taxas são muito diferentes entre si — 0%, 85%, 100% — e isso é achado, não
ruído: o comportamento do modelo depende fortemente da frasagem, e uma sondagem de um
turno por frasagem (como a da TEC-139) não tinha como enxergar essa dependência.

Em `"vc e um robo?"` o modelo **nunca** oferece corretor sozinho, em 20 tentativas. O
append é a única coisa que entrega o CA-04.1 nessa frasagem **fora de conversa nova** — a
card não é um no-op.

A ressalva não é detalhe, e vale contra o método desta própria sonda: em conversa nova o
`TEXTO_DA_IDENTIFICACAO` já entra como prefixo e já oferece corretor, então o append se
cala (`test_nao_duplica_quando_a_conversa_e_nova` prova). E a sonda manda **um turno sem
histórico**, que é exatamente o caso de conversa nova. O buraco que a card fecha é o do
lead que pergunta no sexto turno — que a sonda não mede e não tinha como medir.

## A TEC-139 mediu um dos três misses como se fosse a regra

A sondagem da TEC-139 (`2026-09-11-tec-139-identificacao-036d973.md`) mediu
`"to falando com uma pessoa?"` como **não** oferecendo corretor (uma execução, um turno).
A taxa real, medida aqui com repetição, é **85% oferecendo**. A observação única daquela
sondagem pegou um dos três misses de uma distribuição que na maioria das vezes oferece —
não a regra geral da frasagem.

Isto é o mesmo tipo de erro de leitura que a TEC-271 encontrou (números de uma execução
só tratados como taxa), e é exatamente a razão de esta card ter medido com repetição em
vez de repetir o método de turno único.

## A quarta frasagem da card saiu da amostra

A card TEC-272 cita quatro frasagens e um resultado agregado `2/4`. A quarta —
`"voce e humano ou maquina? nao quero falar com robo"` — dispara `pediu_humano` desde a
TEC-143 (mergeada em 15/09), quatro dias **depois** da sondagem da TEC-139 (11/09). Hoje
ela toma a trilha determinística daquela card e recebe `TEXTO_DO_PEDIDO_DE_HUMANO`, que já
oferece corretor por construção — medi-la gastaria 20 chamadas para confirmar que uma
trilha determinística é determinística.

`_conferir_a_fronteira`, em `evals/sonda_oferta_de_corretor.py`, assere essa relação antes
da primeira chamada paga e rodou limpa nesta árvore.

O `2/4` da card é um número de um mundo anterior à TEC-143: o denominador de hoje, para o
texto livre do modelo, é **3**, não 4.

## A remoção da família "isso" do detector, medida

Na Task 1 desta card, a família `"isso"` foi removida inteira do detector de robô
(`Ruling T1-D`, `progress.md`), com o argumento de que era "a família em que o append
quase nunca precisaria disparar" — nenhum detector de palavra-chave resolve a anáfora de
`"isso"` sem também casar frases de portaria/contrato que não são pergunta de identidade,
e a canônica (`"isso e automatico ou tem alguem ai?"`) é estruturalmente idêntica aos
falsos positivos que sairiam junto.

A sonda mede **100%** para essa frasagem. O argumento era uma aposta correta e agora é
evidência: é o único ponto em que esta medição confirma, em vez de apenas informar, uma
decisão de desenho desta card.

## Lacunas do desenho (D3), repetidas

- **Não é corpus.** As três frasagens são inventadas; não existe fala real deste eixo em
  `evals/corpus/*.yaml` (D3 do desenho).
- **A recall do detector de entrada é inverificável.** Não há fala real deste eixo no
  repo, os termos do detector são invenção, e o que os testes provam é o lado negativo —
  que o detector não dispara em fala do corpus —, não que ele pega tudo que deveria.
- **A sonda mede o vocabulário do próprio teste.** Qualquer termo medido aqui é invenção
  da TEC-139 ou desta card; medir a taxa de oferta contra essas três frasagens é medir o
  modelo contra o vocabulário do teste, não contra uma amostra de fala real.

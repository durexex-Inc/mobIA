# TEC-242 — Sinônimos de `tipo_imovel`

**Status:** aprovado em 2026-08-29. Não implementado.

**Card:** [TEC-242](https://eduardodurieuxlopes.atlassian.net/browse/TEC-242) — origem: a execução paga do gate de 28/08/2026.

## Objetivo

Na execução de 28/08, `tipo_imovel` respondeu por **8 das 29 discrepâncias** — o segundo maior balde, atrás só de `regiao` (10), que virou a TEC-241.

O lead brasileiro diz **kitnet**, **república**, **sobrado**, **studio**, **flat**, **cobertura duplex**. `TipoImovel` é vocabulário fechado — `APARTAMENTO`, `CASA`, `TERRENO`, `COMERCIAL`, `RURAL` — porque `lead_qualification.tipo_imovel` é filtrado em SQL pela TEC-158.

## A premissa do card que a verificação derrubou

O card oferecia três opções e a decisão de produto escolheu a **1**: um mapa de sinônimos em código, aplicado em `extrair`, na forma que a TEC-241 usou para `regiao`.

**Essa opção é inviável, e a verificação é de uma linha.** O schema da chamada, medido:

```
tipo_imovel: {"anyOf": [{"enum": ["APARTAMENTO","CASA","TERRENO","COMERCIAL","RURAL"]}, {"type":"null"}]}
```

O schema é **estrito**. O modelo não consegue devolver `"kitnet"` — a API o restringe ao enum. E `carregar` (`src/mobia/evals/corpus.py`) valida a anotação contra o mesmo vocabulário, então o corpus também não consegue anotar `"kitnet"`.

Um mapa em `extrair` nunca teria entrada: `bruto.get("tipo_imovel")` já chega como valor do enum ou `null`. Em `_comparavel`, idem. **Seria código morto.**

### O que as 8 discrepâncias de fato são

Não é o modelo dizendo "kitnet". É o modelo fazendo a tradução **sozinho e certo** — devolvendo `APARTAMENTO` para *"queria alugar um kitnet perto da usp"* — e o corpus tendo anotado **nada** ali. `campos` presente é contrato de anotação completa, então isso conta `extra`: **erro cheio, por acertar**.

O problema nunca foi o modelo não saber traduzir. Foi o corpus não ter decidido a tradução, e por isso punir quem traduz.

**Decisão: a card passa da opção 1 para a opção 3.** A decisão de produto continua valendo — kitnet é apartamento, sobrado é casa —, mas ela não é código de tradução: é a **regra que diz ao anotador** o que anotar, e as anotações que decorrem dela.

## O que já existe

Levantado no corpus da `main` mergeada (57aee2d), depois de TEC-238, TEC-239, TEC-240 e TEC-241, não presumido.

**18 anotações de `tipo_imovel`.** Todas as 18 vêm de falas que já usam uma palavra do vocabulário: *apartamento*, *apto*, *casa*, *terreno*, *sala comercial*. **Nenhuma** vem de um sinônimo.

**10 turnos usam sinônimo fora do vocabulário**, em três estados diferentes:

| turno | fala | estado hoje |
|---|---|---|
| `aluguel-01` i0 | kitnet | positivo, `{regiao}` — **sem** `tipo_imovel` |
| `aluguel-07` i0 | república **ou** kitnet | positivo, `{regiao}` — **sem** `tipo_imovel` |
| `compra-11` i0 | sobrado | positivo, `{regiao}` — **sem** `tipo_imovel` |
| `aluguel-05` i1 | flat | fora da medição |
| `aluguel-06` i0 | studio | fora da medição |
| `compra-06` i0, i1, i2 | cobertura duplex | fora da medição |
| `compra-11` i2 | sobrado | fora da medição |
| `investimento-01` i0 | studio | fora da medição |

Os **três primeiros** são o caso caro: estão anotados, com anotação declarada completa, e omitem o tipo. É onde a tradução correta vira `extra`.

## Decisões

### D1 — A regra, e onde ela mora

| sinônimo | vira |
|---|---|
| kitnet | `APARTAMENTO` |
| studio | `APARTAMENTO` |
| flat | `APARTAMENTO` |
| cobertura duplex | `APARTAMENTO` |
| sobrado | `CASA` |

A regra vai no **docstring de `TurnoAnotado`** (`src/mobia/evals/corpus.py`), junto das outras regras de anotação — o imóvel que o lead *tem* não é o que ele procura, pergunta sobre forma de pagamento conta como afirmação, `regiao` se anota como topônimo.

**Nenhuma mudança em `src/mobia/domain/`.** Nada em `extrair`, nada no schema, nada no prompt.

### D2 — `república` fica fora, e o motivo é a fala, não a política

`república` não é tipologia — é **uso**, e pode ser casa ou apartamento. A única ocorrência no corpus torna isso explícito: `aluguel-07` i0 diz *"procuro **republica ou kitnet** pra alugar perto da unicamp"* — o lead oferece **duas** opções e não escolhe.

O turno **continua anotado sem `tipo_imovel`**, agora com o motivo escrito.

Consequência aceita, e registrada porque é incômoda: um modelo que devolva `APARTAMENTO` ali por causa do *kitnet* continuará levando `extra`. A alternativa — anotar um dos dois valores — puniria o modelo por escolher o outro, que é pior. É o mesmo erro simétrico que a régua já pune nos dois sentidos.

### D3 — Os sete fora da medição passam a ser anotados

Todos os sete **nomeiam** a tipologia na própria fala. Anotação completa de cada um:

| turno | anotação |
|---|---|
| `aluguel-05` i1 | `{tipo_imovel: APARTAMENTO}` |
| `aluguel-06` i0 | `{tipo_imovel: APARTAMENTO, urgencia: ATE_3_MESES}` |
| `compra-06` i0 | `{tipo_imovel: APARTAMENTO}` |
| `compra-06` i1 | `{tipo_imovel: APARTAMENTO}` |
| `compra-06` i2 | `{tipo_imovel: APARTAMENTO}` |
| `compra-11` i2 | `{tipo_imovel: CASA}` |
| `investimento-01` i0 | `{tipo_imovel: APARTAMENTO}` |

O `urgencia` de `aluguel-06` i0 entra pela barra que a TEC-239 fixou: *"meu contrato de aluguel atual vence **mes que vem**"* é marco temporal explícito.

Os três de `compra-06` são perguntas que **pressupõem** o imóvel já nomeado. Anotá-las segue o precedente que o corpus já tem: `aluguel-08` i2 — *"o predio ja tem alvara pra uso comercial de saude?"* — está anotado `tipo_imovel: COMERCIAL`.

Contagem resultante: **38 → 45 turnos positivos**, `tipo_imovel` de **18 → 27** anotações, negativos inalterados em **37**.

### D4 — Esta card desfaz duas exclusões que outras cards escreveram

E isso é o ponto, não um efeito colateral.

- A **TEC-238** excluiu `compra-11` i2 de propósito, com o argumento de que *"um modelo que devolve `CASA` para 'sobrado' está lendo a fala com razão"*.
- A **TEC-239** recusou anotar `aluguel-06` i0 justamente porque *"studio"* não caía no vocabulário.

As duas exclusões existiam porque **não havia regra**. Esta card cria a regra, então os comentários que as justificam ficam falsos e saem — do corpus e de onde mais tiverem sido registrados.

Não é retrabalho: é a dívida sendo paga onde foi contraída, e as duas cards nomearam esse momento por escrito.

### D5 — O termo original continua sem ser preservado

`lead_qualification.tipo_imovel` guarda só o valor canônico. Quem disse *kitnet* vira `APARTAMENTO`, e a palavra some do estado.

**Isso não é escolha desta card — o schema estrito nunca permitiu outra coisa.** Preservar a distinção exigiria alargar `TipoImovel` (opção 2 do card), que muda a coluna, o conjunto que a TEC-158 vai filtrar, e o schema compilado, que entra na subcontagem do orçamento de contexto — hoje em 587 de um teto de 600.

O que fica declarado no README, e é metade do valor desta card:

- *kitnet*, *studio* e *flat* não são a mesma coisa que *apartamento* para o lead — mudam faixa de preço e metragem — e essa distinção não existe no estado de qualificação;
- o consolo que a TEC-241 usou para `regiao` (*"o texto original segue no histórico de mensagens, cifrado"*) **é mais fraco aqui**: a TEC-240 registrou que `_texto_do_estado` alimenta o **prompt de verdade**, então a memória que o modelo enxerga também lê `APARTAMENTO`, e quando as mensagens literais saírem da janela a palavra do lead some da visão dele;
- preservar o termo é card futura, e o que a bloqueia é o orçamento de contexto — não falta de vontade.

## Testes

Não há função nova para testar. O guarda certo é sobre o **corpus commitado**:

1. **Todo turno cuja fala contenha um sinônimo ou tem `tipo_imovel` anotado, ou está numa lista nomeada de exceções** — hoje só `aluguel-07` i0. Sem ele, o próximo turno com "kitnet" entra sem tipo e a punição volta em silêncio.

   A lista de **detecção** do teste tem seis palavras, e não as cinco do mapa: `kitnet`, `studio`, `flat`, `cobertura`, `sobrado` e **`republica`**. Duas precisões que importam:

   - a palavra é `cobertura`, não `cobertura duplex` — `compra-06` i1 e i2 dizem só *"na cobertura"* e *"dessa cobertura"*;
   - `republica` entra na detecção **apesar de não estar no mapa**, por motivo prospectivo: hoje ela não muda nada — o único turno que a usa, `aluguel-07` i0, já contém "kitnet" e seria detectado sem ela —, mas um turno futuro que diga só *"procuro uma república perto da PUC"*, sem outro sinônimo junto, precisa ser detectado e forçado a uma decisão explícita em vez de entrar sem tipo em silêncio.

2. A lista de exceções é uma constante nomeada no arquivo de teste, com o motivo em comentário — o mesmo padrão que a TEC-241 usou para as anotações grandfathered de `regiao`.
3. As contagens do README batem com o corpus, verificadas por execução.

## Contrato depois da card

- Regra de sinônimos escrita onde o anotador a lê.
- 45 turnos positivos, 37 negativos, `tipo_imovel` com 27 anotações.
- Nenhum turno com sinônimo na fala fica sem tipo, exceto `aluguel-07` i0, com motivo.
- Zero mudança em `src/mobia/domain/`.

## O que esta card não entrega

**O critério "as discrepâncias de `tipo_imovel` caem numa execução do gate" exige execução paga, e ela não será feita aqui.**

E continua sem existir **baseline comparável**: os 29 de 28/08 são anteriores à TEC-238, à TEC-239, à TEC-240 e à TEC-241. A próxima execução vai medir cinco mudanças sobrepostas. Isso é lacuna conhecida, registrada na TEC-244.

## Fora de escopo

- Alargar `TipoImovel` (opção 2 do card).
- Preservar o termo original do lead.
- A ordem do prompt contra a do schema — [TEC-244](https://eduardodurieuxlopes.atlassian.net/browse/TEC-244).
- Qualquer mudança em `extrair`, no schema ou no prompt.

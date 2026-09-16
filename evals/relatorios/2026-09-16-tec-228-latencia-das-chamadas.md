# Latência das chamadas pagas do turno (TEC-228)

- data: 2026-09-16, ~14h local (UTC-3)
- modelos: `claude-sonnet-5` (`modelo_agente` e `modelo_resumo`, `config.py`)
- máquina: desktop de desenvolvimento, Windows 11, ociosa
- amostras: 5 por cenário (3 no investidor)
- script: não comitado, rodou do scratchpad da sessão; usava os prompts e os
  `max_tokens` **de produção**, importados dos módulos, contra a API real
- commit medido: `a82511b` (a medição precedeu a implementação)

A card pedia medir antes de escolher os tetos. Estes são os números que os
escolheram.

## Resultado

| chamada | `max_tokens` | mediana | máximo | saída real | teto escolhido |
| --- | --- | --- | --- | --- | --- |
| `count_tokens` | — | 0,25s | 0,28s | — | 5s |
| `desambiguar` | 300 | 1,43s | 1,69s | 41 tokens | 12s |
| `resumir` | 2000 | 2,87s | 3,72s | ~242 tokens | 25s |
| `classificar` | 1500 | 6,25s | 7,49s | ~460 tokens | 25s |
| `investidor` | 1500 | 8,05s | 9,26s | ~600 tokens | 35s |

## O que a medição derrubou

**O `resumir` não é o perigoso.** A card afirmava que *"uma geração legítima de
2000 tokens em opus pode se aproximar de 60 segundos"*. Não roda em opus
(`modelo_resumo` é `claude-sonnet-5` desde a troca por custo) e não gera 2000
tokens (gera ~242). É o segundo mais rápido dos cinco.

**A latência é governada pelos tokens de saída, não pelo teto.** O `resumir`
tem o maior `max_tokens` da tabela e a segunda menor latência. Quem estimar
custo de tempo a partir de `max_tokens` erra na direção do pânico.

## O alarme falso, que é a parte mais útil deste relatório

Na primeira passada o investidor apareceu com **18,56s de mediana e 2 de 5
amostras cortadas** no teto de 1500 tokens. Quase virou card de defeito.

Era artefato da medição: o cenário alimentava o prompt do investidor com uma
conversa de **aluguel**, e o descasamento fazia o modelo divagar até bater no
teto. Refeito com uma conversa de investidor de verdade: **8,05s, ~600 tokens,
zero cortes em 3 amostras**.

**Medição com entrada descasada produz defeito que não existe.** Quem repetir
esta medição use entrada fiel ao caminho que está medindo — é a única parte
deste relatório que continua valendo depois que os números envelhecerem.

## Limitações declaradas

**Uma máquina, um momento, cinco amostras.** Não é p95 de produção e não
pretende ser: é a ordem de grandeza que faltava para escolher teto. A folga de
~3× sobre o máximo existe porque a medição é o que é.

**O prompt cache provavelmente ajudou.** Repetir o mesmo `system` cinco vezes é
o melhor caso de cache. Produção também o usa (`cache_control`), mas não no
primeiro turno de cada conversa — que é justamente o caso frio. Os números aqui
são otimistas para ele.

**`classificar` foi medido SEM ferramenta.** O script não declarava `tools`,
então mede o caminho sem busca. Um turno que busca faz duas requisições e ainda
paga a execução da porta entre elas; `_PIOR_TURNO` em `infra/anthropic.py` conta
a fatia em dobro por causa disso, mas o número de cada requisição continua sendo
o daqui.

**`reagir` não foi medido.** Herda o teto de `desambiguar` por ter a mesma forma
— 300 tokens de saída, sem ferramenta, uma requisição.

**O embed da busca não foi medido, e é o maior termo do orçamento.** Não há
`OPENAI_API_KEY` nesta máquina, então a sonda não rodou. O teto de 10s de
`TETO_DA_CONSULTA_DO_TURNO` é o dobro do que a medição deu para `count_tokens`
— a chamada de forma mais parecida que existe medida aqui — e está declarado
como não medido no próprio comentário. **É o número menos sustentado deste
conjunto**; quem tiver a chave mede e corrige.

**Nada aqui mede qualidade.** A troca opus→sonnet do resumo continua sem
instrumento: este relatório mede tempo.

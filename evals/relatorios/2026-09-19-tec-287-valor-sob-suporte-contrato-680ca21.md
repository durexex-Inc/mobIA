# Sonda: valor citado sob SUPORTE_CONTRATO vira orçamento? (TEC-287)

- data: 2026-09-19
- modelo: `claude-sonnet-5` (`modelo_agente`, `config.py`)
- commit da árvore medida: `680ca21`
- runner: `evals/sonda_valor_sob_suporte_contrato.py`, chamando `ClassificadorAnthropic.classificar`
  direto com `SISTEMA_DO_AGENTE` atual e sem estado acumulado — cada fala é o único turno
  da sua própria conversa. Não passa por `executar_turno`: mede o modelo cru, que é o que a
  pergunta pede, porque o vazamento da card começa no primeiro turno de uma conversa que
  ainda não tinha orçamento nenhum.
- repetições por fala: 3
- chamadas: 36
- custo: ~US$ 0,16
- objetivo: a TEC-287 manda, com todas as letras, medir antes de decidir — *"se for raro a
  ponto de não aparecer, a card pode não valer o risco de mexer no filtro de gravação, e
  essa conclusão também é um resultado."*

**Diagnóstico, não gate.** Nenhum número aqui vira piso ou métrica.

## A pergunta, e por que o corpus não a respondia

A card afirma que um valor dito num turno de suporte de contrato vira teto de preço de uma
busca de compra. A metade de código dessa afirmação é verdadeira, e foi conferida antes de
gastar a primeira chamada — é o que `_conferir_a_fronteira` faz no runner:

```
campos_a_gravar(SUPORTE_CONTRATO, Extracao(faixa_preco_max_centavos=280_000))
-> {'intencao': 'SUPORTE_CONTRATO', 'faixa_preco_max_centavos': 280000}
```

O filtro de gravação **deixa passar**: só `FORA_DE_ESCOPO` devolve dict vazio, e `INDEFINIDA`
perde a intenção mas mantém os campos.

Faltava a outra metade: o extrator chega a preencher a faixa num turno desses? O corpus não
respondia. Ele tinha sete turnos `SUPORTE_CONTRATO`, todos com `campos: {}` — mas **nenhum
deles cita dinheiro**, então nenhum teve a chance de vazar. Zero de sete, ali, era evidência
sobre o que o autor do corpus pensou em escrever, não sobre o comportamento do extrator.

## O método

Doze falas de suporte de contrato que **citam** um valor, variadas em dois eixos de propósito:

- **forma do número:** `2.800`, `dois mil e oitocentos`, `2,8 mil`, `R$ 4200`
- **papel do valor na frase:** o que paga hoje, o reajuste, uma multa, uma caução, o condomínio

Uma das doze é a fala **exata** do exemplo da card.

Critério de vazamento: a intenção volta `SUPORTE_CONTRATO` **e** a faixa de preço vem
preenchida. Uma fala classificada `ALUGUEL` com faixa preenchida não é este defeito — ali a
banda valida o número.

## O resultado

| | |
| --- | --- |
| chamadas medidas | 36 |
| indisponíveis | 0 |
| classificadas fora de `SUPORTE_CONTRATO` | **0** |
| com faixa de preço preenchida | **0** |
| **vazaram** | **0/36 (0%)** |

Todas as doze falas deram `min=None max=None` nas três repetições. A tabela por fala está no
relatório bruto que o runner escreve em `evals/relatorios/_sonda-tec-287-bruto.md`, que não é
versionado.

A coluna que decide não é a do zero — é a do meio. **O classificador acertou
`SUPORTE_CONTRATO` nas 36 chamadas** e em nenhuma preencheu a faixa. O modelo já distingue
sozinho "o que eu pago hoje" de "o que eu posso pagar", que é exatamente a distinção que a
card afirmava que o sistema não faz.

## A conclusão, e o que ela mudou

**O vazamento é alcançável em código e inalcançável na prática.** A recomendação foi não
mexer em `campos_a_gravar`: é a regra única compartilhada entre produção e o runner do eval
— a docstring dela registra que foi extraída justamente para que os dois não divirjam — e o
raio de uma mudança ali alcança as sete intenções, para um ganho medido nulo.

**Mas a sonda achou uma lacuna real, e ela não é a da card.** 0/36 é comportamento do modelo
de hoje com o prompt de hoje, não invariante: uma mudança de prompt ou de modelo vira isso em
silêncio, e nada no repo pegaria. Por isso três conversas novas entraram em
`evals/corpus/borda.yaml` (`borda-suporte-valor-01` a `-03`), cobrindo os dois eixos medidos
mais o caminho de dano completo — valor citado no suporte, pergunta de compra no turno
seguinte, `campos` sem faixa nenhuma nos dois.

Ali o `campos: {}` não é ausência de anotação: é a asserção de que o valor citado **não** é
orçamento, e ela roda toda vez que alguém rodar o eval.

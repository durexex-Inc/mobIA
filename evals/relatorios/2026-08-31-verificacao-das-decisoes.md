# Condicoes de validade da execucao

- data: 2026-08-31 11:46 UTC
- modelo: claude-sonnet-5
- corpus no disco: 53 conversas, 147 turnos
- conversas abandonadas por infraestrutura: 0, teto 5
- turnos medidos: 147/120, folga de 27
- turnos anotados positivos: 62/45, folga de 17
- turnos anotados negativos: 71/53, folga de 18

Folga negativa em qualquer linha acima invalida a execucao: o numero
medido nao tem amostra que o sustente, e re-rodar e mais barato que
acreditar nele.

# Avaliacao da classificacao de intencao

- **acuracia de intencao**: VERDE -- 143/147 (97.3%), alvo 90%, piso 84%
- **acuracia efetiva (o que producao roteia)**: VERDE -- 143/147 (97.3%), alvo 90%, piso 84%
- **precisao da extracao**: VERDE -- 89/98 (90.8%), alvo 90%, piso 85%
- **taxa de alucinacao**: SEM_MECANISMO -- sem mecanismo: bloqueada pela TEC-161
- **aderencia ao tom**: SEM_MECANISMO -- sem mecanismo: TEC-140 nao existe

## Confianca

- limiar de desambiguacao: 0.6
- turnos abaixo do limiar: 4/147 (2.7%)
- acertos rebaixados para INDEFINIDA: 0
- erros que o rebaixamento acertou: 0

## Reperguntas (proxy de palavra-chave, diagnostico)

- total detectado: 18
  - tipo_imovel: 11
  - forma_pagamento: 3
  - quartos: 3
  - regiao: 1

## Extracao: a conta aberta, e quanto ela resolve (diagnostico)

- campos anotados no corpus (base fixa): 97
- acertos: 89 -- 91.8% da base fixa
- faltou: 7 | divergiu: 1 | inventados (extra): 1

  A metrica que trava usa denominador de uniao (esperado | obtido), e
  e assim de proposito: sem contar o inventado, um modelo que acerta o
  anotado e inventa mais quatro tiraria 100%. O preco e que ela soma
  numa razao so duas coisas que se movem diferente -- `faltou` e
  `divergiu` medem o defeito e sao estaveis; `extra` oscila, e cada
  campo inventado desconta duas vezes, deixando de ser acerto e
  inflando o denominador.

  **Poder de resolucao (medido em 30/08/2026, TEC-253):** duas
  execucoes do MESMO codigo ja diferiram 5.7 pontos na
  metrica de uniao e 2.1 na base fixa. Nao atribua a
  uma mudanca um efeito dessa ordem a partir de uma execucao so --
  compare `faltou` e `divergiu`, que sao a parte estavel, e trate
  `extra` como quantidade que precisa de varias execucoes.

  Duas execucoes nao sao distribuicao: e a maior diferenca observada,
  nao a dispersao real.

## Extracao efetiva: o estado que a conversa deixou (diagnostico)

- 53 conversas, estado final contra anotacao acumulada
- campos corretos no estado: 85/90 (94.4%)

  Compare com a precisao turno a turno acima. A diferenca entre as
  duas nao e erro de nenhuma: `None` nao apaga, entao um campo que o
  modelo deixou de reemitir num turno posterior continua gravado. A
  metrica turno a turno cobra a reemissao; o lead experimenta o
  estado. Onde as duas discordam, e a de cima que mede o modelo e
  esta que mede o produto.

Campos errados no estado final:

  - compra-02: regiao (extra) -- obtido 'metro'
  - compra-13: regiao (divergiu) -- anotado 'sao roque', obtido 'sao roque e arredores'
  - compra-13: urgencia (faltou) -- anotado 'SEM_PRESSA'
  - follow-up-01: forma_pagamento (extra) -- obtido <FormaPagamento.FINANCIAMENTO: 'FINANCIAMENTO'>
  - follow-up-08: urgencia (faltou) -- anotado 'IMEDIATA'

## Extracao: campos que nao casaram (diagnostico)

- total de discrepancias: 9
- 71 turnos negativos medidos, 1 com invencao (1 campo)

  Num turno negativo, `extra` e invencao sem ambiguidade: o turno
  esta anotado por completo, e o completo e vazio.

  - tipo_imovel -- extra: 1, faltou: 4
  - urgencia -- faltou: 2
  - forma_pagamento -- faltou: 1
  - regiao -- divergiu: 1

Onde, para quem for anotar:

  - aluguel-01 turno 1: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>
  - aluguel-08 turno 2: tipo_imovel (faltou) -- anotado 'COMERCIAL'
  - compra-06 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-06 turno 2: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-11 turno 2: tipo_imovel (faltou) -- anotado 'CASA'
  - compra-13 turno 0: regiao (divergiu) -- anotado 'sao roque', obtido 'sao roque e arredores'
  - compra-13 turno 1: urgencia (faltou) -- anotado 'SEM_PRESSA'
  - compra-14 turno 2: forma_pagamento (faltou) -- anotado 'CONSORCIO'
  - follow-up-08 turno 1: urgencia (faltou) -- anotado 'IMEDIATA'

## Classificacoes erradas

conversa_id[indice]: esperada -> obtida (confianca)

- borda-longa-01[1]: COMPRA -> INDEFINIDA (0.50)  <-- errada, e rebaixada para INDEFINIDA
- borda-longa-01[2]: COMPRA -> INDEFINIDA (0.50)  <-- errada, e rebaixada para INDEFINIDA
- follow-up-01[0]: COMPRA -> INDEFINIDA (0.40)  <-- errada, e rebaixada para INDEFINIDA
- follow-up-08[1]: COMPRA -> SUPORTE_CONTRATO (0.72)

## Matriz de confusao

esperada -> obtida (contagem)

- ALUGUEL -> ALUGUEL: 32
- COMPRA -> COMPRA: 54
- COMPRA -> INDEFINIDA: 3  <-- erro
- COMPRA -> SUPORTE_CONTRATO: 1  <-- erro
- FORA_DE_ESCOPO -> FORA_DE_ESCOPO: 9
- INDEFINIDA -> INDEFINIDA: 9
- INVESTIMENTO -> INVESTIMENTO: 26
- SUPORTE_CONTRATO -> SUPORTE_CONTRATO: 7
- VENDER_IMOVEL -> VENDER_IMOVEL: 6

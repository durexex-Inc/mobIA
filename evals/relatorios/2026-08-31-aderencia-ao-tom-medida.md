# Condicoes de validade da execucao

- data: 2026-08-31 13:19 UTC
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

- **acuracia de intencao**: VERDE -- 144/147 (98.0%), alvo 90%, piso 84%
- **acuracia efetiva (o que producao roteia)**: VERDE -- 143/147 (97.3%), alvo 90%, piso 84%
- **precisao da extracao**: VERDE -- 89/98 (90.8%), alvo 90%, piso 85%
- **taxa de alucinacao**: SEM_MECANISMO -- sem mecanismo: bloqueada pela TEC-161
- **aderencia ao tom**: AMARELO -- 121/147 (82.3%), alvo 90%, piso-andaime 50%

## Confianca

- limiar de desambiguacao: 0.6
- turnos abaixo do limiar: 5/147 (3.4%)
- acertos rebaixados para INDEFINIDA: 1
- erros que o rebaixamento acertou: 0

## Reperguntas (proxy de palavra-chave, diagnostico)

- total detectado: 21
  - tipo_imovel: 11
  - quartos: 5
  - forma_pagamento: 2
  - regiao: 2
  - urgencia: 1

## Extracao: a conta aberta, e quanto ela resolve (diagnostico)

- campos anotados no corpus (base fixa): 97
- acertos: 89 -- 91.8% da base fixa
- faltou: 8 | divergiu: 0 | inventados (extra): 1

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
- campos corretos no estado: 86/92 (93.5%)

  Compare com a precisao turno a turno acima. A diferenca entre as
  duas nao e erro de nenhuma: `None` nao apaga, entao um campo que o
  modelo deixou de reemitir num turno posterior continua gravado. A
  metrica turno a turno cobra a reemissao; o lead experimenta o
  estado. Onde as duas discordam, e a de cima que mede o modelo e
  esta que mede o produto.

Campos errados no estado final:

  - aluguel-07: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - borda-injecao-01: forma_pagamento (faltou) -- anotado 'FINANCIAMENTO'
  - borda-mista-02: vagas (extra) -- obtido 0
  - compra-02: regiao (extra) -- obtido 'de metro'
  - follow-up-01: forma_pagamento (extra) -- obtido <FormaPagamento.FINANCIAMENTO: 'FINANCIAMENTO'>
  - follow-up-06: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>

## Formato da resposta (diagnostico)

- 147 respostas do agente medidas
- acima de 600 caracteres: 2
- com mais de 1 pergunta: 26
- com emoji: 17 (17 no total)

  A contagem de emoji **nao** entra na metrica. A regra e "a
  informacao essencial nunca depende de emoji", e decidir isso exige
  entender o que a frase afirma -- nenhuma contagem responde. O numero
  fica como pista para quem for ler as respostas.

  Contar `?` e proxy, como o de reperguntas: erra nas duas direcoes.

Onde:

  - aluguel-01 turno 0: perguntas -- 2
  - aluguel-06 turno 0: perguntas -- 2
  - borda-injecao-01 turno 1: perguntas -- 2
  - borda-evasivo-02 turno 0: perguntas -- 2
  - borda-mista-01 turno 0: perguntas -- 2
  - borda-longa-01 turno 1: perguntas -- 2
  - compra-02 turno 0: perguntas -- 2
  - compra-02 turno 1: perguntas -- 2
  - compra-02 turno 2: perguntas -- 2
  - compra-02 turno 3: perguntas -- 2
  - compra-10 turno 1: comprimento -- 602
  - compra-10 turno 1: perguntas -- 2
  - compra-10 turno 2: comprimento -- 625
  - compra-10 turno 2: perguntas -- 2
  - compra-10 turno 3: perguntas -- 2
  - compra-14 turno 0: perguntas -- 2
  - compra-14 turno 1: perguntas -- 2
  - compra-14 turno 2: perguntas -- 2
  - follow-up-07 turno 0: perguntas -- 3
  - investimento-01 turno 0: perguntas -- 2
  - investimento-03 turno 0: perguntas -- 2
  - investimento-03 turno 1: perguntas -- 2
  - investimento-04 turno 0: perguntas -- 2
  - investimento-05 turno 1: perguntas -- 2
  - investimento-06 turno 0: perguntas -- 2
  - investimento-08 turno 0: perguntas -- 2
  - investimento-09 turno 0: perguntas -- 2
  - investimento-10 turno 1: perguntas -- 2

## Extracao: campos que nao casaram (diagnostico)

- total de discrepancias: 9
- 71 turnos negativos medidos, 0 com invencao (0 campos)

  Num turno negativo, `extra` e invencao sem ambiguidade: o turno
  esta anotado por completo, e o completo e vazio.

  - tipo_imovel -- extra: 1, faltou: 6
  - forma_pagamento -- faltou: 2

Onde, para quem for anotar:

  - aluguel-05 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - aluguel-07 turno 0: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - aluguel-08 turno 2: tipo_imovel (faltou) -- anotado 'COMERCIAL'
  - borda-injecao-01 turno 1: forma_pagamento (faltou) -- anotado 'FINANCIAMENTO'
  - compra-06 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-06 turno 2: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-11 turno 2: tipo_imovel (faltou) -- anotado 'CASA'
  - compra-14 turno 2: forma_pagamento (faltou) -- anotado 'CONSORCIO'
  - follow-up-06 turno 0: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>

## Classificacoes erradas

conversa_id[indice]: esperada -> obtida (confianca)

- borda-longa-01[1]: COMPRA -> INDEFINIDA (0.50)  <-- errada, e rebaixada para INDEFINIDA
- borda-longa-01[2]: COMPRA -> INDEFINIDA (0.50)  <-- errada, e rebaixada para INDEFINIDA
- compra-11[0]: COMPRA -> COMPRA (0.55)  <-- certa, rebaixada para INDEFINIDA
- follow-up-01[0]: COMPRA -> INDEFINIDA (0.35)  <-- errada, e rebaixada para INDEFINIDA

## Matriz de confusao

esperada -> obtida (contagem)

- ALUGUEL -> ALUGUEL: 32
- COMPRA -> COMPRA: 55
- COMPRA -> INDEFINIDA: 3  <-- erro
- FORA_DE_ESCOPO -> FORA_DE_ESCOPO: 9
- INDEFINIDA -> INDEFINIDA: 9
- INVESTIMENTO -> INVESTIMENTO: 26
- SUPORTE_CONTRATO -> SUPORTE_CONTRATO: 7
- VENDER_IMOVEL -> VENDER_IMOVEL: 6

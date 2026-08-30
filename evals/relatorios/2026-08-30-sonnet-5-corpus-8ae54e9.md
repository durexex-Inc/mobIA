# Condicoes de validade da execucao

- data: 2026-08-30 14:44 UTC
- modelo: claude-sonnet-5
- corpus no disco: 53 conversas, 146 turnos
- conversas abandonadas por infraestrutura: 0, teto 5
- turnos medidos: 146/120, folga de 26
- turnos anotados positivos: 62/45, folga de 17
- turnos anotados negativos: 70/53, folga de 17

Folga negativa em qualquer linha acima invalida a execucao: o numero
medido nao tem amostra que o sustente, e re-rodar e mais barato que
acreditar nele.

# Avaliacao da classificacao de intencao

- **acuracia de intencao**: VERDE -- 143/146 (97.9%), alvo 90%, piso 84%
- **acuracia efetiva (o que producao roteia)**: VERDE -- 143/146 (97.9%), alvo 90%, piso 84%
- **precisao da extracao**: AMARELO -- 88/103 (85.4%), alvo 90%, piso 85%
- **taxa de alucinacao**: SEM_MECANISMO -- sem mecanismo: bloqueada pela TEC-161
- **aderencia ao tom**: SEM_MECANISMO -- sem mecanismo: TEC-140 nao existe

## Confianca

- limiar de desambiguacao: 0.6
- turnos abaixo do limiar: 4/146 (2.7%)
- acertos rebaixados para INDEFINIDA: 0
- erros que o rebaixamento acertou: 0

## Reperguntas (proxy de palavra-chave, diagnostico)

- total detectado: 19
  - tipo_imovel: 11
  - quartos: 5
  - forma_pagamento: 2
  - urgencia: 1

## Extracao: campos que nao casaram (diagnostico)

- total de discrepancias: 15
- 70 turnos negativos medidos, 0 com invencao (0 campos)

  Num turno negativo, `extra` e invencao sem ambiguidade: o turno
  esta anotado por completo, e o completo e vazio.

  - tipo_imovel -- extra: 5, faltou: 5
  - urgencia -- extra: 2, faltou: 1
  - forma_pagamento -- faltou: 1
  - tem_imovel_para_vender -- faltou: 1

Onde, para quem for anotar:

  - aluguel-05 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - aluguel-07 turno 0: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>
  - aluguel-08 turno 1: tipo_imovel (extra) -- obtido <TipoImovel.COMERCIAL: 'COMERCIAL'>
  - aluguel-08 turno 2: tipo_imovel (faltou) -- anotado 'COMERCIAL'
  - compra-04 turno 2: tipo_imovel (extra) -- obtido <TipoImovel.CASA: 'CASA'>
  - compra-06 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-06 turno 2: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-10 turno 0: tem_imovel_para_vender (faltou) -- anotado False
  - compra-11 turno 2: tipo_imovel (faltou) -- anotado 'CASA'
  - compra-14 turno 2: forma_pagamento (faltou) -- anotado 'CONSORCIO'
  - follow-up-03 turno 0: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>
  - follow-up-06 turno 0: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>
  - follow-up-07 turno 2: urgencia (extra) -- obtido <Urgencia.IMEDIATA: 'IMEDIATA'>
  - follow-up-08 turno 0: urgencia (extra) -- obtido <Urgencia.IMEDIATA: 'IMEDIATA'>
  - follow-up-08 turno 1: urgencia (faltou) -- anotado 'IMEDIATA'

## Classificacoes erradas

conversa_id[indice]: esperada -> obtida (confianca)

- borda-longa-01[1]: COMPRA -> INDEFINIDA (0.55)  <-- errada, e rebaixada para INDEFINIDA
- borda-longa-01[2]: COMPRA -> INDEFINIDA (0.40)  <-- errada, e rebaixada para INDEFINIDA
- follow-up-01[0]: COMPRA -> INDEFINIDA (0.40)  <-- errada, e rebaixada para INDEFINIDA

## Matriz de confusao

esperada -> obtida (contagem)

- ALUGUEL -> ALUGUEL: 32
- COMPRA -> COMPRA: 54
- COMPRA -> INDEFINIDA: 3  <-- erro
- FORA_DE_ESCOPO -> FORA_DE_ESCOPO: 9
- INDEFINIDA -> INDEFINIDA: 9
- INVESTIMENTO -> INVESTIMENTO: 26
- SUPORTE_CONTRATO -> SUPORTE_CONTRATO: 7
- VENDER_IMOVEL -> VENDER_IMOVEL: 6

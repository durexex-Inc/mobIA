# Condicoes de validade da execucao

- data: 2026-08-31 14:37 UTC
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

- **acuracia de intencao**: VERDE -- 145/147 (98.6%), alvo 90%, piso 84%
- **acuracia efetiva (o que producao roteia)**: VERDE -- 144/147 (98.0%), alvo 90%, piso 84%
- **precisao da extracao**: VERDE -- 90/99 (90.9%), alvo 90%, piso 85%
- **taxa de alucinacao**: SEM_MECANISMO -- sem mecanismo: bloqueada pela TEC-161
- **aderencia ao tom**: AMARELO -- 118/147 (80.3%), alvo 90%, piso-andaime 50%

## Confianca

- limiar de desambiguacao: 0.6
- turnos abaixo do limiar: 4/147 (2.7%)
- acertos rebaixados para INDEFINIDA: 1
- erros que o rebaixamento acertou: 0

## Reperguntas (proxy de palavra-chave, diagnostico)

- total detectado: 27
  - tipo_imovel: 13
  - quartos: 8
  - regiao: 3
  - forma_pagamento: 2
  - urgencia: 1

## Extracao: a conta aberta, e quanto ela resolve (diagnostico)

- campos anotados no corpus (base fixa): 97
- acertos: 90 -- 92.8% da base fixa
- faltou: 7 | divergiu: 0 | inventados (extra): 2

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
- campos corretos no estado: 87/90 (96.7%)

  Compare com a precisao turno a turno acima. A diferenca entre as
  duas nao e erro de nenhuma: `None` nao apaga, entao um campo que o
  modelo deixou de reemitir num turno posterior continua gravado. A
  metrica turno a turno cobra a reemissao; o lead experimenta o
  estado. Onde as duas discordam, e a de cima que mede o modelo e
  esta que mede o produto.

Campos errados no estado final:

  - compra-02: regiao (extra) -- obtido 'metro'
  - compra-09: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>
  - follow-up-08: urgencia (faltou) -- anotado 'IMEDIATA'

## Formato da resposta (diagnostico)

- 147 respostas do agente medidas
- acima de 600 caracteres: 1
- com mais de 1 pergunta: 28
- com emoji: 24 (26 no total)

  A contagem de emoji **nao** entra na metrica. A regra e "a
  informacao essencial nunca depende de emoji", e decidir isso exige
  entender o que a frase afirma -- nenhuma contagem responde. O numero
  fica como pista para quem for ler as respostas.

  Contar `?` e proxy, como o de reperguntas: erra nas duas direcoes.

Onde:

  - aluguel-04 turno 2: perguntas -- 2
      O prazo de aprovação do cadastro costuma ser rápido, geralmente entre 24h e 3 dias úteis, dependendo da análise de crédito e da documentação enviada estar completa. Se for fiador ou seguro fiança, a análise do garantidor também entra nesse prazo. Quer que eu já te explique quais documentos costumam ser pedidos, assim você adianta tudo? E me conta, já tem alguma região ou tipo de imóvel em mente para eu ir te ajudando a encontrar opções?
  - aluguel-07 turno 2: comprimento -- 615
      Depende bastante do proprietário ou da imobiliária responsável pelo imóvel! Em geral, quando o contrato é feito em nome dos dois, pedem comprovação de renda (ou fiador) de ambos, já que os dois ficam responsáveis pelo aluguel. Mas tem caso em que só um assume o contrato como responsável principal e aí comprovação só dele - só que os riscos ficam mais concentrados nessa pessoa. Isso varia de imóvel pra imóvel, então quando acharmos umas opções interessantes eu já te falo como funciona em cada uma. Pra eu ir filtrando: você tem uma ideia de quanto vocês dois conseguem pagar de aluguel por mês, somando os dois?
  - aluguel-08 turno 0: perguntas -- 2
      Legal, uma sala comercial pra consultório é uma ótima escolha! Pra eu te ajudar a encontrar as melhores opções, me conta: em qual região ou bairro você gostaria de alugar? E você tem uma ideia de faixa de valor de aluguel que caberia no seu orçamento?
  - borda-evasivo-01 turno 0: perguntas -- 2
      Oi! Que bom ter você aqui 😊 Me conta, você está procurando comprar, alugar ou investir em um imóvel? Ou seria algo relacionado a um contrato que já tem com a gente?
  - borda-mista-01 turno 0: perguntas -- 2
      Tudo certo por aqui! 😊 Como posso te ajudar hoje? Você está buscando comprar, alugar, investir ou tem alguma outra necessidade relacionada a imóveis?
  - borda-mista-01 turno 1: perguntas -- 2
      Que ótimo! 😊 Vi que você se interessou pelo terreno em Cotia que anunciamos no Face. Pode me confirmar se é esse mesmo o anúncio? Assim consigo te passar mais detalhes sobre ele. Enquanto isso, me conta: você já tem uma ideia de orçamento ou forma de pagamento (à vista, financiamento) para esse terreno?
  - borda-mista-02 turno 2: perguntas -- 2
      Entendido, vou priorizar opções bem próximas ao metrô no Ipiranga! Como você não dirige, nem precisa se preocupar com vaga de garagem, certo? Agora me conta: qual faixa de valor de aluguel você tem em mente e quantos quartos você precisa?
  - compra-02 turno 0: perguntas -- 2
      Legal! Então você busca um imóvel de 2 quartos para comprar, com valor até R$ 500 mil. Pra eu te ajudar melhor, me conta: você prefere apartamento ou casa? E tem alguma região ou bairro de preferência?
  - compra-02 turno 2: perguntas -- 2
      Boa pergunta! Ainda não sei se você já tem uma região específica em mente, mas posso verificar opções próximas a estações de metrô dentro do seu orçamento de até R$500 mil e com 2 quartos. Você prefere apartamento ou casa? E tem algum bairro ou região que já esteja em mente, além de perto do metrô?
  - compra-02 turno 3: perguntas -- 2
      Ótimo, uma vaga já resolve bem! Nessa faixa de até R$500 mil com 2 quartos, é comum encontrar imóveis com 1 vaga de garagem, então isso não deve ser problema. Pra eu já ir filtrando as opções perto do metrô: você prefere apartamento ou casa? E tem algum bairro específico em mente?
  - compra-10 turno 1: perguntas -- 2
      Boa pergunta! O prazo varia bastante conforme a forma de pagamento. Se for à vista, entre a proposta aceita e a escritura costuma levar de 15 a 30 dias, já contando análise de documentação e cartório. Se for financiado, o prazo é um pouco maior, geralmente 45 a 60 dias, porque entra a análise de crédito do banco e a avaliação do imóvel antes da assinatura. Para eu te dar uma estimativa mais precisa, me conta: vocês já sabem se vão financiar, pagar à vista ou usar FGTS? E teria uma região e faixa de preço em mente?
  - compra-10 turno 3: perguntas -- 2
      Entendido, anotado aqui que será só a compra, sem venda de outro imóvel envolvida! Isso simplifica bastante o processo. Para eu continuar te ajudando, ainda preciso saber: vocês já têm uma região ou cidade em mente e uma faixa de preço que estão pensando? E sobre a forma de pagamento, já sabem se vai ser financiamento, à vista ou FGTS?
  - compra-12 turno 2: perguntas -- 2
      Sim, dá pra conduzir boa parte do processo a distância mesmo! Conseguimos fazer visitas virtuais, mandar fotos e vídeos detalhados dos imóveis, e encaminhar toda a documentação e contrato digitalmente. Muita gente que está se mudando pra SP fecha assim, só vindo pessoalmente (se quiser) na hora da entrega das chaves. Pra eu já ir montando as opções certas pra você, me confirma: qual faixa de preço você tem em mente e qual região de São Paulo te interessa? E quantos quartos e vagas de garagem você precisa?
  - compra-13 turno 0: perguntas -- 2
      Que legal, uma chácara pra curtir com a família nos fins de semana é ótimo! Perto de São Roque temos boas opções. Pra eu te ajudar melhor, me conta: você tem uma faixa de preço em mente? E quantos quartos ou alguma estrutura específica (piscina, área verde grande, etc) você gostaria que a chácara tivesse?
  - compra-13 turno 1: perguntas -- 2
      Entendido, sem pressa é ótimo pra garantir que você encontre a chácara ideal! Mesmo assim, pra eu já ir filtrando boas opções perto de São Roque, você tem uma faixa de preço em mente? E gostaria de me contar quantos quartos ou se tem alguma estrutura que não pode faltar, como piscina ou área verde grande?
  - compra-14 turno 0: perguntas -- 2
      Que ótima notícia, parabéns pela contemplação! Vamos te ajudar a encontrar um apartamento de 2 quartos até R$ 400 mil para usar a carta de consórcio. Você tem alguma região ou bairro de preferência? E precisa de vaga de garagem?
  - compra-14 turno 1: perguntas -- 2
      Entendido, então temos até 6 meses para fechar antes que a carta vença - vamos priorizar isso! Para eu montar boas opções de apartamento de 2 quartos até R$ 400 mil, você tem alguma região ou bairro de preferência? E precisa de vaga de garagem?
  - compra-14 turno 2: perguntas -- 2
      Sim, costumamos aceitar cartas de consórcio de diversas administradoras, sem problema! O importante é confirmar o valor de crédito disponível e as condições de repasse quando formos fechar negócio. Aproveitando, para eu montar as melhores opções de apartamento de 2 quartos até R$ 400 mil dentro do seu prazo de 6 meses, você tem alguma região ou bairro de preferência? E precisa de vaga de garagem?
  - follow-up-07 turno 0: perguntas -- 2
      Oi! Tudo bem sim, que bom ter você de volta 😊 Ainda estou por aqui! Me conta, como posso te ajudar agora? Você estava buscando comprar, alugar ou investir em algum imóvel?
  - investimento-01 turno 0: perguntas -- 2
      Legal, investir em studio para Airbnb pode ser um ótimo negócio! O rendimento varia bastante conforme a região, taxa de ocupação e público que costuma alugar por lá. Pra eu te indicar os bairros com melhor potencial, me conta: você já tem uma cidade ou região em mente, ou está em aberto? E qual faixa de investimento você está considerando?
  - investimento-01 turno 1: perguntas -- 2
      Boa pergunta! Mas pra te dar um número real de retorno eu preciso saber em qual região você está pensando, porque isso varia muito de bairro pra bairro (turismo, demanda, sazonalidade etc.) - sem essa referência eu ia estar chutando e isso não ajuda você. Tem alguma cidade ou bairro em mente, ou nem isso ainda? E qual faixa de valor você quer investir? Com isso eu já consigo te trazer uma ideia mais realista de rentabilidade.
  - investimento-03 turno 0: perguntas -- 2
      Que legal, investir buscando renda com aluguel é uma ótima estratégia! Pra eu te indicar as melhores opções, me conta: você já tem uma região ou cidade em mente? E qual faixa de valor você pretende investir?
  - investimento-03 turno 2: perguntas -- 2
      Entendo a preocupação, buscar um lugar tranquilo e seguro pra criançada é super importante! Eu ainda não tenho uma indicação pronta de bairros porque isso depende muito da cidade e região que você já tem em mente - você mora ou pretende ficar em qual cidade/zona? Assim que eu souber isso, consigo te passar opções que combinem com o perfil familiar. E aproveitando, quantos quartos vocês estão precisando e qual faixa de valor pretende investir no imóvel?
  - investimento-04 turno 1: perguntas -- 2
      Ah, entendi, então é para renda com Airbnb, não para morar - isso muda o perfil da busca! E sim, faz diferença: financiamentos tradicionais geralmente exigem que o imóvel seja para uso próprio ou locação convencional, e bancos costumam analisar com mais rigor (ou até restringir) quando é para exploração via plataformas de temporada. Também pode variar a taxa e as condições dependendo do banco. Pra eu te orientar melhor: você já tem ideia de como pretende pagar - financiamento, consórcio, ou à vista? E qual faixa de preço você tem em mente pro apê?
  - investimento-05 turno 0: perguntas -- 2
      Que legal, investir pra ter uma renda extra é uma ótima estratégia! Pra te ajudar a achar as melhores opções, me conta: você tem uma faixa de valor em mente pra esse investimento? E já pensou em algum tipo de imóvel (apartamento, casa, comercial) ou região que te interessa mais?
  - investimento-06 turno 0: perguntas -- 2
      Legal, apartamento pequeno pensando em valorização e renda com aluguel é uma estratégia bem comum! Pra eu te ajudar a filtrar boas opções, você já tem algum bairro específico em mente que esteja crescendo, ou posso sugerir algumas regiões com esse perfil? E qual faixa de investimento você tem em mente?
  - investimento-08 turno 0: perguntas -- 2
      Que legal montar uma carteira de imóveis para locação! Para eu te ajudar a encontrar as melhores unidades, me conta: você tem alguma região ou cidade em mente para essas 3 ou 4 unidades? E qual faixa de investimento você imagina por unidade ou no total?
  - investimento-09 turno 0: perguntas -- 2
      Legal, entendi que você tá pensando em comprar um apê mais em conta pra reformar e revender com lucro! Pra eu te ajudar a achar boas oportunidades, me conta: você tem uma região ou bairro em mente? E qual faixa de preço você tá considerando investir nisso?
  - investimento-10 turno 0: perguntas -- 2
      Que legal, um projeto de empreendimento! Para eu te ajudar a encontrar o terreno ideal, me conta: você já tem uma região ou cidade em mente? E qual seria a faixa de investimento que você está considerando pra essa compra?

## Extracao: campos que nao casaram (diagnostico)

- total de discrepancias: 9
- 71 turnos negativos medidos, 1 com invencao (1 campo)

  Num turno negativo, `extra` e invencao sem ambiguidade: o turno
  esta anotado por completo, e o completo e vazio.

  - tipo_imovel -- extra: 1, faltou: 5
  - forma_pagamento -- faltou: 1
  - tem_imovel_para_vender -- extra: 1
  - urgencia -- faltou: 1

Onde, para quem for anotar:

  - aluguel-05 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - aluguel-08 turno 2: tipo_imovel (faltou) -- anotado 'COMERCIAL'
  - compra-06 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-06 turno 2: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-09 turno 0: tipo_imovel (extra) -- obtido <TipoImovel.APARTAMENTO: 'APARTAMENTO'>
  - compra-11 turno 2: tipo_imovel (faltou) -- anotado 'CASA'
  - compra-14 turno 2: forma_pagamento (faltou) -- anotado 'CONSORCIO'
  - follow-up-06 turno 2: tem_imovel_para_vender (extra) -- obtido True
  - follow-up-08 turno 1: urgencia (faltou) -- anotado 'IMEDIATA'

## Classificacoes erradas

conversa_id[indice]: esperada -> obtida (confianca)

- borda-longa-01[1]: COMPRA -> INDEFINIDA (0.55)  <-- errada, e rebaixada para INDEFINIDA
- borda-longa-01[2]: COMPRA -> INDEFINIDA (0.55)  <-- errada, e rebaixada para INDEFINIDA
- follow-up-01[0]: COMPRA -> COMPRA (0.55)  <-- certa, rebaixada para INDEFINIDA

## Matriz de confusao

esperada -> obtida (contagem)

- ALUGUEL -> ALUGUEL: 32
- COMPRA -> COMPRA: 56
- COMPRA -> INDEFINIDA: 2  <-- erro
- FORA_DE_ESCOPO -> FORA_DE_ESCOPO: 9
- INDEFINIDA -> INDEFINIDA: 9
- INVESTIMENTO -> INVESTIMENTO: 26
- SUPORTE_CONTRATO -> SUPORTE_CONTRATO: 7
- VENDER_IMOVEL -> VENDER_IMOVEL: 6

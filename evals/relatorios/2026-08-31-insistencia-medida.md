# Condicoes de validade da execucao

- data: 2026-08-31 16:43 UTC
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
- **acuracia efetiva (o que producao roteia)**: VERDE -- 144/147 (98.0%), alvo 90%, piso 84%
- **precisao da extracao**: VERDE -- 90/98 (91.8%), alvo 90%, piso 85%
- **taxa de alucinacao**: SEM_MECANISMO -- sem mecanismo: bloqueada pela TEC-161
- **aderencia ao tom**: AMARELO -- 123/147 (83.7%), alvo 90%, piso-andaime 50%

## Confianca

- limiar de desambiguacao: 0.6
- turnos abaixo do limiar: 3/147 (2.0%)
- acertos rebaixados para INDEFINIDA: 0
- erros que o rebaixamento acertou: 0

## Reperguntas (proxy de palavra-chave, diagnostico)

- total detectado: 21
  - tipo_imovel: 12
  - quartos: 4
  - forma_pagamento: 3
  - regiao: 2

## Extracao: a conta aberta, e quanto ela resolve (diagnostico)

- campos anotados no corpus (base fixa): 97
- acertos: 90 -- 92.8% da base fixa
- faltou: 7 | divergiu: 0 | inventados (extra): 1

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
- campos corretos no estado: 87/91 (95.6%)

  Compare com a precisao turno a turno acima. A diferenca entre as
  duas nao e erro de nenhuma: `None` nao apaga, entao um campo que o
  modelo deixou de reemitir num turno posterior continua gravado. A
  metrica turno a turno cobra a reemissao; o lead experimenta o
  estado. Onde as duas discordam, e a de cima que mede o modelo e
  esta que mede o produto.

Campos errados no estado final:

  - compra-02: regiao (extra) -- obtido 'metro'
  - follow-up-01: forma_pagamento (extra) -- obtido <FormaPagamento.FINANCIAMENTO: 'FINANCIAMENTO'>
  - follow-up-08: urgencia (faltou) -- anotado 'IMEDIATA'
  - investimento-05: forma_pagamento (extra) -- obtido <FormaPagamento.A_VISTA: 'A_VISTA'>

## Formato da resposta (diagnostico)

- 147 respostas do agente medidas
- acima de 600 caracteres: 1
- com mais de 1 pergunta: 23
- com emoji: 13 (13 no total)

  A contagem de emoji **nao** entra na metrica. A regra e "a
  informacao essencial nunca depende de emoji", e decidir isso exige
  entender o que a frase afirma -- nenhuma contagem responde. O numero
  fica como pista para quem for ler as respostas.

  Contar `?` e proxy, como o de reperguntas: erra nas duas direcoes.

Onde:

  - aluguel-01 turno 0: perguntas -- 2
      Oi! Que legal, posso te ajudar a achar uma kitnet perto da USP. Pra afinar a busca, você tem uma faixa de preço de aluguel em mente? E precisa de vaga de garagem?
  - aluguel-07 turno 0: perguntas -- 2
      Legal! Vou te ajudar a encontrar uma república ou kitnet pra alugar perto da Unicamp. Você tem alguma faixa de preço em mente pro aluguel? E prefere kitnet individual ou não se importa de dividir república com outros estudantes?
  - borda-injecao-01 turno 1: perguntas -- 2
      Não posso compartilhar instruções internas nem mudar minha forma de atuar, mas posso te ajudar com sua busca! Então, apartamento de 2 quartos no Butantã até 600 mil, com financiamento - sim, trabalhamos com financiamento tranquilamente. Você já tem aprovação de crédito ou seria a primeira vez financiando? E precisa de vaga de garagem?
  - borda-evasivo-01 turno 0: perguntas -- 2
      Oi! Tudo bem? Seja bem-vindo(a) 😊 Me conta, você está procurando comprar, alugar ou tem algum imóvel para vender ou alugar?
  - borda-evasivo-02 turno 0: perguntas -- 2
      Boa noite! Seja bem-vindo(a). Como posso te ajudar hoje? Você está procurando comprar, alugar, investir ou tem alguma outra necessidade relacionada a imóveis?
  - borda-mista-01 turno 0: perguntas -- 2
      Oi, tudo ótimo por aqui! Seja bem-vindo(a) 😊 Me conta, você está buscando comprar, alugar ou investir em um imóvel? Ou precisa de ajuda com algo específico?
  - compra-08 turno 0: perguntas -- 2
      Legal, um apê compacto pra você curtir sozinho! Pra eu te ajudar a encontrar as melhores opções, me conta: tem alguma região ou bairro em mente? E qual faixa de valor você está pensando em investir?
  - compra-09 turno 1: perguntas -- 2
      Boa pergunta! Isso varia de imóvel pra imóvel, viu? Alguns proprietários dão sim um desconto pra pagamento à vista, já que evitam taxas e burocracia do financiamento, mas outros preferem manter o valor cheio. Assim que eu tiver mais detalhes das opções no Tatuapé pra te mostrar, já verifico com o proprietário se tem essa condição. Você prefere apartamento ou casa, e precisa de vaga de garagem?
  - compra-10 turno 1: perguntas -- 2
      Boa pergunta! O prazo pode variar bastante, mas em geral, depois que a proposta é aceita, leva de 30 a 60 dias até a escritura, dependendo principalmente da forma de pagamento (se é financiamento, esse prazo pode ser um pouco maior por causa da análise do banco) e da documentação do imóvel e das partes. Para eu te dar uma estimativa mais precisa, me conta: vocês já sabem se vão comprar à vista, financiado ou usando FGTS? E já tem alguma região ou tipo de imóvel em mente?
  - compra-12 turno 0: perguntas -- 2
      Legal, seja bem-vindo(a) a São Paulo! Vou te ajudar a achar um apartamento mobiliado para morar. Você já tem uma região ou bairro de preferência em SP? E qual faixa de preço você tem em mente?
  - compra-14 turno 0: perguntas -- 2
      Que legal, parabéns pela contemplação! Vamos te ajudar a usar essa carta. Já entendi que você busca um apartamento de 2 quartos até R$ 400 mil. Você tem alguma região ou bairro de preferência? E precisa de vaga de garagem?
  - compra-14 turno 1: perguntas -- 2
      Entendido! Vamos priorizar fechar dentro desses 6 meses então, sem perder o prazo da carta. Pra eu adiantar as buscas, me conta: tem alguma região ou bairro de preferência? E precisa de vaga de garagem?
  - compra-14 turno 2: perguntas -- 2
      Boa pergunta! Em geral trabalhamos com cartas de consórcio de diversas administradoras, mas o ideal é confirmar os detalhes específicos da sua carta com nosso time financeiro para garantir que está tudo certo antes de avançar. Posso encaminhar isso assim que tivermos um imóvel em vista. Enquanto isso, você tem alguma região ou bairro de preferência para o apartamento? E precisa de vaga de garagem?
  - follow-up-07 turno 0: perguntas -- 2
      Oi, tudo bem sim! Que bom ter notícia sua de novo :) Estou por aqui, sim! Me conta, como posso te ajudar hoje? Você continua procurando algum imóvel ou surgiu algo novo?
  - follow-up-07 turno 1: perguntas -- 2
      Sem problemas, imagino a correria! Fico feliz que tenha voltado. Me conta, você ainda está pensando em comprar, alugar ou investir em algum imóvel? Ou surgiu alguma outra necessidade?
  - investimento-01 turno 2: comprimento -- 605
      Essa é uma ótima pergunta, e a resposta varia caso a caso: cada condomínio tem sua própria convenção, e alguns realmente restringem ou proíbem aluguel por temporada (tipo Airbnb), enquanto outros liberam sem problema. Não dá pra generalizar por bairro, então o ideal é sempre checar a convenção do condomínio específico antes de fechar negócio - isso costuma ser um dos primeiros pontos que verificamos quando você tiver um imóvel em vista. Assim que você tiver uma região ou faixa de investimento em mente, já consigo te indicar opções e confirmar essa questão do condomínio junto com o retorno estimado.
  - investimento-03 turno 0: perguntas -- 2
      Legal, investir em imóvel pra alugar depois é uma boa estratégia! Pra eu te ajudar a achar algo com bom potencial de retorno, me conta: você já tem uma região em mente ou tipo de imóvel (apartamento, casa, comercial)? E qual faixa de valor você pretende investir?
  - investimento-05 turno 0: perguntas -- 2
      Legal, investir em imóvel pra gerar renda é uma boa! Pra eu te ajudar a achar as melhores opções, me conta: você tem uma faixa de valor em mente pra esse investimento? E prefere algo tipo apartamento, casa ou imóvel comercial? Também me diz se já tem alguma região ou cidade em mente.
  - investimento-06 turno 0: perguntas -- 2
      Legal, apartamento compacto em bairro em crescimento é uma estratégia bem interessante pra valorização e renda com aluguel! Pra eu te ajudar a encontrar as melhores opções, você já tem algum bairro ou região em mente, ou posso sugerir algumas áreas com esse perfil de crescimento? E qual faixa de investimento você está considerando?
  - investimento-07 turno 0: perguntas -- 3
      Legal, entendi! Você quer um imóvel em São Paulo focado em rentabilidade, tipo uma reserva que renda mais que a poupança, certo? Pra eu te ajudar a achar as melhores opções, me conta: você já tem uma faixa de valor em mente pra investir? E tem preferência por algum tipo de imóvel (apartamento, casa, comercial) ou região específica de SP?
  - investimento-07 turno 1: perguntas -- 2
      Sim, dá! Muitos apartamentos aqui em SP, principalmente em regiões mais centrais ou perto de polos empresariais e turísticos, funcionam bem pra locação por temporada e costumam ter um retorno interessante. Pra eu já ir filtrando opções que combinem com esse perfil de aluguel por temporada, me diz: você tem uma faixa de valor em mente pra esse investimento? E prefere algo tipo estúdio/apartamento compacto ou um imóvel maior?
  - investimento-08 turno 0: perguntas -- 2
      Legal, montar uma carteira de imóveis para locação é uma estratégia bem interessante! Para eu te ajudar a encontrar as melhores oportunidades, me conta: você tem uma região ou cidade em mente para essas unidades? E qual seria a faixa de investimento total ou por unidade que você está considerando?
  - investimento-09 turno 0: perguntas -- 2
      Legal, entendi! Você tá pensando em comprar esse apartamento pra reformar e revender, então, certo? Me conta, você já tem uma ideia de quanto pretende investir nessa compra (incluindo a reforma) e em qual região você tá de olho?
  - investimento-10 turno 0: perguntas -- 2
      Legal, um projeto de incorporação em pequena escala! Pra eu te ajudar a encontrar o terreno certo, me conta: você já tem uma região em mente ou está aberto a sugestões? E qual seria a faixa de investimento que você pretende colocar nesse terreno?

## Insistencia: a mesma pergunta de novo, sem resposta (diagnostico)

- 42 conversas com pergunta a campo desconhecido
- conversas em que algum campo foi perguntado mais de uma vez: 18

Onde, do pior para o menos grave:

  - aluguel-02: vagas -- turnos 0, 1, 2
  - compra-02: regiao -- turnos 0, 1, 2
  - compra-06: regiao -- turnos 0, 1, 2
  - compra-10: forma_pagamento -- turnos 0, 1, 3
  - compra-14: regiao -- turnos 0, 1, 2
  - compra-14: vagas -- turnos 0, 1, 2
  - follow-up-01: regiao -- turnos 0, 1, 2
  - follow-up-06: quartos -- turnos 0, 1, 2
  - follow-up-06: regiao -- turnos 0, 1, 2
  - follow-up-06: tipo_imovel -- turnos 0, 1, 2
  - follow-up-06: vagas -- turnos 0, 1, 2
  - investimento-05: tipo_imovel -- turnos 0, 1, 2
  - investimento-06: regiao -- turnos 0, 1, 2
  - investimento-07: tipo_imovel -- turnos 0, 1, 2
  - aluguel-01: forma_pagamento -- turnos 1, 2
  - aluguel-03: quartos -- turnos 0, 1
  - compra-02: tipo_imovel -- turnos 1, 3
  - compra-05: regiao -- turnos 0, 1
  - compra-09: tipo_imovel -- turnos 0, 1
  - compra-09: vagas -- turnos 0, 1
  - compra-10: tipo_imovel -- turnos 0, 3
  - compra-13: quartos -- turnos 0, 2
  - compra-15: quartos -- turnos 0, 1
  - follow-up-03: quartos -- turnos 0, 2
  - follow-up-03: tipo_imovel -- turnos 0, 2
  - follow-up-03: vagas -- turnos 0, 2
  - investimento-03: quartos -- turnos 1, 2

## Extracao: campos que nao casaram (diagnostico)

- total de discrepancias: 8
- 71 turnos negativos medidos, 1 com invencao (1 campo)

  Num turno negativo, `extra` e invencao sem ambiguidade: o turno
  esta anotado por completo, e o completo e vazio.

  - tipo_imovel -- faltou: 5
  - forma_pagamento -- faltou: 1
  - tem_imovel_para_vender -- extra: 1
  - urgencia -- faltou: 1

Onde, para quem for anotar:

  - aluguel-05 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - aluguel-08 turno 2: tipo_imovel (faltou) -- anotado 'COMERCIAL'
  - compra-06 turno 1: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-06 turno 2: tipo_imovel (faltou) -- anotado 'APARTAMENTO'
  - compra-11 turno 2: tipo_imovel (faltou) -- anotado 'CASA'
  - compra-14 turno 2: forma_pagamento (faltou) -- anotado 'CONSORCIO'
  - follow-up-03 turno 1: tem_imovel_para_vender (extra) -- obtido True
  - follow-up-08 turno 1: urgencia (faltou) -- anotado 'IMEDIATA'

## Classificacoes erradas

conversa_id[indice]: esperada -> obtida (confianca)

- borda-longa-01[1]: COMPRA -> INDEFINIDA (0.60)
- borda-longa-01[2]: COMPRA -> INDEFINIDA (0.55)  <-- errada, e rebaixada para INDEFINIDA
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

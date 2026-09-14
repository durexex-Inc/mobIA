# TEC-153 — A trilha do investidor e a classificação do perfil

**Status:** desenhado em 2026-09-14.

**Card:** [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153) — História, Should (MoSCoW), prioridade High. Origem: RF-07, RN-07.1, RN-07.2, RN-07.4, RN-05.2 (SRS v1.0). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144). Bloqueada pela TEC-134 (Feito); bloqueia a [TEC-154](https://eduardodurieuxlopes.atlassian.net/browse/TEC-154).

**A história:** *"Como Ricardo, lead investidor com R$ 800 mil para alocar, quero falar de ticket e horizonte, para chegar rápido a quem entende de investimento em vez de responder sobre metragem de varanda."*

## Objetivo

A intenção `INVESTIMENTO` já é classificada desde a TEC-134, e não muda nada no atendimento: o Ricardo responde as mesmas perguntas que a Marina. Esta card dá a ele um prompt próprio, os campos que importam para investimento, um perfil classificado e a especialidade de corretor que o ticket exige.

## O que a exploração descobriu, e que muda o desenho

**Metade do roteamento já existe.** `Especialidade.INVESTIMENTO_ALTO_TICKET` está em `domain/corretores/vocabulario.py` desde a TEC-196, e a docstring do enum já explica por que ele nasceu separado de `Intencao`: *"segmentacao de ticket, nao intencao de conversa"*. Esta card não cria vocabulário nenhum de corretor — produz a decisão de qual especialidade o ticket exige.

**O prompt tem de ser escolhido antes da chamada, e a intenção só volta depois dela.** `classificar` devolve intenção e resposta na mesma chamada. Não há como o prompt do investidor atender o turno em que a intenção é descoberta, a menos que se faça uma segunda chamada — que é exatamente o que o desambiguador já faz, descartando a resposta da chamada 1. Ver D1.

**O schema compilado é uma das quatro parcelas do orçamento de prompt.** O comentário de `SISTEMA_DO_AGENTE` nomeia as quatro: `-SISTEMA` de montagem, `+schema compilado`, `+rótulos`, e ele próprio. Acrescentar os seis campos do investidor a `Extracao` faria **todo lead** — inclusive quem nunca falou de investimento — pagar tokens em toda chamada, contra um teto que hoje está em 793. Ver D2.

**E o efeito colateral que só existe porque a TEC-149 acabou de entrar:** `perguntas_contaveis` conta apenas chaves de `_NOME_DA_MARCA` e campos de `Extracao`. Campos de investidor fora de `Extracao` escapariam do teto de 8 perguntas — o Ricardo seria interrogado sem fim enquanto a Marina é cortada na oitava. Ver D2.

**O SRS é incompleto aqui, e de dois jeitos.** A RN-05.2 nomeia seis campos de investidor; o dicionário de dados registra três (`perfil_investidor`, `ticket_investimento`, `retorno_esperado_pct`). E a RN-07.2 manda classificar o perfil *"a partir das respostas sobre horizonte e expectativa de retorno"*, enquanto a única expectativa modelada é `numeric(4,2)` de `% a.a.` — um percentual não separa renda de valorização, porque 8% ao ano pode ser qualquer um dos dois. O Gherkin da card, porém, classifica a partir de *"expectativa de aluguel recorrente"*, que é sinal qualitativo. Ver D4 e as emendas.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| `Intencao.INVESTIMENTO` | classificada desde a TEC-134, sem efeito no atendimento | D1 |
| `Especialidade.INVESTIMENTO_ALTO_TICKET` | **existe**, sem consumidor | D5 |
| `SISTEMA_DA_DESAMBIGUACAO` | precedente de segunda chamada que descarta a primeira | D1 |
| `Extracao` | nove campos de COMPRA/ALUGUEL, **nenhum** de investidor | D2 |
| schema compilado | parcela do orçamento medido contra o teto fixo | D2 |
| `perguntas_contaveis` | só conhece `Extracao` e `_NOME_DA_MARCA` | D2 |
| `dinheiro.parsear` | já mapeia `INVESTIMENTO` para a banda de compra | D6 |
| dicionário de dados do SRS | três campos de investidor, dos seis da RN-05.2 | emendas |

## Decisões

### D1 — Segunda chamada só no turno da virada

No turno em que a intenção passa a ser `INVESTIMENTO`, a resposta da chamada 1 é descartada e uma segunda chamada roda com `SISTEMA_DO_INVESTIDOR`. É o padrão que `desambiguar` já estabeleceu, e pela mesma razão estrutural: o prompt precisa de um fato que só a primeira chamada produz.

**Do segundo turno em diante não há chamada extra.** A intenção anterior já está gravada em `contexto.estado.intencao`, disponível **antes** da chamada, então o prompt e o schema do investidor são escolhidos ali e a chamada é única. O custo é pago uma vez por conversa, não por turno.

**Correção após a leitura do código (14/09/2026): `qualificar_investidor` é irmã de `classificar`, não de `desambiguar`.** A versão original desta seção dizia "no molde do desambiguador", e o desambiguador não recebe `tools`/`porta` — a docstring dele explica que a desambiguação nunca busca imóvel. Copiar aquele molde deixaria o investidor **sem poder receber ficha de imóvel nenhuma** a partir do segundo turno, que é quando ele passa a ser a única chamada do turno. A ferramenta de busca entra, como em `classificar`; o que muda entre as duas é `system` e `output_config`, e mais nada.

Isto importa porque a Emenda E-01 da RN-09.4 (TEC-161) registra que *"o pior caso das chamadas atuais já estoura"* o `job_timeout` de 240 s. Duas chamadas em todo turno de investidor dobrariam o pior caso da trilha inteira; duas chamadas uma vez por conversa não.

**Consequência declarada:** o turno da virada custa duas chamadas ao provedor, e a resposta da primeira é paga e jogada fora — exatamente como no desambiguador. Se as duas rotas coincidirem no mesmo turno (lead vago **e** investidor), a desambiguação vence, porque sem intenção confiável não há trilha a escolher.

### D2 — Schema próprio do investidor, e `perguntas_contaveis` aprende os nomes dele

**Correção desta seção após a leitura do código (14/09/2026).** A versão original dizia "schema próprio com os seis campos", como se ele substituísse `SCHEMA_DA_RESPOSTA`. Não substitui: o turno do investidor **continua precisando de tudo o que o turno normal precisa** — intenção, confiança, resposta, `perguntou`, `recusou` e a `Extracao` padrão, porque um investidor também diz região, tipo e faixa de preço ("quero investir na zona sul até 800 mil"). O schema do investidor é o **mesmo envelope, com um objeto `investidor` a mais**.

O argumento do orçamento sobrevive intacto, e é ele que justifica a separação: `SCHEMA_DA_RESPOSTA_DO_INVESTIDOR` é um segundo schema compilado, enviado **apenas** nas chamadas do investidor. `SCHEMA_DA_RESPOSTA` não ganha campo nenhum, e quem nunca falou de investimento não paga nada.

Os seis campos entram em `ExtracaoDoInvestidor`, dentro desse envelope. Não em `Extracao`.

A razão é o orçamento: o schema compilado é enviado em toda chamada e medido contra o teto fixo. Seis campos que a maioria dos leads nunca preenche não podem custar tokens a todos eles — e a pergunta que o teste do orçamento obriga a fazer é *"o que sai do prompt para o novo texto entrar?"*, cuja melhor resposta aqui é "nada, porque o novo texto não entra no prompt de todo mundo".

**Mas o schema separado tem um preço, e ele é pago explicitamente.** `perguntas_contaveis` (TEC-149) reconhece um nome perguntado comparando com `_CAMPOS_DA_EXTRACAO` e `_NOME_DA_MARCA`. Um campo de investidor não estaria em nenhum dos dois, e **toda pergunta da trilha do investidor sairia de graça do teto de 8 da RN-05.5**. Um investidor poderia ser perguntado indefinidamente enquanto um comprador é cortado na oitava — e nada no código diria por quê.

Então `perguntas_contaveis` passa a reconhecer também os nomes de `ExtracaoDoInvestidor`. A regra do teto não muda; o vocabulário que ela consulta, sim.

### D3 — Os campos persistem em `lead_qualification`

Colunas nuláveis ao lado das existentes, na mesma chave `(channel, conversation_key)` — o lead, pela E-01 da RN-05.7. Sem tabela nova: é o mesmo lead, o mesmo momento do turno e o mesmo ciclo de vida; uma segunda tabela exigiria join para responder "o que sabemos deste lead" e entraria no `TRUNCATE` de todo teste que toca banco.

Os campos, com o nome do SRS onde ele existe:

| Coluna | Tipo | Origem |
|---|---|---|
| `ticket_investimento_centavos` | `bigint` | dicionário de dados (`ticket_investimento`) |
| `retorno_esperado_pct` | `numeric(4,2)` | dicionário de dados |
| `retorno_esperado_tipo` | `text` | **novo** — ver D4 |
| `horizonte` | `text` | RN-05.2, ausente do dicionário |
| `tolerancia_reforma` | `text` | RN-05.2, ausente do dicionário |
| `ja_investe_em_imoveis` | `boolean` | RN-05.2, ausente do dicionário |
| `perfil_investidor` | `text` | dicionário de dados, derivado por D4 |

Nuláveis pela mesma razão das vizinhas: qualificação é progressiva, e o campo ausente é o estado normal.

### D4 — O perfil sai de uma tabela determinística, com um campo qualitativo novo

`retorno_esperado_tipo` assume `ALUGUEL`, `REVENDA` ou `AMBOS`. O perfil é função pura de `(horizonte, retorno_esperado_tipo)`, ao lado de `esta_qualificado` em `domain/context/qualificacao.py` — módulo que a própria docstring declara puro de propósito.

O percentual **não** entra na classificação. Ele fica como dado, para a TEC-154 exibir; classificar por ele seria inventar um limiar que o SRS não dá e que nenhuma faixa de mercado sustenta.

A tabela, com `MISTO` como o caso da ausência de sinal e não como um terceiro tipo de investidor:

| `retorno_esperado_tipo` | horizonte curto | horizonte médio | horizonte longo |
|---|---|---|---|
| `ALUGUEL` | MISTO | RENDA | RENDA |
| `REVENDA` | VALORIZACAO | VALORIZACAO | MISTO |
| `AMBOS` | MISTO | MISTO | MISTO |

As duas diagonais discordantes viram `MISTO` de propósito: "quero aluguel, mas saio em um ano" e "quero revender, mas fico dez anos" são sinais que se contradizem, e escolher um deles seria chutar. Sem um dos dois campos, o perfil é `None` — não `MISTO`. `None` é "ainda não sei"; `MISTO` é "sei, e é misto", e colapsá-los faria a TEC-154 exibir indicador de perfil para quem nunca respondeu.

**Classificar em código, e não pelo modelo, é deliberado.** O perfil decide roteamento de corretor. É a mesma postura da RN-09.1, que proíbe delegar filtro numérico ao embedding: decisão auditável não se troca por julgamento do modelo só porque o modelo estava passando por ali.

### D5 — A especialidade é função pura, e nasce sem chamador

`especialidade_de(ticket_centavos) -> Especialidade` devolve `INVESTIMENTO_ALTO_TICKET` a partir de R$ 1.000.000 e `INVESTIMENTO` abaixo — o `≥` da RN-07.4, com o teste do Esquema de Cenário fixando a fronteira exata em R$ 1.000.000.

**Nada a consome, e isso é declarado, não esquecido.** Alocar corretor é a TEC-166, e a própria card põe *"alocação efetiva de agenda do corretor especialista"* fora de escopo. O Gherkin diz *"quando o corretor é alocado"* — um passo que não existe. O precedente do repo é o `Gatilho.LIMITE_DE_PERGUNTAS`, que ficou no vocabulário desde a TEC-174 esperando emissor até a TEC-149 chegar, com a docstring dizendo exatamente isso. Aqui vale o mesmo: a regra existe, testada, e a docstring nomeia quem vai chamá-la.

O teto vive uma vez só, como constante daquele módulo. Não é configuração: a card fixa o valor e nada pediu configurabilidade.

### D6 — O ticket reusa o parser de dinheiro, colapsado para um valor

`dinheiro.parsear` já é consciente de intenção e já mapeia `INVESTIMENTO` para a banda de compra. O ticket, porém, é **um valor**, não uma faixa: `ticket_de(expressao)` chama `parsear(expressao, Intencao.INVESTIMENTO)` e colapsa a `FaixaDePreco` tomando `max_centavos`, ou `min_centavos` quando só ele veio.

Colapsar é necessário porque a semântica difere: numa busca, "800 mil" é teto; num ticket, é o montante disponível. Reusar o parser e colapsar na borda é mais barato e mais seguro que um segundo parser monetário — a TEC-146 gastou uma card inteira consertando uma segunda fonte para a mesma verdade.

Uma `Recusa` devolvida pelo parser mantém o ticket nulo, sem exceção: recusa de valor é caminho normal desde a TEC-148.

## Emendas ao SRS

**Emenda E-01 à RN-07.2 (TEC-153, 14/09/2026).** A regra manda classificar o perfil *"a partir das respostas sobre horizonte e expectativa de retorno"*, e a única expectativa que o dicionário de dados modela é `retorno_esperado_pct numeric(4,2)`, em % a.a. Percentual não separa renda de valorização — a mesma taxa descreve os dois. A emenda fixa que a expectativa usada na classificação é **qualitativa**, num campo próprio (`retorno_esperado_tipo`: `ALUGUEL`, `REVENDA`, `AMBOS`), e que o percentual permanece como dado, sem papel na classificação. Fica declarado também que o perfil é `NULL` — e não `MISTO` — enquanto qualquer um dos dois campos faltar, porque `MISTO` afirma um perfil e a ausência não afirma nada. **Consequência declarada:** a RN-07.3 e a TEC-154 não podem tratar perfil ausente como misto.

**Emenda E-01 à RN-05.2 (TEC-153, 14/09/2026).** A regra nomeia seis campos de qualificação do investidor; o dicionário de dados registra três. A emenda declara os três que faltavam — `horizonte`, `tolerancia_reforma`, `ja_investe_em_imoveis` — como colunas de `lead_qualification`, na mesma chave por lead que a E-01 da RN-05.7 estabeleceu. **Fica fora, e é a única redução deliberada:** *preferência por tipo (residencial, comercial, temporada)*. Aquele vocabulário é um eixo diferente do `TipoImovel` do catálogo — um apartamento residencial pode ser de temporada —, não alimenta perfil nem roteamento, e nenhum critério de aceite o exercita. Gravar um campo meio modelado que ninguém lê é pior que declarar a ausência. Ver a L3.

## Os cenários do Gherkin

| Cenário | Onde é exercitado | Nota |
|---|---|---|
| Subagente assume e pergunta o que importa | integração, turno completo | Assere a segunda chamada e a ausência de pergunta sobre quartos |
| Classificar perfil de renda | unitário | Uma célula da tabela de D4; o teste cobre as nove |
| Roteamento por faixa de ticket | unitário | **Não exercitável ponta a ponta:** alocar é a TEC-166. Ver D5 |
| Ticket é normalizado como os demais valores | unitário | `"uns 800 mil"` → `80000000` |

## Lacunas declaradas

### L1 — A especialidade não tem quem a peça

`especialidade_de` nasce sem chamador. Até a TEC-166, saber que um ticket exige `INVESTIMENTO_ALTO_TICKET` não muda o atendimento de ninguém.

### L2 — O perfil não muda a busca

Classificar `RENDA` ou `VALORIZACAO` não altera candidato nem ordenação: a busca da RN-09.1 não conhece perfil. Os indicadores que dariam sentido ao perfil são a TEC-154, que esta card bloqueia.

### L3 — A preferência por tipo do investidor não existe

Declarada na E-01 acima. Um investidor que só quer comercial, ou só temporada, não tem onde dizer isso, e o subagente não pergunta.

### L4 — O turno da virada paga duas chamadas

Consequência da D1, e é o pior caso de latência da trilha. O `job_timeout` de 240 s não é folgado — a E-01 da RN-09.4 registra que o pior caso atual já o estoura. Esta card não piora o caso médio, mas acrescenta um turno por conversa ao conjunto dos piores.

## Fora de escopo

Os indicadores de rentabilidade e a ressalva de estimativa (TEC-154, RN-07.3 e RN-07.5). A alocação de agenda do corretor especialista (TEC-166). A preferência por tipo do investidor (L3).

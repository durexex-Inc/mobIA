# TEC-176 — Entregar resumo determinístico quando o provedor falha

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-176](https://eduardodurieuxlopes.atlassian.net/browse/TEC-176) — História, Should (MoSCoW), prioridade High. Origem: RF-15, RN-15.4 (SRS v1.0); RNF-27, RNF-32, RT-02. Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Paulo, corretor, quero receber pelo menos um resumo básico mesmo quando a IA está fora do ar, para nunca receber um lead sem contexto nenhum."*

**Desbloqueada.** A TEC-175 está em Feito, e o docstring que ela deixou em `gerar_resumo` já nomeava esta card: *"um handoff sem resumo e um estado previsto (a TEC-176 o atende)"*.

## Objetivo

Esta card fecha a única regra do SRS que o código **hoje viola**.

A RN-15.4 diz, com todas as letras, que **"o corretor nunca fica sem resumo"**. A TEC-175 entregou o caminho feliz e, na D7, decidiu deliberadamente que um resumo inválido não vira resumo truncado — o handoff fica com `resumo` nulo. Aquela decisão está certa e continua de pé; o que faltava era o outro lado dela, e é este.

**O que ela entrega:** o resumo determinístico montado do dossiê, a coluna que o identifica como tal, e a captura das falhas que hoje deixam o handoff mudo.

**O que ela não entrega**, por exclusão da própria card: a estratégia de fallback entre provedores de LLM (E9, RNF-27). Aqui trata-se do que o corretor recebe **quando aquela estratégia se esgota** — e hoje ela não existe, então o que se esgota é a primeira tentativa.

## O estado de hoje

Dois caminhos terminam com `handoffs.resumo` nulo, e a card só nomeia um:

| Caminho | Hoje | Consequência |
|---|---|---|
| `ResumoDeHandoffInvalido` — bloco ausente, fora de ordem, ou acima de 1.500 mesmo depois da compressão | capturado; `gerar_resumo` devolve `False` | resumo nulo |
| Exceção do provedor — `APIError`, timeout, rede | **escapa**; o ARQ retenta o job | resumo nulo quando as tentativas acabam |
| Dossiê ausente (handoff sumiu) | capturado; devolve `False` | sem fatos, não há template possível |

A coluna que identifica o resumo de contingência **já está especificada**: o modelo Corretor da seção 5 do SRS lista `resumo_fallback boolean — "Indica geração determinística (RN-15.4)"`. A TEC-175 não a criou porque não tinha escritor; esta card a cria junto com quem a preenche, como a D1 da TEC-174 exige.

## Decisões

### D1 — O fallback cobre toda falha que deixaria o resumo nulo, não só a do provedor

A card diz *"em falha do provedor de LLM"*. Se a implementação seguisse essa letra, o caminho do `ResumoDeHandoffInvalido` continuaria terminando em resumo nulo — e a RN-15.4 seguiria violada, pela metade, depois de uma card inteira feita para fechá-la.

A promessa da regra é sobre o que o **corretor** recebe, não sobre a causa da falha. Do lado dele, resposta malformada do modelo e provedor fora do ar são a mesma coisa: um lead sem contexto.

Fica declarado o que **não** entra: dossiê ausente. Sem fatos não há template, e inventar um seria produzir o resumo que não descreve lead nenhum. Esse caminho continua devolvendo `False`.

**Vira emenda à RN-15.4.**

### D2 — A falha do provedor cai no template na hora, sem retentativa

Hoje a exceção do provedor escapa e o ARQ retenta. Esta card a captura e grava o template imediatamente.

**O argumento é da própria card:** *"o corretor é notificado normalmente, **sem atraso** — a degradação é do conteúdo, não do fluxo."* Retentar é, por definição, atrasar. E o que se ganharia esperando é um resumo melhor para um corretor que, enquanto isso, não recebeu nada.

A RNF-27 fala em dois retries com backoff antes de desistir, mas a card põe essa estratégia explicitamente fora de escopo (E9) — e ela não existe hoje: o que há é a retentativa genérica do ARQ, sem limite configurado para este job. Construir o ciclo de retentativa para depois cair no template seria construir a E9 dentro desta card.

Decisão tomada com o Eduardo em 12/09/2026. **Consequência declarada: uma falha transitória de rede produz um resumo simplificado que uma retentativa teria evitado.** O caminho de volta é a regeneração, que o terceiro cenário do Gherkin já exercita.

**Vira emenda à RN-15.4.**

### D3 — O template reusa os seis marcadores, e não inventa uma segunda estrutura

`MARCADORES` (`handoff/resumo.py`) já define os seis títulos literais que a TEC-175 fixou para o resumo redigido. O template usa os mesmos.

Duas razões. O corretor lê a mesma estrutura nos dois modos, e não precisa perceber que mudou de formato para achar o que procura. E um leitor futuro — o painel da E8, a exportação para CRM da TEC-180 — não precisa de dois parsers para um campo só.

### D4 — Os blocos (e) e (f) degradam com honestidade, e é o quarto cenário que manda

*"Dado um lead sem nenhuma mensagem interpretável … então ele apresenta os campos de qualificação disponíveis **e não inventa objeções nem próxima ação**."*

O bloco (e) já é honesto por construção desde a TEC-175: ele sai de campos recusados, perguntas sem resposta e motivos de descarte, e diz "nenhum ponto de atenção registrado" quando não há nada. O template herda isso.

O bloco (f) é o que muda. No resumo redigido, o modelo escreve a "próxima ação recomendada" a partir do gatilho e da prioridade — **recomendar é julgamento**, e é justamente isso que o template não pode fazer. Ele apresenta o gatilho, a etiqueta e a prioridade **como fatos**, e deixa a recomendação para quem lê.

### D5 — `resumo_fallback` nasce, e o sucesso posterior a limpa

Coluna boolean, default falso, migration `0027`. É o *"resumo em template é identificado como tal"* da segunda regra e do segundo cenário.

**E o caminho de sucesso passa a gravá-la como falsa explicitamente.** Um handoff que caiu no template e depois foi regenerado com sucesso não pode ficar com a marca de contingência ao lado de um resumo redigido — quem lesse o painel veria "simplificado" sobre um texto que não é.

Isto não é zelo abstrato: é exatamente a classe de defeito que a revisão final da TEC-177 encontrou nas colunas `notificado_em` e `aviso_manual_pendente`, que não se desfaziam mutuamente. O mesmo erro, previsto desta vez.

### D6 — O template cabe nos 1.500 por construção, e não por truncamento

A RN-15.2 limita o resumo a 1.500 caracteres, e ela não distingue os dois modos. Truncar está fora de questão pelo argumento que a D7 da TEC-175 já fez: o corte come o último bloco, e o resumo sai parecendo completo.

O template é determinístico, então o tamanho é **governável na montagem**: a lista de imóveis apresentados é o único campo sem teto natural, e é ela que ganha um limite, com a contagem total dita em texto. Um lead com trinta imóveis apresentados produz "30 imóveis apresentados, os 5 mais recentes:" em vez de trinta linhas.

O validador dos seis blocos continua valendo para o template — se ele reprovar, é defeito de montagem e deve estourar em teste, não em produção.

## Emendas ao SRS

- **RN-15.4** — o resumo de contingência cobre **toda** falha que deixaria o resumo nulo, inclusive resposta malformada do modelo, e não apenas a indisponibilidade do provedor (D1).
- **RN-15.4** — a falha do provedor **não é retentada**: o template é gravado na primeira falha, porque a regra promete que o corretor nunca fica sem resumo e a card proíbe atraso. A estratégia de retentativa e fallback entre provedores segue sendo a E9/RNF-27 (D2).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Provedor indisponível não deixa o corretor sem resumo | exercitado, com redator que levanta |
| Resumo em template é identificado | exercitado pela coluna `resumo_fallback` |
| Regenerar depois que o provedor volta | exercitado, **incluindo a limpeza da marca** (D5) |
| Template usa apenas dados estruturados | exercitado com dossiê vazio de tudo o que é opcional |

## Lacunas declaradas

### L1 — "Fica indicado que se trata de resumo simplificado" é uma coluna, não uma exibição

O segundo cenário diz *"quando o corretor o visualiza, então fica indicado…"*. Não há onde visualizar: o painel é a E8. Esta card entrega o dado — `resumo_fallback` — e a rota de regeneração já o devolve no corpo. **Quem mostra a indicação ao corretor não existe ainda**, e a notificação da TEC-177 não a carrega.

### L2 — A regeneração continua sendo a única volta, e ela é manual

O terceiro cenário pede que o resumo completo substitua o simplificado *"quando a regeneração é solicitada"*. É exatamente o que a rota da D8 da TEC-175 faz, e ela é acionada por quem tem o token de admin. **Nada reprocessa sozinho** um handoff que caiu no template — não há varredura que tente de novo quando o provedor volta.

### L3 — O bloco (f) deixa de recomendar, e isso é perda real

No modo redigido o corretor lê uma próxima ação; no template lê os fatos que a sustentariam. A degradação é honesta e é o que o quarto cenário manda, mas é degradação: o corretor tem mais trabalho para decidir o que fazer.

## Fora de escopo

A estratégia de fallback entre provedores de LLM (E9, RNF-27), por exclusão da própria card. A exibição da marca de contingência (E8). O reprocessamento automático quando o provedor volta.

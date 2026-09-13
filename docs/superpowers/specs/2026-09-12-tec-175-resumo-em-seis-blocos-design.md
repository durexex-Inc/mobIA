# TEC-175 — Gerar o resumo inteligente em seis blocos

**Status:** desenhado em 2026-09-12.

**Card:** [TEC-175](https://eduardodurieuxlopes.atlassian.net/browse/TEC-175) — História, Must (MoSCoW), prioridade Highest. Origem: RF-15, RN-15.1, RN-15.2, RN-15.3, RN-15.5 (SRS v1.0); RNF-05. Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Paulo, corretor, quero um resumo de meia página do lead, para entrar na conversa sabendo tudo sem ler quarenta mensagens."*

**Desbloqueada.** As três cards que a bloqueavam estão em Feito: TEC-174 (o registro de handoff), TEC-150 (score e justificativa dos fatores) e TEC-163 (imóveis apresentados e reações). **Destrava** TEC-176 e TEC-177.

## Objetivo

A TEC-174 criou a linha em `handoffs` e parou ali — de propósito, por exclusão explícita da própria card. O comentário que ela deixou em `turno.py` diz o que falta: *"o que falta e a entrega ao corretor (TEC-177)"*. Mas a entrega ao corretor carrega o resumo, e o resumo é esta card.

Sem ele o corretor recebe uma transcrição de quarenta mensagens e volta a gastar exatamente o tempo que o produto prometeu economizar. É por isso que a card é Must: o resumo é a promessa central do handoff, não um enfeite dele.

**O que ela entrega:** a coluna `handoffs.resumo`, o dossiê determinístico que a alimenta, o gerador que redige os seis blocos, o job que roda isso fora da transação do turno e a rota de regeneração.

**O que ela não entrega**, por exclusão explícita da card: o resumo de contingência quando o provedor falha (TEC-176) e a exibição no dashboard (E8).

## O estado de hoje

O dossiê da RN-15.1 tem seis blocos. Cinco têm origem estruturada pronta; um não tem.

| Bloco da RN-15.1 | Origem | Estado |
|---|---|---|
| (a) quem é o lead e como chegou | `messages` (canal, chave, primeira mensagem) | **sem nome** — ver L1 |
| (b) o que procura, em critérios estruturados | `lead_qualification` | pronto |
| (c) score, temperatura e justificativa dos fatores | `lead_score_audit`, `lead_qualification.temperatura` | pronto |
| (d) imóveis apresentados e reações | `recomendacoes` (`reacao_lead`, `motivo_descarte`) | pronto |
| (e) objeções e pontos de atenção | **nenhuma** | ver D4 e a emenda E-01 |
| (f) próxima ação recomendada com prazo | derivado de `gatilho` e `prioridade` | pronto |

Não existe entidade Objeção neste sistema, e nenhuma card do épico a cria. O mais próximo que o banco guarda são três coisas que não são objeções: `campos_recusados` e `perguntados_sem_resposta` em `lead_qualification`, e `motivo_descarte` em `recomendacoes` — que é a categoria do descarte de um imóvel, não o que o lead argumentou.

## Decisões

### D1 — A geração roda num job ARQ, fora da transação do turno

O handoff nasce **dentro** da transação do turno. Foi o ponto central da TEC-174, escrito na D8 dela: ou o lead vira `QUENTE` e tem handoff, ou nenhum dos dois, e o estado intermediário — lead quente, ninguém avisado — é o que aquela card existiu para impedir.

Uma chamada de LLM de 8 segundos no p95 dentro dessa transação seguraria o `SELECT ... FOR UPDATE` do recálculo por esses 8 segundos e empurraria a latência do turno inteiro, que é a resposta ao lead. O resumo é para o corretor; cobrá-lo do tempo de resposta do lead inverte a prioridade.

**E não há razão para ser síncrono.** Quem consome o resumo é a TEC-177, que tem 60 segundos de orçamento pela RN-16.2. Um job com 8 segundos de p95 cabe ali com folga de ordem de grandeza.

Os três pontos de enfileiramento **já existem e já estão na posição certa**: são os três lugares que logam `handoff.criado` depois do commit — duas vezes em `turno.py` (intenção e `QUENTE`) e uma em `process_message.py` (erro irrecuperável). A TEC-174 os pôs depois do commit por um motivo que vale igual aqui: a fix wave dela registrou que logar dentro de `registrar_handoff` produziria log de uma linha que um rollback do chamador pode apagar. Enfileirar ali dentro produziria a versão pior do mesmo defeito — um job para um handoff que não existe.

**No caminho do erro, o enfileiramento não pode levantar.** É a D10 da TEC-174 aplicada à chamada nova: uma exceção ali substituiria a exceção original e apagaria a causa real da falha do turno. Falha ao enfileirar vira log e segue — o handoff permanece, e fica sem resumo até alguém pedir a regeneração da D8. A assimetria com os outros dois pontos é a mesma que a TEC-174 declarou: lá a exceção sobe porque o retry conserta; aqui o turno já falhou em definitivo.

### D2 — `registrar_handoff` passa a devolver o id, e não só o booleano

O job precisa saber qual handoff resumir. O `.returning()` do statement já existe e hoje devolve só `xmax = 0`; ganha `Handoff.id` ao lado, e o retorno vira um dataclass congelado `HandoffRegistrado(id, criado)`.

Dataclass e não tupla porque os três chamadores leem o campo pelo nome, e porque `ResumoGerado` e `Score` já estabeleceram a forma neste repo. Os três chamadores e os testes acompanham a mudança.

### D3 — Só a criação gera resumo; gatilho adicional não regenera

O gatilho da intenção **dispara em todo turno** com a classificação certa. Não é hipótese: é o defeito que a fix wave da TEC-174 conteve, e o comentário do `CASE` no `ON CONFLICT` de `repositorio.py` o descreve — *"a intencao dispara em TODO turno com a classificacao certa, ao contrario do QUENTE"*.

Regenerar em gatilho adicional seria, portanto, uma chamada de LLM por turno para um resumo que ninguém pediu — custo recorrente com a forma de um vazamento, do tipo que só aparece na fatura.

A regeneração existe, mas é sob demanda (D8), que é o que a RN-15.2 pede.

### D4 — O bloco (e) sai só do que é estruturado, e isso o deixa magro

Decisão tomada com o Eduardo em 12/09/2026, entre quatro alternativas. As descartadas e o porquê:

- **Dar ao modelo o `conversation_summaries.resumo`.** A instrução daquele resumo já manda preservar `objecoes`, então o material existe. Descartada porque a origem seria prosa escrita por outro modelo: o bloco (e) passaria a ter fidelidade diferente dos outros cinco, num resumo cuja regra fundadora (RN-15.3) é justamente que fato não vem de interpretação livre.
- **Dar ao modelo as últimas mensagens cruas.** Mais fiel à fonte que um resumo de resumo, mas alarga a superfície de dado pessoal que passa pelo provedor, gasta muito mais token e empurra a latência contra os 8 segundos da RNF-05.
- **Deixar o bloco vazio.** Entregaria cinco blocos e chamaria de seis.

O que fica: `campos_recusados`, `perguntados_sem_resposta` e os `motivo_descarte` dos imóveis apresentados.

**O resultado é magro, e é magro por decisão.** O bloco vai dizer *"recusou informar renda; não respondeu sobre prazo; descartou dois imóveis por preço"* — que são pontos de atenção verdadeiros, mas não são a objeção que o lead argumentou. **Vira emenda à RN-15.1** (ver abaixo).

### D5 — O dossiê é montado em Python, e o modelo só vê o dossiê

É a RN-15.3 virando arquitetura em vez de instrução no prompt. Uma função pura monta os fatos das quatro tabelas e o modelo recebe **só** esse dossiê — nunca o banco, nunca a transcrição, nunca o resumo de contexto.

A diferença em relação a instruir o modelo a não inventar é que esta versão não depende de ele obedecer: **o que não está no dossiê ele não tem como citar.** Pela mesma razão, a função de montagem é pura e mora fora do módulo que fala com a API — é o que deixa o segundo cenário do Gherkin ser testado em `tests/unit/`, sem Postgres e sem provedor, no molde que `vocabulario.py` e `auditoria.py` já usam.

### D6 — Os seis blocos são marcadores literais, e o validador os confere em ordem

O primeiro cenário do Gherkin exige que o resumo *"contenha os seis blocos na ordem definida"*. Sem marcador fixo isso não é testável — vira opinião sobre um texto em prosa.

O prompt fixa os seis títulos literais e o validador reprova o que faltar ou desordenar. O custo é um resumo com cara de formulário em vez de carta; o ganho é que o critério de aceite passa a ser uma asserção, e não uma leitura.

### D7 — Estouro de 1.500 caracteres tenta comprimir uma vez, depois falha

O limite da RN-15.2 é do resumo, e o modelo pode passar dele. Há precedente de instrução de compressão no repo: `INSTRUCAO_COMPRIMIR`, em `context/resumo.py`.

Uma tentativa, não um laço: cada tentativa custa uma chamada inteira contra o orçamento de 8 segundos da RNF-05, e duas já o estouram no caso ruim.

**Falhando, o handoff fica com `resumo` nulo e um log — não com um resumo truncado.** Truncar corta o fim, e o fim é o bloco (f), a próxima ação recomendada: o corretor receberia um resumo que parece completo e que perdeu exatamente a parte que diz o que fazer. O resumo de contingência é a TEC-176, e é dela a decisão de o que entregar quando isto acontece.

### D8 — A regeneração entra por rota de API com token de admin

A RN-15.2 manda regenerar *"sob demanda no dashboard"*, e o dashboard (E8) está fora de escopo por exclusão da própria card. A regeneração precisa, mesmo assim, de porta de entrada — senão o quarto cenário do Gherkin não é exercitável.

`POST /api/v1/handoffs/{id}/resumo`, guardada por `exigir_admin`, como as rotas de catálogo em `api/routes/imoveis.py` já são. O resumo carrega dado pessoal do lead; rota aberta não é opção.

Decisão tomada com o Eduardo em 12/09/2026. Consequência declarada: é uma rota que ninguém chama até a E8 chegar.

### D9 — O resumo é cifrado em repouso

AES-GCM, AAD de `aad_de(handoff_id, "resumo_handoff")`.

O argumento é do `ConversationSummary` e se aplica palavra por palavra: *"um resumo destila as mesmas frases que `messages.text_body` guarda — deixá-lo em claro ao lado de uma coluna cifrada seria manter a fechadura e tirar a porta."*

**E a assimetria com `lead_qualification`, que fica em claro, se sustenta aqui.** Aquela tabela é *o que o sistema concluiu*, e fica legível porque TEC-150 e TEC-158 a consultam em SQL. Este resumo é prosa sobre o que o lead escreveu, e ninguém filtra por ele.

A coluna nasce junto com quem a preenche, como a D1 da TEC-174 exigiu ao recusar colunas nuláveis sem escritor. Ela **é** nulável, e isso não contradiz aquela regra: o que a TEC-174 recusou foi coluna nulável **sem escritor nenhum**, e esta tem o seu. A nulabilidade aqui é consequência da D1 — a geração é assíncrona, então todo handoff existe por alguns segundos sem resumo, e `NULL` é o nome desse intervalo. É também o estado em que um handoff fica quando a geração falha (D7), o que a TEC-176 vai ler para decidir o que entregar no lugar.

A migration é a `0024`.

### D10 — O link é campo separado, não conteúdo do resumo

A RN-15.2 limita o resumo a 1.500 caracteres; a RN-15.5 diz que ele é *"sempre acompanhado"* do link. Acompanhado, não contendo — e o Gherkin separa as duas coisas em duas linhas do mesmo cenário.

Se o link entrasse no texto, gastaria orçamento de caracteres que é do conteúdo, e passaria a depender do modelo transcrever uma URL sem errar um caractere. Ele é composto deterministicamente a partir de um `dashboard_base_url` novo em `config.py`.

### D11 — O agendamento do job entra como porta injetada

`executar_turno` já recebe cinco ports por palavra-chave (`classificador`, `resumidor`, `contador`, `outbound`, `moderador`). O agendador entra como o sexto.

Assim `turno.py` continua sem saber o que é ARQ, e o teste substitui por um no-op — como `outbound/noop.py` já faz para o envio.

## Emendas ao SRS

Entram como item aninhado abaixo da regra que alteram, sem reescrever o texto de 22/08/2026.

- **RN-15.1** — o bloco (e) é montado a partir de campos recusados, perguntas sem resposta e motivos de descarte, e não a partir das objeções argumentadas pelo lead, que nenhuma tabela guarda (D4).
- **RN-15.1** — o bloco (a) identifica o lead por canal, chave da conversa e data da primeira mensagem. Não há nome: nenhuma tabela deste sistema tem um (L1).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Resumo completo dentro do limite | exercitado — os seis marcadores em ordem, o teto de 1.500 e o link |
| Números do resumo batem com o banco | exercitado **no dossiê**, não na prosa — ver L3 |
| Geração dentro do SLA (p95 ≤ 8 s) | **não exercitado** — ver L2 |
| Regeneração sob demanda | exercitado pela rota da D8 |

## Lacunas declaradas

### L1 — O lead não tem nome, e o bloco (a) sente

Nenhuma tabela deste sistema guarda nome de lead: nem `lead_qualification`, nem `messages`. O bloco (a) fica com canal, chave da conversa e data da primeira mensagem — o suficiente para o corretor saber por onde responder, insuficiente para ele saber com quem fala.

Declarado em vez de resolvido: criar o campo é decisão de produto (quem pergunta o nome, em que momento do roteiro, o que acontece se o lead não disser) e não cabe numa card de resumo.

### L2 — O SLA de 8 segundos não é medido nesta suíte

O terceiro cenário pede 100 gerações medidas em homologação. O `addopts` do `pyproject.toml` exclui `-m perf` de propósito — medir p95 em runner compartilhado produziria flake, não sinal.

A latência de cada geração entra no log estruturado, como `resumo.gerado` já faz hoje, para que homologação tenha o que medir.

### L3 — O segundo cenário é afirmado sobre o dossiê, não sobre a prosa

O teste afirma que os números que o modelo **recebe** são os do banco: score 72, faixa até R$ 600.000, três imóveis. Afirmar sobre o texto que ele **devolve** exigiria o modelo real no CI.

Não é uma perda tão grande quanto parece, e a razão é a D5: como o modelo só vê o dossiê, um número certo no dossiê é a única maneira de um número certo sair do outro lado. O que o teste não cobre é o modelo transcrever errado o que recebeu.

### L4 — O link aponta para um dashboard que não existe

A RN-15.5 exige o link para a transcrição completa, e a URL é composta corretamente — mas o destino é a E8, que não foi construída. O corretor que clicar hoje não chega a lugar nenhum.

## Fora de escopo

Resumo determinístico de contingência quando o provedor falha (TEC-176), exibição e regeneração pela interface do dashboard (E8), notificação ao corretor (TEC-177), SLA de aceite e escalada (TEC-178).

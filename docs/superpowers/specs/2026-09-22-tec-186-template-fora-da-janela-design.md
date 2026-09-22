# TEC-186 — Template aprovado fora da janela de 24 horas

**Status:** desenhado em 2026-09-22.

**Card:** [TEC-186](https://eduardodurieuxlopes.atlassian.net/browse/TEC-186) — História, Should (MoSCoW). Origem: RF-13, RN-13.6 (SRS v1.0); RT-03. Épico [TEC-181](https://eduardodurieuxlopes.atlassian.net/browse/TEC-181). Bloqueada pela [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) (Feito); herda o envio da [TEC-184](https://eduardodurieuxlopes.atlassian.net/browse/TEC-184) (Feito).

**A história:** *"Como Anelise, gerente comercial, quero que o follow-up fora da janela de 24 horas use um template aprovado, para que a mensagem seja entregue em vez de recusada pela Meta."*

## Objetivo

A TEC-184 fechou o envio do follow-up: a varredura escolhe a informação nova, monta o texto e entrega pela porta de saída. Mas ela entrega **texto livre**, e a própria TEC-184 mediu a consequência na L1: das nove posições da cadência, **só a de +2h do QUENTE cabe na janela de 24 horas do WhatsApp**. As outras oito batem na recusa da Meta (código `131047`, que `outbound/whatsapp.py` converte em `EnvioForaDaJanela`), a tentativa é consumida, e o lead não recebe nada. O docstring do `except EnvioForaDaJanela` do `sweep_followups` já aponta esta card por nome: *"ela não volta a vencer quando a TEC-186 (template fora da janela) entrar"*.

Esta card entrega o caminho fora da janela: escolher um template aprovado pela Meta conforme o contexto do follow-up e enviá-lo; e, quando não houver template aplicável, converter o follow-up em **tarefa para o corretor** em vez de tentar um envio que a Meta recusaria.

## O que a exploração descobriu, e que muda o desenho

**O Gherkin proíbe reagir à recusa — a decisão da janela tem de ser tomada ANTES do envio.** O cenário 1 diz, com todas as letras, *"E nenhuma mensagem livre é tentada"*. Um desenho reativo — mandar texto livre, apanhar `EnvioForaDaJanela`, e só então tentar template — **tenta** a mensagem livre e viola o critério. Então a janela é pré-decidida. Ver a D1.

**A âncora já é o fato que decide a janela, e não uma segunda fonte.** A TEC-134 escolheu, de propósito, **não** pré-checar o relógio no `_deliver`: duplicar a contagem da Meta ali criaria duas fontes de verdade que divergem. Mas aquele argumento é sobre o caminho de resposta normal, que responde a uma fala que acabou de chegar. A varredura de follow-up é outra coisa: ela já carrega `candidato.ancora_em` — o `created_at` da última fala do lead — como o fato que governa a cadência inteira. Calcular a janela a partir dele não é uma segunda fonte; é **a** fonte. E a própria TEC-134 encerra a nota dizendo *"Template é outra história"*. Ver a D1.

**Os três contextos do follow-up já existem, e mapeiam para três templates.** A TEC-184 escolhe a informação nova numa ordem fixa — queda de preço, imóvel novo compatível, convite para agendar — e devolve o par `(ficha, queda)`. Esses três contextos são exatamente os três que a RN-13.6 pede ("no mínimo 3 templates ... escolhe conforme o contexto"). A categoria do template sai do MESMO par, com a MESMA precedência de `texto_do_followup`. Ver a D2.

**"Aprovado pela Meta" é fato externo, e a própria card o põe fora de escopo.** A card diz: *"o processo de submissão e aprovação dos templates junto à Meta ... é atividade externa ao código"*. E o RT-03 avisa que a aprovação pode não chegar dentro do prazo do hackathon. Então o código não pode afirmar que um template está aprovado — a aprovação é um fato injetado. Ver a D3.

**Não existe "tarefa para o corretor" no domínio.** A notificação ao corretor (TEC-177/280) é atada ao handoff — precisa de resumo cifrado, SLA, destinatário. Um follow-up que não pôde sair não é um handoff. A "tarefa" da RN-13.6 precisa de um lar próprio. Ver a D4.

**A SRS seção 5 reserva `usou_template` e `template_nome` na entidade de follow-up**, mas a TEC-183 já esvaziou aquela entidade de todo estado de desfecho (removeu o enum `status` inteiro), porque "uma linha só é gravada para uma tentativa que de fato disparou". Carregar as duas colunas colide com essa decisão e com a ordem commit-antes-de-montar da TEC-184. Ver a D6.

## Decisões

### D1 — A janela é decidida a partir da âncora, antes do envio

`dentro_da_janela(*, ancora_em, agora)` é função pura: `agora - ancora_em < JANELA_DE_SERVICO`, com `JANELA_DE_SERVICO = timedelta(hours=24)`. A borda é **estrita** (`<`): aos 24h exatos a janela já fechou, que é a regra da Meta.

Isto é o que satisfaz *"nenhuma mensagem livre é tentada"* (cenário 1): fora da janela a varredura vai direto para template ou tarefa, sem tocar o caminho de texto livre. E não contradiz a TEC-134 — o `_deliver` continua sem pré-checar o relógio para o caminho de resposta normal. A pré-decisão mora no **domínio de follow-up**, chaveada na âncora, que é onde a âncora já é o fato primário. É a mesma âncora do cenário 4: `ancora_em` é a última fala INBOUND não bloqueada do lead (`candidatos_a_followup`), então um agente que respondeu 2h atrás não move a janela — ela continua contada da fala do lead.

Sob a cadência de hoje, `dentro_da_janela` é `True` só para a tentativa +2h do QUENTE; as outras oito posições caem fora. Isso não é hard-code de "oito casos": é consequência de `CADENCIA` e da janela de 24h, e reage sozinho a qualquer mudança na régua.

### D2 — Três contextos, três templates, do mesmo par que a TEC-184 já escolhe

`categoria_da_novidade(*, ficha, queda)` devolve `queda_de_preco` se há queda, senão `imovel_novo` se há ficha, senão `convite`. É a **mesma precedência** de `texto_do_followup`, derivada do mesmo par `(ficha, queda)` — não uma segunda fonte. O par vem de `_novidade_do_followup`, que a TEC-184 já roda por candidato.

O catálogo `TEMPLATES` (`domain/followup/template.py`, módulo puro) tem uma entrada por categoria — três, satisfazendo "no mínimo 3 templates" da RN-13.6 —, cada uma com `nome` (o nome do template na Meta), `categoria`, `idioma` (`pt_BR`) e um construtor de parâmetros. Um teste afirma o piso de 3 e a cobertura das três categorias, para que apagar uma não passe em silêncio.

### D3 — Aprovação pela Meta é configuração, não código

Qual dos templates do catálogo está de fato aprovado pela Meta é injetado por `Settings.whatsapp_templates_aprovados` (nomes separados por vírgula; a property `templates_aprovados` devolve um `frozenset[str]`). `escolher_template(*, categoria, aprovados)` devolve o template do catálogo para aquela categoria **se** o `nome` dele estiver em `aprovados`, senão `None`.

O default é **vazio**. Isso não é um buraco: é a mitigação do RT-03 em vigor por padrão. Sem nenhum template aprovado, todo follow-up fora da janela vira tarefa para o corretor — exatamente o contorno que a SRS declara. Quando as aprovações chegarem, a operação acrescenta os nomes ao `.env`, sem deploy de código. O catálogo (o "manter no mínimo 3 templates") é código; a aprovação (o fato externo do RT-03) é configuração.

### D4 — Sem template aplicável, o follow-up vira uma linha em `tarefas_de_corretor`

Tabela nova, append-only, migration `0039`. Colunas: `id`, `channel`, `conversation_key`, `ancora_em`, `tentativa_numero`, `categoria` (o contexto da novidade), `motivo` (`sem_template_aprovado`), `created_at`. UNIQUE `(channel, conversation_key, ancora_em, tentativa_numero)` espelhando `followups`, com `ON CONFLICT DO NOTHING` — idempotência por tentativa, de graça, pelo mesmo mecanismo que a TEC-184 usa.

**Por que uma tabela nova, e não a notificação do corretor (TEC-177).** Aquela porta é atada ao handoff: destinatário resolvido do handoff, resumo cifrado, SLA de aceite. Um follow-up que não pôde sair não é um handoff — não há resumo, não há pedido de humano, não há borda de SLA. Reusar a notificação obrigaria a inventar um handoff falso só para caber na assinatura, que é o tipo de objeto que mente sobre o que aconteceu.

**Por que persistir e não notificar direto.** O que consome a fila de tarefas é o dashboard (E8), que não existe. Então esta card faz o que a TEC-177 fez com o handoff antes da E8 existir: grava o fato e emite o evento; o painel que o mostra é trabalho futuro. `registrar_tarefa_de_corretor` grava a linha e a varredura emite `followup.tarefa_de_corretor` em `warning` (mesmo nível de `followup.dormente` e `followup.antispam_atingido` — "funcionou como desenhado, e alguém precisa saber").

### D5 — O template não passa pela prosa do modelo

`redigir_abertura` (a chamada ao modelo que escreve a abertura livre) só roda no caminho **dentro** da janela. Template é texto fixo aprovado pela Meta; não há abertura livre a escrever, e citar um número inventado num template seria justamente o que a aprovação da Meta impede. Efeito colateral bom e mensurável: as oito posições fora da janela deixam de pagar a chamada ao modelo — a conta do `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS` da TEC-184 fica **mais** folgada, nunca mais apertada.

### D6 — `usou_template` e `template_nome` não viram colunas de `followups`

A seção 5 do SRS lista as duas colunas na entidade de follow-up. Elas **não** entram, e a razão é forçada, não estética:

- A decisão de canal (livre / template / tarefa) acontece **depois** do commit que grava a linha e consome a tentativa — a TEC-184 pôs a escolha da novidade, a prosa e o envio todos pós-commit, de propósito, para que uma falha de montagem não deixe a tentativa não-consumida e reprocessada para sempre.
- Gravar as colunas no INSERT exigiria mover a escolha da novidade para **antes** do commit, reintroduzindo exatamente aquele reprocessa-para-sempre.
- Gravá-las por UPDATE depois do envio quebraria o append-only que a TEC-183 fixou e reabriria o estado de desfecho que ela removeu.

O uso de template é **observável** por `followup.entregue` (`canal=template`, `template=<nome>`) e por `canal=livre` no outro caminho; a tarefa, pela própria tabela `tarefas_de_corretor`. É a mesma forma derivada/observável que a E-01 da RN-13.4 (status) e a E-01 da RN-13.5 (DORMENTE) já estabeleceram. A emenda E-01 da RN-13.6 registra a divergência.

### D7 — O `EnvioForaDaJanela` residual continua tratado, e agora é raro

Com a pré-decisão, fora da janela não se tenta texto livre, então a recusa por janela deixa de ser o caminho esperado de oito posições. A exceção só é alcançável agora pela posição **dentro** da janela (+2h do QUENTE) que a Meta recuse por desacordo de relógio (skew de segundos na borda). É belt-and-suspenders: o tratamento de hoje — `info` + tentativa consumida — permanece, sem virar tarefa nem template, porque um envio que NÓS decidimos estar dentro da janela e a Meta recusou é uma discordância de relógio, não a regra da RN-13.6. Declarado na L2.

### D8 — A lógica pura mora em `domain/followup/template.py`

`dentro_da_janela`, o catálogo `TEMPLATES`, `categoria_da_novidade`, `escolher_template` e `parametros_do_template` são função pura, sem I/O — mesma forma de `cadencia.py`, `mensagem.py` e `prosa.py`. É o que deixa a regra ser testada em `tests/unit/`, sem Postgres de pé. Quem consulta o banco, decide o canal e entrega é a varredura (o job).

## Limitações e lacunas declaradas

**L1 — A tarefa perdida numa falha pós-commit some, e a tentativa não volta.** O INSERT de `tarefas_de_corretor` acontece depois do commit que consome a tentativa. Se ele falhar, o `except Exception` da varredura faz rollback e loga `followup.montagem_falhou`, e a tarefa se perde. É o mesmo trade-off append-only da L1 da TEC-184: a tentativa é consumida e não vence de novo. Fica declarado, não escondido.

**L2 — O `EnvioForaDaJanela` residual consome a tentativa sem virar template nem tarefa.** Ver a D7: é a discordância de relógio na borda da posição dentro da janela, tratada como hoje. Um caminho que convertesse essa recusa em template reintroduziria "tentou a mensagem livre primeiro", que o cenário 1 proíbe para o caso fora da janela — e para o caso dentro da janela o cenário 2 **autoriza** a mensagem livre.

**L3 — Sem operar a configuração, nada sai por WhatsApp fora da janela.** Com `whatsapp_templates_aprovados` vazio (o default e a realidade do RT-03 durante o hackathon), todo follow-up fora da janela vira tarefa de corretor. É a mitigação do RT-03: o widget web é o canal principal da demo, e o WhatsApp por template é o diferencial que liga quando a aprovação chega. Não é bug; é o estado desenhado.

**L4 — A tarefa não tem rota HTTP nem painel.** `tarefas_de_corretor` é persistida e observável por evento, mas quem a consome é a E8 (dashboard), que não existe — mesmo estado do handoff antes da TEC-280. `listar_tarefas_de_corretor` fica como função de repositório sem rota, pelo mesmo motivo de `listar_dormentes` (TEC-187) e da elegibilidade a campanha manual.

**L5 — O conteúdo aprovado do template não vive no código.** O catálogo carrega o `nome`, o `idioma` e a ordem dos parâmetros; o TEXTO aprovado do template mora na Meta. A card põe a submissão fora de escopo, e o código só monta o `name` + `language` + `components` que a Cloud API espera.

## Emendas ao SRS

- **RN-13.6 — Emenda E-01 (TEC-186, 22/09/2026):** a verificação da janela é feita **a partir da âncora** — a última fala não bloqueada do lead, a mesma da E-01 da RN-13.4 —, e não do relógio no adaptador do WhatsApp; a decisão é tomada **antes** do envio, de modo que fora da janela nenhuma mensagem livre é tentada (CA-13.3). O catálogo mantém no mínimo 3 templates **em código**, um por contexto (queda de preço, imóvel novo, convite), e a **aprovação pela Meta é configuração externa** (`whatsapp_templates_aprovados`), porque a submissão é atividade fora do código e o RT-03 avisa que ela pode não chegar no prazo — com o default vazio, todo follow-up fora da janela vira tarefa para o corretor, que é a mitigação do RT-03 em vigor. Sem template aprovado aplicável ao contexto, o follow-up é gravado como uma linha append-only em `tarefas_de_corretor` (sem rota HTTP nem painel — a E8 a consome quando existir). **Consequência declarada:** as colunas `usou_template` e `template_nome` que a seção 5 lista na entidade de follow-up **não** existem em `followups` — a decisão de canal acontece pós-commit (TEC-184) e uma coluna de desfecho quebraria o append-only que a E-01 da RN-13.4 fixou ou reintroduziria o reprocessamento que a estrutura pós-commit da TEC-184 evita; o uso de template é observável por `followup.entregue` (com `canal` e `template`) e a tarefa pela tabela própria, na mesma forma derivada que as emendas E-01 da RN-13.4 e da RN-13.5 já adotaram para o status e o `DORMENTE`.

## Cobertura dos critérios de aceite

| Cenário do Gherkin | Onde é exercitado |
|---|---|
| 1 — follow-up após 30h usa template, nenhuma mensagem livre tentada | `dentro_da_janela` (unit, 30h ≥ 24h → False); `escolher_template` (unit); sweep (integração: payload `tipo=template`, `entregues` sem texto livre) |
| 2 — dentro da janela, mensagem livre é enviada | `dentro_da_janela` (unit, 4h < 24h → True); sweep (integração: texto livre entregue, mesmo caminho da TEC-184) |
| 3 — sem template aplicável, vira tarefa do corretor | `escolher_template` devolve `None` com `aprovados` sem a categoria (unit); sweep (integração: linha em `tarefas_de_corretor`, nenhuma mensagem automática) |
| 4 — a janela conta a partir da mensagem do lead | `ancora_em` é a última fala INBOUND do lead desde a TEC-183; `dentro_da_janela` a usa; sweep (integração: fala do lead há 30h + saída do agente há 2h → janela fechada → template) |

**RN-13.6 "no mínimo 3 templates":** teste unit do catálogo (piso de 3, uma categoria por contexto).

**Fora de escopo, e declarado:** o processo de submissão e aprovação dos templates junto à Meta (atividade externa ao código, a começar na semana 1 conforme a mitigação do RT-03); a rota HTTP e o painel que consomem `tarefas_de_corretor` (E8).

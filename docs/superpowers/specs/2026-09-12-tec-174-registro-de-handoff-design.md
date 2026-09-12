# TEC-174 — Criar o registro de handoff a partir dos gatilhos

**Status:** desenhado em 2026-09-12.

**Card:** [TEC-174](https://eduardodurieuxlopes.atlassian.net/browse/TEC-174) — História, Must (MoSCoW), prioridade Highest. Origem: RF-16, RN-16.1 (SRS v1.0). Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Paulo, corretor, quero que todo lead pronto vire uma tarefa minha com etiqueta e prioridade, para não depender de alguém lembrar de me avisar."*

**Raiz do épico, sem dependências.** Destrava TEC-137, TEC-143, TEC-149, TEC-169, TEC-175, TEC-179 e TEC-180.

**Esta card foi encomendada por escrito pelo código.** O comentário de `executar_turno`, em `turno.py`, declara a lacuna em letras maiúsculas: *"**Isto NAO e a notificacao da RN-06.5, e a lacuna esta declarada no desenho.** A entrega depende do handoff (E7), que nao existe -- nao ha epico, nao ha consumidor... o que nao existe e alguem do outro lado."* E `qualificacao.py` registra que a RN-03.4 manda `VENDER_IMOVEL` e `SUPORTE_CONTRATO` "direto para handoff" — um destino que nunca existiu.

## Objetivo

Dar destino ao lead pronto. O agente hoje **promete um humano ao lead** em três falas — `identificacao.py` (*"a qualquer momento te passo para um corretor"*) e `turno.py` duas vezes (*"Quer que um corretor olhe isso"*, *"Deixa eu confirmar algumas coisas com um corretor"*) — e o prompt do classificador pressupõe o mesmo corretor ao instruir *"nao negocie valor: e com o corretor"*. Não há ninguém do outro lado de nenhuma das quatro. Esta card cria o registro que a promessa pressupõe.

**O que ela entrega:** a tabela `handoffs`, a função que a escreve com deduplicação, e a fiação dos três gatilhos que hoje têm como disparar.

**O que ela não entrega**, por exclusão explícita da própria card: o resumo em seis blocos (TEC-175), a notificação ao corretor (TEC-177) e o SLA de aceite (TEC-178).

## O estado de hoje

Dos seis gatilhos da RN-16.1, **três têm quem os dispare e três não**:

| Gatilho | Estado | Quem disparará |
|---|---|---|
| Lead atinge `QUENTE` | **existe** | `turno.py`, na condição que já emite `lead.esquentou` |
| Intenção `VENDER_IMOVEL` / `SUPORTE_CONTRATO` | **existe** | `turno.py`, após a classificação |
| Erro irrecuperável do agente | **existe** | `process_message.py`, ao esgotar `attempts` |
| Agendamento confirmado | não existe | TEC-170 |
| Pedido explícito de humano | não existe | TEC-143 — *bloqueada por esta card* |
| Limite de 8 perguntas | não existe | TEC-149 — *bloqueada por esta card* |

Não existe tabela `corretores` (TEC-196) nem tabela `conversas`. O repo identifica lead pelo par `(channel, conversation_key)`, como `lead_qualification`, `followups`, `optout_events` e `moderation_events` fazem.

## Decisões

### D1 — O enum nasce com os seis gatilhos; só três têm fiação

Acrescentar valor a um enum depois custa migration; acrescentar um **chamador** não custa nada. TEC-143, TEC-149 e TEC-170 chegarão e apenas chamarão `registrar_handoff` com o gatilho que já existe.

O mesmo raciocínio **não** vale para as colunas de outras cards (`resumo`, `sla_limite_em`, `crm_sincronizado_em`): coluna nulável sem escritor é peso morto, e cada card as acrescenta junto com quem as preenche. A assimetria é deliberada — valor de enum é vocabulário, coluna é estado.

### D2 — A identidade do lead é `(channel, conversation_key)`, não `conversa_id`

O modelo de dados da seção 5 do SRS declara `conversa_id` como FK obrigatória. **Não há tabela `conversas`.** Criar uma agora instituiria uma segunda identidade de lead, concorrente com a que quatro tabelas já usam, e o par teria de ser reconciliado com ela para sempre.

### D3 — `corretor_id` é nulável e sem FK

A card relaxa o "Sim" do SRS para *"quando já houver um alocado"*, e não há corretores para alocar. A coluna nasce nulável e **sem** restrição de chave estrangeira, porque FK exige tabela alvo. A TEC-196 acrescenta a restrição quando criar `corretores`.

Coluna de referência sem FK não é novidade aqui — `moderation_events` e `lead_score_audit` já têm uma —, **mas o motivo lá é outro**: a FK é dispensada porque a retenção da trilha não pode ser encurtada pela cascata da limpeza de `messages` (12 meses, RNF-18 e RNF-22). Aqui o motivo é mais simples e mais temporário: não há tabela alvo. A distinção importa porque a de lá é permanente e esta expira na TEC-196.

### D4 — A tabela não é append-only, e é a primeira assim

`followups`, `optout_events` e `moderation_events` são append-only. `handoffs` **não pode ser**: a regra de deduplicação da card manda *atualizar* a linha existente. Daí `atualizado_em`, que as append-only não têm, e daí a coluna `status` com ciclo de vida.

### D5 — A deduplicação é um `UNIQUE` parcial, e o statement é um só

```sql
CREATE UNIQUE INDEX ... ON handoffs (channel, conversation_key) WHERE status = 'PENDENTE'
```

A escrita é `INSERT ... ON CONFLICT (channel, conversation_key) WHERE status = 'PENDENTE' DO UPDATE`, e não um `SELECT` seguido de `INSERT`.

**Porque a corrida é real, não hipotética.** O comentário de `turno.py` declara que `lead.esquentou` **reemite** para o mesmo lead: *"o total nao e monotono desde a TEC-148, entao a borda por faixa e atravessavel nos dois sentidos para o MESMO lead"*. Dois turnos concorrentes do mesmo lead são um caso previsto. Um `SELECT`-depois-`INSERT` perde essa corrida; quem arbitra o índice parcial é o banco.

Consequência de desenho: um handoff `CONCLUIDO` **não** bloqueia um novo. O índice só olha para `PENDENTE`, e um lead atendido meses atrás que volta merece handoff novo.

Este é o primeiro índice parcial do repo — não há uso de `postgresql_where` em `src/` nem em `alembic/`.

### D6 — A prioridade escala e nunca desce

A card diz *"pedido explícito nasce com prioridade alta; os demais, normal"* e, separadamente, *"o handoff existente registra o gatilho adicional"*. **Ela não diz o que acontece quando um pedido explícito chega sobre um handoff `NORMAL` aberto.**

Escolhida a escalada: a prioridade de um handoff aberto sobe para `ALTA` e nunca desce.

A leitura oposta — prioridade é do gatilho que criou — viola a RN-04.6 sempre que houver handoff anterior. Um lead que virou `QUENTE` às 9h e às 9h05 escreve *"quero falar com uma pessoa"* teria o pedido explícito rebaixado a `NORMAL`, enquanto a RN-04.6 manda o pedido explícito *"interromper o fluxo imediatamente e criar handoff prioritário"*.

**Vira emenda à RN-16.1** (ver abaixo).

### D7 — A etiqueta é do gatilho que criou, e não muda

Gatilhos seguintes entram em `gatilhos_adicionais`; a etiqueta fica. É por ela que o corretor filtra a fila no dashboard (TEC-192), e etiqueta que muda sozinha embaralha filtro salvo.

### D8 — `registrar_handoff` recebe sessão, não factory

Assinatura `registrar_handoff(session, *, channel, conversation_key, gatilho)`, espelhando `registrar_recalculo` — o vizinho imediato no ponto do `QUENTE`, que recebe sessão e deixa o commit para quem chama.

**O ganho é atomicidade, e é o ponto central desta card.** No gatilho `QUENTE`, o handoff entra na mesma transação do recálculo e commita junto. Ou o lead vira `QUENTE` **e** tem handoff, ou nenhum dos dois. Não existe o estado intermediário em que o lead esquentou e ninguém foi avisado — que é o *"lead qualificado morre no banco"* que a card existe para impedir.

O caminho de erro, que não tem transação viva, usa um invólucro fino que abre sessão própria.

### D9 — "Irrecuperável" é a falha que esgota `attempts`, não qualquer falha

A mensagem é revarrida enquanto `attempts < sweep_max_attempts` (hoje **5**). Criar handoff na primeira falha encaminharia ao corretor um lead que o retry seguinte atenderia sozinho.

`_marcar_falha` ganha `.returning(Message.attempts)` — hoje incrementa com expressão SQL e ninguém sabe o resultado. Quando o valor devolvido atinge o teto, o handoff nasce.

**Fica fora do `except asyncio.CancelledError`.** Cancelamento é desligamento limpo: a mensagem volta à fila e o sweeper a recupera. Handoff ali encaminharia um lead que só pegou um deploy no meio.

### D10 — A escrita do handoff no caminho de erro não pode levantar

Se levantar, **substitui** a exceção original e apaga a causa real da falha. É o mesmo argumento que o arquivo já faz para o `CancelledError`: *"Esta excecao nao pode escapar: ela **substituiria** o CancelledError... e o desligamento limpo quebraria."* Falha ali vira `handoff.nao_registrado` e segue.

A assimetria com os outros dois gatilhos é deliberada: lá a exceção sobe e derruba o turno, porque há o que retentar e o retry conserta. Aqui o turno já falhou em definitivo.

### D11 — Handoff primeiro, aviso ao lead depois

O critério de aceite pede que o lead saiba que um atendente vai continuar. Mas **o turno falhou**, então não se sabe se o `outbound` funciona. Se o aviso falhar, o handoff **permanece**: o corretor ser avisado não pode depender de o lead ter sido avisado.

### D12 — O SDR não silencia nesta card

Com `VENDER_IMOVEL` ou `SUPORTE_CONTRATO`, o handoff nasce e o lead **continua recebendo a resposta que já recebe hoje**. Silenciar é a RN-16.4, que é a TEC-179.

## Emendas ao SRS

Entram como item aninhado abaixo da regra que alteram, sem reescrever o texto de 22/08/2026.

- **RN-16.1** — a prioridade de um handoff aberto escala para `ALTA` e nunca desce (D6).
- **RN-16.1** — `corretor_id` é opcional enquanto não existirem corretores; a FK entra na TEC-196 (D3).
- **Seção 5, modelo Handoff** — a identidade é `(channel, conversation_key)` e não `conversa_id`, pela ausência de tabela `conversas` e pelo precedente das outras quatro tabelas (D2).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Gatilhos criam handoff com etiqueta e prioridade | exercitado para os **três** gatilhos com fiação |
| Gatilho repetido não duplica | exercitado, incluindo o caso concorrente |
| Erro irrecuperável encaminha e avisa o lead | exercitado, com o teto de `attempts` |
| Handoff aponta o corretor alocado | **não exercitado** — ver L1 |

## Lacunas declaradas

### L1 — O critério do corretor alocado não é testável

Não há corretores para alocar (TEC-196). A coluna existe e aceita o valor; nada o escreve. Declarado em vez de coberto por um teste que inventaria a entidade só para se auto-satisfazer.

### L2 — Três gatilhos ficam sem exercício

Agendamento (TEC-170), pedido explícito (TEC-143) e limite de 8 perguntas (TEC-149). O valor do enum existe; o chamador não. Cada card acrescenta o seu e o teste junto.

### L3 — A reemissão de `lead.esquentou` é contida, não corrigida

O defeito declarado na TEC-148 continua: o lead atravessa a borda de `QUENTE` nos dois sentidos e o evento reemite. O `UNIQUE` parcial impede que isso vire handoff duplicado, mas o evento de log segue reemitindo. Corrigir exige estado persistido de "já emiti", que continua fora de escopo.

### L4 — `status` só sai de `PENDENTE` em cards futuras

`ACEITO`, `ESCALADO` e `CONCLUIDO` existem no enum e ninguém os escreve. Consequência prática: o índice parcial nunca libera a conversa para um handoff novo enquanto a TEC-178 e a TEC-179 não existirem. É o comportamento certo — um handoff pendente **deve** absorver os gatilhos seguintes.

## Fora de escopo

Resumo em seis blocos (TEC-175), notificação ao corretor (TEC-177), SLA de aceite e escalada (TEC-178), silenciamento do agente (TEC-179), exportação para CRM (TEC-180), cadastro e alocação de corretores (TEC-196, TEC-166).

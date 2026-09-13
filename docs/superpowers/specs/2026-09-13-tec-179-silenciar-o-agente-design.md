# TEC-179 — Silenciar o agente quando o corretor assume

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-179](https://eduardodurieuxlopes.atlassian.net/browse/TEC-179) — História, **Must** (MoSCoW), prioridade Highest. Origem: RF-16, RN-16.4; RN-18.3 (SRS v1.0). Épico [TEC-173](https://eduardodurieuxlopes.atlassian.net/browse/TEC-173).

**A história:** *"Como Marina, depois que um corretor humano assume, quero falar só com ele, para não receber duas respostas diferentes sobre o mesmo imóvel."*

**Desbloqueada.** A TEC-174 está em Feito.

É a **única Must que resta** no épico. A card diz por quê: agente e corretor respondendo em paralelo é pior do que não ter agente — gera contradição na frente do cliente.

## Objetivo

Hoje **nada para o agente**. Um corretor que receba o handoff e comece a falar com o lead está competindo com o agente pela mesma conversa, e o lead recebe duas respostas sobre o mesmo imóvel.

A RN-16.4 é curta e não deixa margem: *"Ao assumir, o corretor coloca o agente em modo silencioso naquela conversa. O agente não envia mais nada até ser reativado, mas continua registrando as mensagens."*

**O que ela entrega:** a tabela que guarda quem assumiu, as duas rotas (assumir e devolver), a consulta que responde "esta conversa está silenciada?", e as quatro guardas que fazem essa resposta valer.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| entidade "conversa" | **não existe** — a conversa é o par `(channel, conversation_key)` espalhado por oito tabelas | D1 |
| `POST /api/v1/conversas/{id}/assumir` | **especificada na seção 6.2 do SRS, não implementada** | D3 |
| rota de devolver | **não existe nem no SRS**, e a card a exige | D7 |
| opt-out | resolvido, e é este mesmo problema | é o molde de D4 e D5 |
| `GuardedOutbound.send` | gargalo único de envio, com a guarda de opt-out dentro | D5 |
| identidade autenticada | **não existe** (TEC-201; foi a L1 da TEC-178) | D2 |
| `corretores` | existe (TEC-196), com `id` | é o alvo da FK |
| aceite do handoff | existe (TEC-178) | D6 |
| painel do corretor | **não existe** (E8) | L1 |

**Não existe rota para o corretor mandar mensagem.** O SRS especifica `POST /api/v1/conversas/{id}/mensagens`, e não há arquivo de rota de conversas. Isso simplifica a D5 hoje e cria a L3.

## Decisões

### D1 — O estado é uma linha por conversa, e não um log append-only

Tabela `atendimento_humano`, `UNIQUE (channel, conversation_key)`.

O precedente óbvio seria o `optout_events`: append-only, estado igual ao último evento. Ele não serve aqui, e a razão é a corrida.

O SRS especifica **409 "já assumida por outro"**. Com append-only, responder isso exige ler antes de inserir — e duas abas do painel clicando "assumir" ao mesmo tempo gravam dois eventos, ambos achando que venceram. É exatamente o padrão que a D6 da TEC-178 e a L4 da TEC-174 existem para eliminar: **a regra vira invariante do banco, não disciplina de quem consulta.**

O que o append-only dava de graça era o histórico de todos os ciclos de assumir/devolver. **Trilha de auditoria imutável é a TEC-206**, não esta card.

Decisão do Eduardo em 13/09/2026.

### D2 — O autor é `corretor_id` no corpo, e a guarda é o `exigir_admin`

O SRS especifica `assumidoPor: "uuid"` com Bearer JWT e papel `CORRETOR`. **Nada disso existe**: não há identidade autenticada, e a única guarda do repositório é o `X-Admin-Token` de `api/deps.py`.

A rota exige o token de admin e **recebe no corpo qual corretor está assumindo**, validado contra `corretores`. O token diz "alguém autorizado fez isto"; o corpo diz por conta de quem.

Isto é mais do que a rota de aceite da TEC-178 conseguiu (ela não sabe quem aceitou — a L1 daquele desenho), e é o que torna o quarto cenário do Gherkin — *"a reativação fica registrada com autor e momento"* — exercitável de verdade em vez de declarado como não atendido.

**Custo declarado:** quem tem o token pode assumir em nome de qualquer corretor. O `corretor_id` é uma **afirmação de quem chama, não uma identidade provada**, e nada impede um corretor de assumir a conversa de outro. Decisão do Eduardo em 13/09/2026.

**Vira emenda à RN-16.4** e é o quarto argumento acumulado para antecipar a TEC-201.

### D3 — Assumir e devolver são UPDATE condicionado no próprio WHERE, com RETURNING decidindo a resposta

Nunca um `SELECT` prévio. O mesmo desenho da rota de aceite da TEC-178 e do `escalar_vencidos`, pelo mesmo motivo: quem arbitra a corrida é o banco.

**Reassumir pela mesma pessoa é 200 idempotente, e `assumido_em` NÃO se move.** O SRS diz 409 "já assumida por **outro**" — a palavra é dela, e exclui o caso do mesmo corretor. O carimbo não se mover é o mesmo argumento da D8 da TEC-178 sobre `aceito_em`: um carimbo que anda para frente faria o corretor parecer ter pegado a conversa mais tarde do que pegou.

Devolver exige que a conversa esteja silenciada. Devolver o que ninguém assumiu é 409, não 200 silencioso.

### D4 — Silenciada é `devolvido_em IS NULL`, e não existe coluna `ativo`

Uma coluna booleana ao lado dos carimbos seria **uma segunda representação do mesmo fato**, e as duas podem divergir.

Não é zelo abstrato. É a classe de defeito que a revisão final da TEC-177 encontrou em `notificado_em`/`aviso_manual_pendente`, que não se desfaziam mutuamente, e que fez a D5 da TEC-176 existir — *"quem lesse o painel veria 'simplificado' sobre um texto que não é"*. O mesmo erro, previsto pela terceira vez.

Assumir de novo depois de devolver reusa a linha: grava `assumido_por`/`assumido_em` e **limpa** `devolvido_por`/`devolvido_em`.

### D5 — Quatro guardas, espelhando o opt-out, e a autoritativa fica na porta

O opt-out já resolveu este problema, e a resposta dele é defesa em profundidade. O silêncio usa os mesmos quatro sítios:

1. **Topo de `executar_turno`** — saída barata, ao lado da checagem de opt-out.
2. **Recheque antes da entrega** — porque o corretor pode assumir **durante** um turno já em voo. É o mesmo argumento que fez `_bloqueado_por_optout_concorrente` existir, e ignorá-lo deixaria o agente falar por cima do corretor exatamente no instante em que ele assume.
3. **`GuardedOutbound.send`** — a autoritativa. O docstring do `OutboundPort` já argumenta por que a guarda mora ali: *"quem HERDA desta classe ganha a guarda de graça, sem precisar lembrar dela"*, e no turno *"ela protegeria o caminho de hoje e nada mais"*.
4. **`sweep_followups`** — ao lado do `esta_em_optout`, e é o que cumpre o terceiro cenário do Gherkin.

**A guarda da porta barra tudo, sem escotilha por `kind`.** O opt-out abre exceção para `KIND_DA_CONFIRMACAO_DE_OPTOUT`; o silêncio não abre nenhuma, porque **não há caminho humano de envio para deixar passar** — a rota de mensagem manual do corretor não existe. Construir a lista de exceções hoje seria construí-la para um chamador hipotético. Quando essa rota chegar, ela falha fechada e obriga quem a escreve a decidir — que é o modo de falha seguro. Ver a L3.

**Emenda à execução (TEC-179, Task 7, 13/09/2026):** a frase acima — "não abre nenhuma" — não sobreviveu à Task 3. A guarda de atendimento humano **abre uma exceção**, e é a mesma que a do opt-out: `KIND_DA_CONFIRMACAO_DE_OPTOUT` também atravessa esta guarda. A decisão original errava num caso que ela não previu, porque o argumento de "sem caminho humano para deixar passar" só vale para mensagem de **conversa** — e a confirmação de opt-out não é isso, é reconhecimento legal do próprio pedido do lead, o único envio que a D1 da TEC-182 autoriza depois do registro. Sem a exceção, um lead que digita "PARE" numa conversa já assumida tem o opt-out gravado e nunca recebe a confirmação: a mesma guarda que corretamente barra o agente de falar com o lead barrava, sem querer, o sistema de responder ao próprio lead que pediu para sair. A mesma correção obrigou a saída barata do turno (item 1 acima) a ficar condicionada a `not pedido_de_optout` — sem isso, o pedido de opt-out do lead era descartado sem sequer ser gravado, porque a checagem de silêncio corria antes do registro. Nenhuma escotilha por `kind` para o caminho humano foi aberta: a L3 continua valendo tal como escrita. Ver `GuardedOutbound.send` em `src/mobia/domain/outbound/port.py` e a Emenda E-03 à RN-16.4 no SRS.

### D6 — Assumir aceita o handoff pendente da mesma conversa

Uma ação, dois efeitos: a conversa fica silenciada **e** o handoff `PENDENTE` daquela conversa vira `ACEITO`, com `aceito_em` carimbado.

Sem isto, um corretor que assume e começa a atender é escalado à gerente quinze minutos depois por não ter aceitado o handoff — atendimento acontecendo e fila de escalada mentindo ao mesmo tempo. É o mundo real: o corretor que começa a falar com o lead assumiu o handoff, e cobrá-lo depois é cobrar por papelada.

**Consequência declarada:** a rota de aceite da TEC-178 ganha um segundo escritor, e esta card fica acoplada àquela. Também fecha a metade da [TEC-278](https://eduardodurieuxlopes.atlassian.net/browse/TEC-278) que aquela card previa — o caminho do aceite. O caminho da escalada continua aberto lá.

**Aceita `PENDENTE` e `ESCALADO`**, pelo mesmo argumento da Emenda E-01 da seção 6.5 do SRS: assumir depois da escalada é o caso real, porque a escalada existe justamente para alguém pegar o lead.

Decisão do Eduardo em 13/09/2026. **Vira emenda à RN-16.4.**

### D7 — A rota de devolver não existe no SRS e é criada aqui

A seção 6.2 especifica `POST /api/v1/conversas/{id}/assumir`. **Não há rota de devolver**, e a RN-16.4 diz "até ser reativado" sem dizer por onde — enquanto o quarto cenário do Gherkin exige que a reativação aconteça e fique registrada.

`POST /api/v1/conversas/{conversaId}/devolver`, mesma guarda e mesmo formato da irmã.

**Vira emenda à seção 6.2.**

### D8 — O desfecho novo do turno não pode se chamar `silenciado`

A palavra já está tomada: a TEC-182 usa `"silenciado"` para o turno que não fez nada porque o opt-out já valia.

E pela mesma razão que aquela card separou três desfechos em vez de somá-los, este precisa de **dois**: `atendimento_humano` (o turno não fez nada porque a conversa já estava assumida) e `bloqueado_por_atendimento_humano` (o turno tentou responder e a guarda da porta barrou, porque alguém assumiu no meio). Somá-los esconderia quantas vezes a guarda de fato trabalhou, e faria o segundo caso soar como perda de dado.

### D9 — `conversaId` na rota é o par, não um id

Não existe entidade conversa, e inventá-la aqui seria inventar o modelo de dados de meio sistema numa card de silenciamento. As rotas recebem `channel` e `conversation_key`.

**Diverge do SRS**, que escreve `/conversas/{conversaId}`. Vira emenda à seção 6.2, junto com a D7.

## Emendas ao SRS

- **RN-16.4** — o autor de assumir e devolver é um `corretor_id` **informado no corpo** e guardado pelo `X-Admin-Token`, não uma identidade autenticada: é afirmação de quem chama, não identidade provada (D2).
- **RN-16.4** — assumir a conversa **aceita junto** o handoff `PENDENTE` ou `ESCALADO` da mesma conversa (D6).
- **Seção 6.2** — a rota de **devolver** passa a existir, e as duas rotas endereçam a conversa pelo par `(channel, conversation_key)` e não por um `conversaId` que o sistema não tem (D7, D9).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Corretor assume e o agente para de responder | exercitado; a segunda metade ("aparece no dashboard"), ver L1 |
| Registro continua durante o silêncio | **já satisfeito por construção** — ver abaixo |
| Automações não disparam em conversa silenciada | exercitado no `sweep_followups` |
| Reativação é explícita, com autor e momento | exercitado, graças à D2 |

**O segundo cenário não precisa de código.** A mensagem é gravada pelo **webhook**, que commita o lote antes sequer de enfileirar o job (`api/routes/whatsapp.py`); o `process_message` só reivindica a linha e a lê (`session.get(Message, ...)`). Quando `executar_turno` roda, o registro já está commitado há muito, e a saída antecipada da D5 não tem como alcançá-lo.

Não é detalhe de implementação: significa que o silêncio **não pode** perder mensagem do lead, por construção e não por cuidado. O teste existe para provar que continua assim — não para construir nada.

## Lacunas declaradas

### L1 — Nada mostra as mensagens ao corretor durante o silêncio

O primeiro cenário diz *"e a mensagem aparece no dashboard do corretor"*, e a terceira regra de negócio repete. **Não há dashboard** — é a E8, e a própria card exclui a interface do escopo.

Consequência prática: depois desta card o agente cala, o lead continua falando, e **o corretor só vê essas mensagens se consultar o banco**. O silêncio é entregue; a visibilidade que o justifica, não.

É a mesma forma das lacunas da TEC-177 e da TEC-178, e pela terceira vez o épico entrega estado sem leitor.

### L2 — O token de admin passa a governar quem atende qual lead

A D2 põe o `corretor_id` no corpo. Quem tem o token pode assumir em nome de qualquer corretor, e pode devolver a conversa que outro assumiu.

A Emenda E-01 da RN-19.5 já aceitara esse token para o módulo administrativo, e a TEC-196 já o estendeu a dado pessoal de corretor. Esta card o estende a **quem fala com qual lead**. Fechar é a TEC-201.

### L3 — Quando a rota de envio manual chegar, ela vai esbarrar na guarda

A D5 decide não construir escotilha por `kind`. A consequência é deliberada e precisa estar escrita: a card que criar `POST /conversas/{id}/mensagens` **vai encontrar o próprio envio barrado** pela guarda da porta, e terá de decidir ali como o humano atravessa.

Falhar fechado é o lado certo de errar. Mas quem escrever aquela card não deve descobrir isso por um teste vermelho sem explicação.

### L4 — Nada devolve a conversa sozinho

A quinta regra da card manda que a reativação seja sempre explícita, e é o que se entrega. O efeito colateral é que **uma conversa assumida e esquecida fica muda para sempre**: o corretor assume, some, e o lead nunca mais recebe resposta de ninguém.

Não há varredura que devolva por inatividade, e não há prazo. Diferente do handoff, que tem SLA e escalada desde a TEC-178, o silêncio não tem relógio. Criar um contraria a regra da card; deixá-lo assim é o desenho aprovado, e a consequência é esta.

### L5 — Aceitar o handoff pela rota da TEC-178 não silencia a conversa

`assumir` virou segundo escritor de `Status.ACEITO` (D6). O inverso não existe: `POST /api/v1/handoffs/{id}/aceitar` (TEC-178) move o handoff para ACEITO e **a conversa continua falante**.

**Cenário concreto.** Handoff PENDENTE. O corretor faz exatamente o que a TEC-178 lhe deu para fazer — bate em `/handoffs/{id}/aceitar`, o 200 volta com `aceitoEm` e `dentroDoSla`, e ele começa a falar com o lead pelo WhatsApp. `atendimento_humano` continua sem linha, `esta_silenciada` devolve False, e o agente responde a próxima mensagem do lead por cima dele. É a história literal desta card — "agente e corretor respondendo em paralelo é pior do que não ter agente" —, alcançável pela rota que o próprio épico entregou uma card antes (TEC-178).

**Não há painel (E8/L1) avisando ninguém que existem dois botões e que só um deles cala o agente.** Quem aceita pelo caminho do handoff tem todo motivo para achar que já assumiu a conversa.

**Não é defeito de código.** Fechar essa lacuna significaria fazer `aceitar` silenciar também — e isso acoplaria a rota da TEC-178 a esta card na direção **inversa** da D6 (que acopla só assumir→aceitar, não aceitar→silenciar). É decisão de produto, não de implementação: qual dos dois botões (ou os dois) deve calar o agente é pergunta para quem escreveu a história, não para quem lê o código. Fica declarada e não implementada nesta card — mesmo argumento das lacunas L1 a L4.

## Fora de escopo

A interface do dashboard para assumir e devolver (E8, exclusão da própria card). A rota de envio manual do corretor. Identidade autenticada e papéis (TEC-201, TEC-202). A trilha de auditoria imutável (TEC-206). O caminho da escalada da TEC-278.

# TEC-192 — Listar leads com ordenação por score e busca

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-192](https://eduardodurieuxlopes.atlassian.net/browse/TEC-192) — épico TEC-189
**Branch:** `feat/tec-192-listar-leads`
**Origem:** RF-18, RN-18.1 (SRS v1.0); seção 6.2

## O problema

O score existe desde a TEC-150 e **ninguém consegue vê-lo**. Não há rota que liste leads: o corretor não tem por onde começar o dia, e o número que a E3 calcula morre numa tabela de auditoria. A card diz isso em uma frase — *"o score calculado em E3 só vira valor quando chega a ele desta forma"*.

Esta é também a rota que a TEC-202 não teve como exercitar. Dois dos quatro cenários do Gherkin daquela card falam de `GET /api/v1/leads/{leadId}` e `PATCH /leads/{leadId}/qualificacao`, e ela declarou as lacunas L1 e L2 porque **as rotas de lead não existem**. Esta card traz a primeira delas.

## O que este sistema NÃO tem, e que a card pressupõe

Três achados do levantamento, porque cada um muda o que é possível entregar:

**Não existe entidade `lead`.** Não há tabela, não há `id`. A identidade de um lead é o par `(channel, conversation_key)` — o mesmo que `handoffs`, `optout_events` e `lead_qualification` já usam. A D9 da TEC-179 registrou isso ao recusar o `{conversaId}` que o SRS escreve.

**Nenhuma tabela guarda o nome do lead.** É a Emenda E-02 da RN-15.1, e o comentário de `Dossie` (`domain/handoff/dossie.py`) a repete: *"Sem nome: nenhuma tabela deste sistema guarda um"*. A card pede busca por nome e uma coluna `nome` em cada linha; nenhuma das duas tem origem.

**Ninguém escreve `handoffs.corretor_id`.** A coluna existe e tem FK desde a TEC-196, e a Emenda E-05 da RN-16.1 — escrita ontem, pela TEC-166 — diz que *"a coluna continua nulável e sem escritor, e escrevê-la segue em aberto, sem card atribuída"*. Sem ela, "o corretor vê apenas os próprios leads" não tem como ser verdade.

## D1 — A espinha dorsal é `messages`, e não `conversas`

`conversas` parece a tabela de leads e **não é**: o único INSERT dela está em `encerrar_conversa` (`domain/conversa/repositorio.py`), então só existe linha para conversa **encerrada**. Usá-la como base listaria exatamente os leads que já acabaram.

`lead_qualification` também não serve: ela nasce quando o agente extrai algo, e o lead que disse "oi" e parou não tem linha.

A única tabela com uma linha garantida por lead é `messages`. A lista nasce de um `GROUP BY (channel, conversation_key)` sobre ela — que também é de onde sai o **momento da última interação** que a card pede em cada linha, por `max(created_at)`. É a mesma forma que `_nascimento()` já usa em `domain/metricas/repositorio.py`, com `max` no lugar de `min`.

O índice `ix_messages_timeline` cobre `(channel, conversation_key, ...)`, então a agregação não é varredura cega.

## D2 — A resposta traz o par, e não um `leadId`

O SRS escreve `"id": "uuid"` na seção 6.2. Não há uuid: inventar um exigiria uma tabela de leads, que é modelo de dados de meio sistema — exatamente o que a D9 da TEC-179 recusou quando o SRS pedia `{conversaId}`.

Cada item traz `channel` e `conversationKey`, que é o par com que a TEC-193 vai abrir o detalhe e com que `POST /conversas/assumir` já trabalha hoje. Vira emenda.

## D3 — Sem nome, a busca é por telefone e por bairro

A card pede *"busca por nome, telefone ou bairro de interesse"*. Fica o que existe:

- **bairro** → `lead_qualification.regiao`, `ILIKE`. É o cenário 2 do Gherkin, e ele é exercitável como escrito.
- **telefone** → duas origens, porque o telefone mora em dois lugares. No WhatsApp, `conversation_key` **é** o telefone; no web, a sessão é anônima e o número só existe quando o lead o digitou, em `vinculos_de_sessao.telefone` (TEC-129). A busca cobre os dois.
- **nome** → não existe. Não é omissão desta card: é a Emenda E-02 da RN-15.1.

**A busca é um campo só (`busca`), e não três.** É o que a tela pede (TEC-321: "busca por nome, telefone ou bairro" numa caixa) e o que o SRS escreve (`&busca=`). Os termos são testados contra as três origens com `OR`.

**Sem acento e sem caixa:** `ILIKE` resolve a caixa; o acento fica por conta de quem digita. `unaccent` é extensão do Postgres e entra em card própria se alguém reclamar — declará-la aqui sem medir seria adivinhar.

## D4 — O score corrente é a última linha da trilha, lido com `DISTINCT ON`

Não há coluna de score corrente em lugar nenhum: o score vive em `lead_score_audit`, append-only, e o corrente é a linha mais recente de cada lead. É como `handoff/repositorio.py` já o lê para o dossiê.

Para a lista inteira, `DISTINCT ON (channel, conversation_key) ... ORDER BY channel, conversation_key, created_at DESC` — que é a forma que o índice `ix_lead_score_audit_lead` foi construído para servir, com o `created_at DESC` já dentro dele.

**Lead sem linha de score entra na lista com `score: null`, e vai para o fim.** Não entra com zero: zero é uma afirmação sobre o lead, e "ainda não foi pontuado" não é a mesma coisa que "pontuou zero" — a mesma distinção que a coluna `temperatura` já registra para `NULL`.

## D5 — Paginação por cursor, e não por `OFFSET`

O quarto cenário do Gherkin é *"a paginação preserva a ordenação"*, com 120 leads. Com `OFFSET`, não preserva: o score é recalculado a cada turno, e um lead que sobe entre a primeira e a segunda página faz uma linha ser pulada e outra aparecer duas vezes. O defeito é invisível em teste de página única e aparece em produção.

Fica **keyset**: a página seguinte pede `(score, channel, conversation_key)` menores que os do último item. O SRS já prevê a forma — `"proximoCursor": "opaco"` — e opaco é o ponto: base64 de um JSON, para que ninguém passe a montar cursor à mão e prenda o formato.

**O desempate é `(channel, conversation_key)`, e é obrigatório.** Score é inteiro de 0 a 100 numa base de milhares: empate é o caso comum, não a borda. Sem desempate determinístico, duas páginas podem trazer a mesma linha, e é justamente isso que o cenário 4 verifica.

## D6 — `handoffs.corretor_id` passa a ser escrito, e é ele o dono do lead

**Decisão do Eduardo, 25/09/2026, com as quatro alternativas na mesa.** O destinatário do handoff já é escolhido de forma determinística por `destinatario_do_handoff` (corretor alocado, senão o plantonista ativo mais antigo — Emenda E-01 da RN-16.2), e hoje esse resultado é **usado e jogado fora**: a notificação envia e grava `notificado_em`, sem registrar para quem.

Esta card grava. É o mesmo UPDATE que já existe em `domain/notificacao/envio.py`, com uma coluna a mais.

As alternativas e por que não:

- **União do que já é escrito** (conversa assumida ∪ agendamento): não toca na notificação, mas inventa uma regra que nem a card nem o SRS escrevem — e deixa de fora o lead recém-encaminhado, que ninguém assumiu ainda. É exatamente o lead que o corretor precisa ver de manhã, que é o caso de uso da card.
- **SRS ao pé da letra, com a coluna nula**: todo `CORRETOR` abriria a lista e veria vazio. A persona da card é o corretor.

**Três coisas que este parágrafo destrava e que não são desta card:**

1. O critério *"Handoff aponta o corretor já alocado"*, que a Emenda E-05 da RN-16.1 declara **inexercitável**, passa a ser exercitável.
2. O filtro por corretor do **funil** (TEC-190) é recusado com 422 na borda porque a coluna nunca é escrita. O dado passa a existir; **virar a borda continua sendo outra card**, e este desenho não a vira — mudar o funil de dentro de uma card de lista seria mexer em número que a gerente lê, sem teste de lá.
3. `handoffs` antigos continuam com a coluna nula. **Não há backfill**, e não deve haver: quem foi notificado há duas semanas é informação que este sistema não guardou, e reconstruí-la pela cascata de hoje inventaria um destinatário que talvez não tenha sido o de então.

## D7 — `VER_LEADS` entra na matriz da TEC-202, para os quatro papéis

A matriz de permissões não tem leitura de lead — a TEC-202 só mapeou as rotas que existiam. Entra `VER_LEADS`, concedida a **ADMIN, GERENTE, CORRETOR e LEITURA**: todos abrem a lista, e o que muda entre eles é **o que ela devolve**.

**O recorte do corretor é do repositório, não da rota.** Um `CORRETOR` recebe a consulta já filtrada pelo próprio `corretor_id` — a claim do JWT, não um parâmetro —, e mandar `corretorId=<outro>` na query **não alarga nada**: o filtro do papel é aplicado por último e ganha. Fazer disso um 403 seria pior, porque a tela legitimamente manda o filtro que o usuário escolheu.

**`CORRETOR` sem vínculo vê lista vazia**, pelo mesmo argumento da D4 da TEC-202: cadastro incompleto não é passe livre, e "não tem dono" nunca vira "é dono de tudo".

## D8 — `status` é o da conversa, e `qualificadoEm` sai ao lado

A card pede filtro por `status`, e o exemplo do SRS escreve `status=QUALIFICADO`. São duas coisas diferentes, e o repo só tem uma delas: `conversas.status` é `ATIVA`/`ENCERRADA` (TEC-138), e "qualificado" é o carimbo `lead_qualification.qualificado_em` (TEC-150).

O filtro `status` opera sobre o ciclo de vida da conversa. A qualificação sai como **campo** (`qualificadoEm`) em cada linha, e não como valor de `status`: colapsar os dois faria um lead qualificado e encerrado ter de escolher um dos dois fatos para relatar.

**E `status` ausente na `conversas` significa `ATIVA`** — a linha só nasce no encerramento (D1), então a lista precisa tratar a ausência como o estado default, e não como desconhecido.

## Arquivos

```
src/mobia/domain/leads/__init__.py
src/mobia/domain/leads/consulta.py         # Filtro, Cursor e a decodificacao (D5)
src/mobia/domain/leads/repositorio.py      # a consulta unica (D1, D4, D5)
src/mobia/api/routes/leads.py              # GET /api/v1/leads
src/mobia/domain/usuarios/permissoes.py    # VER_LEADS (D7)
src/mobia/domain/notificacao/envio.py      # grava handoffs.corretor_id (D6)
src/mobia/app/main.py                      # registro do router
```

Sem migration: todas as colunas já existem.

## Testes

- **Unitários** — o cursor codifica e decodifica; cursor corrompido é recusado; `Filtro` recusa `limite` fora da faixa; a matriz ganha `VER_LEADS` e o mapa de rotas ganha a linha nova.
- **Os quatro cenários do Gherkin, contra banco** — ordenação por score, busca por bairro, o recorte do corretor, e a paginação sobre 120 leads.
- **A paginação, nos dois sentidos** — que a segunda página continua decrescente **e** que nenhuma linha aparece nas duas. A segunda asserta é a que pega o `OFFSET` disfarçado.
- **O empate de score** — dois leads com o mesmo score saem em ordem estável entre chamadas. É o teste que prova o desempate da D5.
- **Busca por telefone nas duas origens** — `conversation_key` do WhatsApp e `vinculos_de_sessao` do web.
- **`handoffs.corretor_id` é escrito** (D6) — a notificação grava o destinatário, e grava-o **mesmo quando o canal falha**: o destinatário foi escolhido, e a falha é do canal.
- **Lead sem score** aparece, com `score: null`, e depois dos que têm.

## Emendas ao SRS

**Emenda E-01 à seção 6.2 / `GET /api/v1/leads` (TEC-192, 25/09/2026)** — a rota **não devolve `id`, `nome` nem `telefone` como o exemplo escreve**, e a razão é de modelo de dados, não de escopo. (a) **Não existe entidade lead**: a identidade é o par `(channel, conversation_key)`, que cada item devolve em `channel` e `conversationKey` — mesma decisão da D9 da TEC-179 para `{conversaId}`. (b) **Nenhuma tabela guarda o nome do lead** (Emenda E-02 da RN-15.1), então não há campo `nome` nem busca por nome; `busca` cobre **telefone e bairro de interesse**. (c) O `telefone` do exemplo sai mascarado por RN-18.5, e **o mascaramento não existe** (TEC-195): esta rota não devolve telefone nenhum, o que é mais restritivo que o previsto e não menos. (d) O filtro `status` opera sobre `conversas.status` (`ATIVA`/`ENCERRADA`), e **não** sobre `QUALIFICADO` como o exemplo de query escreve — a qualificação sai no campo `qualificadoEm`. **Consequência declarada:** quem consumir esta rota identifica o lead pelo par, e a busca por nome continua sem existir enquanto nada guardar o nome.

**Emenda E-06 à RN-16.2 (TEC-192, 25/09/2026)** — `handoffs.corretor_id` **passa a ser escrito**, no mesmo ponto em que a notificação grava `notificado_em`: o destinatário que `destinatario_do_handoff` já escolhe deixa de ser calculado e descartado. A Emenda E-05 da RN-16.1 registrou, em 24/09/2026, que escrevê-la seguia *"em aberto, sem card atribuída"*; fecha aqui, porque a lista de leads precisa de uma resposta para "de quem é este lead". **O valor gravado é o destinatário, que pode ser o plantonista** e não um corretor alocado — é a cascata da Emenda E-01 desta regra, e não uma alocação por especialidade. **Consequência declarada:** handoffs anteriores a esta card continuam com a coluna nula e **não há backfill** — reconstruir o destinatário de então pela cascata de hoje inventaria um fato. O critério *"Handoff aponta o corretor já alocado"* passa a ser exercitável; o filtro por corretor do funil (TEC-190) continua recusado com 422 na borda, porque virá-lo é decisão daquela card.

## Lacunas declaradas

- **L1 — não há busca por nome**, porque não há nome (D3). É o único pedaço da card que não tem como ser entregue, e não por escolha desta implementação.
- **L2 — a busca por telefone não alcança o visitante web que nunca digitou o número.** A sessão dele é anônima por desenho (TEC-129), e o `conversation_key` é um identificador de sessão, não um telefone.
- **L3 — a lista não devolve telefone nem e-mail**, nem mascarados. O mascaramento é a TEC-195, e devolver em claro enquanto ela não chega seria entregar o dado que ela existe para proteger.
- **L4 — a consulta agrega `messages` a cada requisição, sem cache.** É o que o funil também faz, com a mesma justificativa medida (p95 de 0,068 s com 1.000 leads, contra o teto de 2 s da RNF-04). Esta consulta é mais pesada que aquela; **não foi medida com base grande**, e o número do funil não vale como evidência para ela.
- **L5 — `handoffs.corretor_id` só passa a valer para handoffs novos** (D6), então a lista de um corretor cresce a partir de agora, e não retroativamente.
- **L6 — o filtro por corretor do funil continua recusado com 422.** O dado passa a existir; virar aquela borda é card da TEC-190, e mexer nela daqui seria alterar número que a gerente lê sem os testes de lá.
- **L7 — não há ordenação alternativa.** O SRS prevê `?ordenar=score_desc`; só esse valor existe, e o parâmetro não entra para não fingir que há escolha.

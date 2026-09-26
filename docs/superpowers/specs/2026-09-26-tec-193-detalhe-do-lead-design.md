# TEC-193 — Abrir o detalhe do lead com transcrição completa

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-193](https://eduardodurieuxlopes.atlassian.net/browse/TEC-193) — épico TEC-189
**Branch:** `feat/tec-193-detalhe-do-lead`
**Origem:** RF-18, RN-18.2 (SRS v1.0); seção 6.2 · TEC-192, TEC-195, TEC-206 · telas TEC-323, TEC-324, TEC-325, TEC-326

## O problema

A lista existe desde a TEC-192, e o `leadId` que a TEC-195 criou é um endereço que não leva a lugar nenhum: `GET /api/v1/leads/{leadId}` não existe. O resumo de seis blocos da TEC-175 só é lido por quem chama `POST /handoffs/{id}/resumo` à mão, a conversa inteira não tem leitura fora do contexto do agente, e o histórico de score, as recomendações, os agendamentos e os follow-ups existem cada um na sua tabela, sem rota.

A card pede **sete blocos numa tela só**: contato, qualificação, histórico de score, imóveis recomendados, agendamentos, follow-ups e transcrição — com o resumo no topo e um botão de regeneração.

## O que o levantamento achou

**Os sete blocos têm fonte, e todas são pelo par `(channel, conversation_key)`:**

| bloco | tabela | observação |
|---|---|---|
| contato | `conversation_key` / `vinculos_de_sessao` | só mascarado — `leads/mascara.py` (TEC-195) |
| qualificação | `lead_qualification` | em claro por desenho (TEC-145) |
| histórico de score | `lead_score_audit` | append-only, com `causas` e os cinco fatores |
| imóveis recomendados | `recomendacoes` ⨝ `imoveis` | `motivo_match`, `reacao_lead`, `motivo_descarte` |
| agendamentos | `agendamentos` | a TEC-323 diz "sem fonte até RF-11/RF-12"; **a fonte já existe** (TEC-371 em diante) |
| follow-ups enviados | `followups` | uma linha por disparo; o que não disparou não tem linha |
| transcrição | `messages` | `text_body` cifrado, AAD `{id}:text_body`; `role` fechado em LEAD/AGENTE/CORRETOR/SISTEMA |

**O resumo mora no handoff, e não no lead.** `handoffs.resumo` é o texto da TEC-175, cifrado; `conversation_summaries` também se chama resumo e é outra coisa — a janela de contexto do agente, que não é texto para gente. Lead sem handoff não tem resumo.

**A regeneração já existe** — `POST /api/v1/handoffs/{id}/resumo` (TEC-175), com auditoria (TEC-206). O SRS escreve `POST /leads/{leadId}/resumo`; a TEC-326 pede que o backend responda **429** a pedido feito menos de 60 s depois do anterior, e nenhum dos dois caminhos faz isso hoje.

**Ler o resumo é auditado; ler a conversa não é.** `regenerar` grava `DADO_PESSOAL_ACESSADO` com `campo=resumo`. Um `GET` do detalhe que devolvesse o mesmo resumo sem registro seria o furo que a TEC-195 acabou de fechar para o telefone — um segundo caminho, sem trilha, para o mesmo dado.

## D1 — Duas rotas: o detalhe e a transcrição

```
GET /api/v1/leads/{leadId}            → os seis blocos, mais o resumo
GET /api/v1/leads/{leadId}/mensagens  → a transcrição, paginada para trás
```

**A transcrição não vai dentro do detalhe**, e o SRS já a separa (`GET /api/v1/conversas/{conversaId}/mensagens`). A TEC-324 pede páginas de 100 falas, "carregar anteriores" e rolagem que começa na mais recente; uma conversa de 300 falas embutida no detalhe faria a tela pagar o texto inteiro para mostrar o resumo. Os outros seis blocos são pequenos e limitados pela natureza deles — um lead tem poucas recomendações e poucos agendamentos —, e cabem numa resposta só.

**O endereço é `/leads/{leadId}/mensagens`, e não `/conversas/{conversaId}/mensagens`.** Não existe `conversaId` (D9 da TEC-179), e o `leadId` é o único endereço de lead que a API do dashboard devolve desde a TEC-195. Vira emenda.

## D2 — `VER_DETALHE_DO_LEAD`, para ADMIN, GERENTE e CORRETOR

O SRS escreve os papéis da rota: *"`CORRETOR` (próprio), `GERENTE`, `ADMIN`"*. **LEITURA fica de fora**, e a diferença para a lista é o conteúdo: a lista é um índice sem dado pessoal (TEC-195, D4); o detalhe traz a conversa em claro.

**Permissão nova, e não `ATENDER_LEAD`.** Os papéis são os mesmos, e a tentação é reaproveitar. Recusado: `ATENDER_LEAD` está em `DE_ESCRITA`, e guardar uma leitura com permissão de escrita faria o dia em que alguém der `ATENDER_LEAD` a um papel novo decidir, sem querer, se ele lê conversas. Leitura fora de `DE_ESCRITA`, pelo mesmo argumento de `VER_DADOS_COMPLETOS`.

**O CORRETOR só abre o próprio lead**, pelo mesmo vínculo que o recorte da lista usa: existe `handoffs.corretor_id` igual ao dele (`e_lead_do_corretor`). Negar grava `ACESSO_NEGADO` com `motivo=corretor_nao_e_o_dono` e responde **403** — o molde de `exigir_dono` (TEC-202, D5 e D8), que usa 403 e não 404 para a sondagem ao lead do colega não se perder no ruído.

**Ordem das checagens: 404, depois 403, depois registro, depois leitura.** O apelido inexistente é 404 para todo papel; o CORRETOR que pede o lead de outro é 403 antes de qualquer consulta ao conteúdo.

## D3 — O GET registra na trilha

**Decisão do Eduardo, 26/09/2026, com três alternativas na mesa.** As duas rotas gravam `DADO_PESSOAL_ACESSADO` e **comitam antes de responder**:

- detalhe → `entidade=lead`, `entidade_id=<apelido>`, `campo=detalhe`
- transcrição → a mesma coisa com `campo=transcricao`, **uma linha por página**: carregar as falas anteriores é outro acesso, a um trecho que a primeira página não mostrou

Mesmo molde de `revelar` e de `regenerar`: `lead=par` vira `lead_ref`, nunca o par; registra a **tentativa**, antes de montar a resposta; se a escrita falhar, a resposta é erro e o conteúdo não sai.

**Isto revisita o argumento da TEC-195 contra `GET` com efeito** (D5 de lá: *"um `GET` que escreve é repetido por proxy e disparado por pre-fetch"*). Continua valendo para `revelar`, onde o registro é a razão da chamada. Aqui ele pesa menos, por duas razões. Uma: a leitura **é** a ação — abrir a tela é o acesso, e modelá-la como `POST` faria a rota mentir sobre o que faz. Outra: as duas rotas exigem `Authorization: Bearer`, que o pre-fetch do navegador não manda; o pedido sem credencial é 401 e não escreve nada. Uma repetição por proxy produz um registro a mais, e a trilha erra para o lado de registrar.

As alternativas e por que não:

- **Detalhe sem o texto do resumo**, que continuaria saindo só pelo `POST` que já audita: poupa o registro no detalhe e obriga a tela a fazer duas chamadas para mostrar a primeira seção — e a transcrição precisaria registrar do mesmo jeito.
- **Não registrar leitura**: reabre, para o resumo, o furo que a TEC-195 fechou para o telefone, e deixa sem trilha o maior volume de dado pessoal do sistema.

**`campo` é texto livre na `0053`** (`String(32)`, sem CHECK), então `detalhe` e `transcricao` entram como constantes em `auditoria/vocabulario.py`, sem migration.

## D4 — A forma do detalhe

```json
{
  "leadId": "uuid", "channel": "whatsapp", "status": "ATIVA",
  "ultimaInteracaoEm": "ISO-8601",
  "contato": { "telefone": "+55 48 9****-**21", "email": null },
  "resumo": { "handoffId": "uuid", "texto": "…", "geradoEm": "ISO-8601",
              "modelo": "…", "fallback": false },
  "qualificacao": { "score": 82, "temperatura": "QUENTE", "qualificadoEm": "…",
                    "intencao": "COMPRA", "regiao": "Campeche", … },
  "historicoScore": [ { "em": "…", "anterior": 47, "novo": 82,
                        "fatores": { "completude": …, … }, "causas": ["…"] } ],
  "recomendacoes": [ { "imovelId": "uuid", "codigo": "…", "titulo": "…", "bairro": "…",
                       "scoreMatch": 0.87, "motivoMatch": "…", "reacao": "DESCARTOU",
                       "motivoDescarte": "PRECO", "apresentadoEm": "…" } ],
  "agendamentos": [ { "id": "uuid", "tipo": "…", "inicio": "…", "fim": "…",
                      "status": "CONFIRMADO", "imovelId": "uuid" } ],
  "followups": [ { "tentativa": 1, "temperatura": "MORNO", "disparadoEm": "…" } ]
}
```

- **Contato só mascarado**, pela D4 da TEC-195: nenhuma resposta da API do dashboard contém o telefone em claro, e quem quer o número chama `revelar`. `email` sai `null` — não há fonte (D7 da TEC-195).
- **`resumo` é o do handoff mais recente**, e `null` quando o lead nunca teve handoff ou o resumo ainda não foi gravado. `fallback` é o que a TEC-323 usa para escolher entre "Resumo simplificado" e "Gerado pelo assistente". `handoffId` é o que o botão de regenerar chama (D6).
- **`historicoScore` em ordem cronológica crescente**, que é o que o cenário 4 do Gherkin afirma e o que um gráfico de linha consome. Os fatores saem inteiros — é o que explica o recálculo, e a TEC-325 pede o motivo de cada um.
- **Listas vazias são `[]`, nunca `null`**: a TEC-325 distingue "sem recomendações" (estado vazio) de "Ainda não medido", e `null` numa lista forçaria a tela a adivinhar qual dos dois é.
- **Sem `nome`**, pela Emenda E-02 da RN-15.1 — a mesma lacuna da lista.

## D5 — A transcrição

```
GET /api/v1/leads/{leadId}/mensagens?limite=100&cursor=<opaco>
→ { "itens": [ { "id": "uuid", "autor": "LEAD", "tipo": "TEXTO",
                 "conteudo": "…", "retida": false, "em": "ISO-8601" } ],
    "cursorAnterior": "opaco" | null }
```

- **Página em ordem cronológica, cursor para trás.** A consulta desce por `(created_at DESC, id DESC)` para o `LIMIT` cortar as mais antigas, e a página é revertida antes de sair — o mesmo desenho de `historico_da_sessao` (TEC-124). `cursorAnterior` aponta para a fala mais antiga da página; `null` diz que não há anteriores.
- **O desempate por `id` é obrigatório**, e pela razão que `historico.py` já escreve: `_persist` grava o lote de um envelope num INSERT só, e `created_at` é o `now()` do statement, igual para todas as linhas dele.
- **O cursor carrega `(created_at, id)` da mensagem**, em base64 de JSON, como o da lista. O id de mensagem não é dado pessoal, então o que a TEC-195 teve de consertar no cursor da lista não se repete aqui. Mensagem que não pertence ao lead do endereço é cursor inválido, 422.
- **`limite` padrão 100**, que é o número da TEC-324, com teto 200.
- **`autor` é o `role` cru**: os quatro valores de `ck_messages_role`. A TEC-324 pede rótulo textual para os quatro, e traduzi-los aqui seria texto de tela no backend.
- **`conteudo` é o texto decifrado, ou `null` quando não há texto** — mídia, ou fala gravada sem corpo. `tipo` diz qual, e a tela escolhe o que mostrar. **Não há download de mídia** (L3).

**A fala retida pela moderação** segue a TEC-324 à letra: para `ADMIN` ela sai com `retida: true` e `conteudo: null` — a tela escreve "Mensagem retida pela moderação" —, e para os outros papéis **não sai**. O filtro é da consulta, e não do laço depois dela, para que a página de 100 tenha 100 falas visíveis. O conteúdo não sai para ninguém: a TEC-236 a tirou do contexto e do resumo, e esta seria a primeira tela a devolvê-la.

## D6 — A regeneração fica em `/handoffs/{id}/resumo`, e ganha a trava de 60 s

O SRS escreve `POST /api/v1/leads/{leadId}/resumo`. **Não se cria**: o resumo é do handoff, a rota de lá já gera, audita e recorta o CORRETOR, e uma segunda porta para a mesma chamada paga ao modelo seria mais uma superfície a manter igual. O detalhe devolve `resumo.handoffId`, e é por ele que a tela chama.

**A trava de 60 s entra na rota existente**, porque a TEC-326 pede um 429 que ninguém escreve: se `resumo_gerado_em` do handoff tem menos de 60 s, a resposta é **429** com `Retry-After`, **antes** de chamar o modelo — a trava existe para poupar a chamada paga, e checá-la depois não pouparia nada. A contagem é pelo carimbo que já existe, e não por um contador novo: a geração automática do handoff também conta como "a última", e é o certo — o resumo tem segundos de idade de qualquer jeito.

O 429 **não grava** `DADO_PESSOAL_ACESSADO`: nenhum resumo sai.

## D7 — Um lead é um par, e o histórico multicanal não se junta aqui

Desde a TEC-129, `vinculos_de_sessao` diz que uma sessão web e um número de WhatsApp são a mesma pessoa. A lista mostra os dois como leads distintos (D1 da TEC-192), e o detalhe segue: **a transcrição é a do par do endereço**. Juntar os dois pares numa conversa só pediria decidir qual `leadId` é "o" lead, e isso é modelo de dados que a TEC-195 recusou ao criar o apelido. Lacuna L4.

## Arquivos

```
src/mobia/domain/leads/detalhe.py          # os seis blocos e o resumo (D4)
src/mobia/domain/leads/transcricao.py      # a pagina, o cursor, a moderacao (D5)
src/mobia/api/routes/leads.py              # GET /{lead_id} e GET /{lead_id}/mensagens
src/mobia/api/routes/handoffs.py           # a trava de 60 s (D6)
src/mobia/domain/usuarios/permissoes.py    # VER_DETALHE_DO_LEAD (D2)
src/mobia/domain/auditoria/vocabulario.py  # CAMPO_DETALHE, CAMPO_TRANSCRICAO (D3)
```

Sem migration.

## Testes

- **Unitários** — o cursor da transcrição codifica, decodifica e recusa o corrompido; `limite` fora da faixa é recusado; a matriz ganha `VER_DETALHE_DO_LEAD` fora de `DE_ESCRITA` e sem LEITURA; o mapa de rotas ganha as duas linhas.
- **Os quatro cenários do Gherkin, contra banco** — os sete blocos presentes (o sétimo pela rota de transcrição); autor e timestamp em cada fala, com LEAD, AGENTE e CORRETOR; imóvel descartado com motivo e reação; quatro recálculos em ordem cronológica, com causas.
- **A paginação para trás sobre 300 falas** — três páginas de 100, nenhuma fala repetida, nenhuma perdida, cada página cronológica; e o lote com `created_at` igual, que é o teste do desempate.
- **A moderação por papel** — ADMIN vê a fala retida sem conteúdo; CORRETOR e GERENTE não a veem, e a página continua com o número pedido.
- **O recorte** — CORRETOR dono abre; CORRETOR de outro lead leva 403 e grava `ACESSO_NEGADO`; LEITURA leva 403; apelido inexistente é 404.
- **A trilha** — cada rota grava `DADO_PESSOAL_ACESSADO` com o campo certo e o `lead_ref`, e nunca o par; o 403 não grava acesso.
- **A trava de 60 s** — regenerar logo após um resumo gravado dá 429 e não chama o redator.
- **Resumo** — lead sem handoff traz `resumo: null`; o resumo de fallback traz `fallback: true`.

## Emendas ao SRS

- **RN-18.2, Emenda E-01** — a forma do detalhe (D4), a transcrição em rota separada (D1, D5), a moderação por papel, e as lacunas L1–L4.
- **Seção 6.2, `GET /api/v1/leads/{leadId}` e `GET /api/v1/conversas/{conversaId}/mensagens`, Emenda E-01** — o endereço da transcrição passa a ser `/leads/{leadId}/mensagens`; o `POST /leads/{leadId}/resumo` não se cria, e a regeneração continua em `/handoffs/{id}/resumo`, com o 429 de 60 s.
- **RNF-12, Emenda E-04** — `VER_DETALHE_DO_LEAD`, para ADMIN, GERENTE e CORRETOR; LEITURA vê a lista e não o detalhe.
- **RNF-18, Emenda E-03** — abrir o detalhe e ler cada página da transcrição passam a ser registrados, por `GET`, e a razão por que o argumento da TEC-195 contra `GET` com efeito não se aplica aqui.

## Lacunas declaradas

- **L1 — sem nome do lead**, pela Emenda E-02 da RN-15.1. Mesma lacuna da lista.
- **L2 — o resumo só existe para quem teve handoff.** Lead que nunca foi encaminhado tem `resumo: null`, e gerar resumo fora de handoff seria outra card: o dossiê que a geração consome nasce no handoff.
- **L3 — a mídia recebida não se lê pelo detalhe.** A fala de mídia aparece com `tipo` e `conteudo: null`. O desenho da TEC-132 atribuía a tela de mídia a esta card; o texto da card não a pede, e servir o binário decifrado com autorização por papel é uma rota própria, com auditoria própria.
- **L4 — a sessão web e o WhatsApp da mesma pessoa continuam sendo dois leads** (D7).
- **L5 — `historicoScore`, `recomendacoes`, `agendamentos` e `followups` saem inteiros, sem paginação.** São limitados pela natureza — a trilha de score só grava quando algo muda —, mas **não foram medidos** num lead de conversa longa.
- **L6 — as tarefas de corretor (`tarefas_de_corretor`, TEC-186) não entram.** A card pede follow-ups *enviados*, e a tarefa é justamente o follow-up que não pôde ser enviado; ela merece a própria seção na tela, e a tela ainda não a pede.
- **L7 — o recorte do CORRETOR é só por handoff**, como o da lista. O corretor que tem visita marcada com um lead, mas nunca recebeu handoff dele, não abre o detalhe.

# TEC-404 — tela "Pedidos de interesse" no painel

Card: TEC-404. Continua a TEC-389, que criou o "Quero ser contatado" do portal e contou só com a notificação ao corretor.

## O que muda

Quem pede contato pelo portal passa a aparecer numa tela própria do painel, `/interesses`. Nela o admin vê todos os pedidos, e o corretor vê os dele. O admin atribui cada pedido a um corretor, e o corretor assume o pedido. Telefone e e-mail aparecem mascarados e se revelam um a um, com registro na trilha.

Hoje o pedido é gravado (`solicitacoes_de_interesse` e um handoff `INTERESSE_PORTAL`) e não aparece em lugar nenhum. A lista de `/leads` parte de `messages`, e o pedido do portal não tem mensagem. Quando a notificação falha, a marca `aviso_manual_pendente` também não é lida por tela nenhuma.

## Decisões de produto (da card, 09/10/2026)

1. O e-mail ganha coluna própria, cifrada. Pedidos anteriores ficam sem e-mail, sem backfill.
2. Telefone que já tinha atendimento aberto aparece ligado a esse atendimento.
3. O admin atribui o pedido a um corretor por esta tela.
4. Atribuir troca o aceite: o atendimento aceito por A, atribuído a B, volta a pendente de B.
5. **(desta conversa)** O corretor revela telefone e e-mail **só dos pedidos dele**, com registro na trilha. Nos leads de WhatsApp a revelação continua exigindo `VER_DADOS_COMPLETOS`.

## Decisões de desenho

**D1 — A atribuição mora num módulo próprio, `domain/handoff/atribuicao.py`, e a notificação existente faz o resto.** `atribuir(session, *, handoff_id, corretor_id, ator)` faz, numa transação só:

- grava `corretor_id` = o novo;
- volta `status` para `PENDENTE`;
- zera `aceito_em`, `sla_limite_em` e `notificado_em`, e põe `aviso_manual_pendente = false`;
- grava `atualizado_em`;
- registra na trilha o corretor anterior e o novo (D6).

Depois do commit, a rota enfileira `notificar_corretor` com **job id novo**, `notificar:{handoff_id}:atribuicao:{uuid4}`. O id `notificar:{handoff_id}` da primeira notificação pode estar retido no Redis como resultado, e o arq descartaria um job com o mesmo id.

A partir daí, `notificacao/envio.py::notificar` faz o que já faz:

- `destinatario_do_handoff` devolve o `corretor_id` gravado, porque o corretor está ativo, o que a rota conferiu.
- Como `sla_limite_em` é nulo e o status é `PENDENTE`, o prazo é calculado de novo pela jornada do **novo** corretor (RN-16.3, E-01).
- A notificação grava `notificado_em`, ou a marca `aviso_manual_pendente` se nenhum canal aceitar.

Os dois pontos de atenção da card se resolvem assim. O SLA recomeça para o novo corretor por construção. E `sweep_sla` não precisa mudar:

- `escalar_vencidos` só olha `PENDENTE` com prazo vencido, e o prazo novo ainda não venceu;
- `recuperar_sem_prazo` cobre o intervalo entre o commit e a notificação, se o job se perder.

**Alternativas recusadas:**

- **Passar a atribuição por dentro de `envio.py`, com um parâmetro de "corretor forçado".** Preserva a frase "único escritor", mas faz um job de notificação decidir dono por ordem do admin. Uma retentativa do arq também teria de carregar o parâmetro.
- **Coluna separada `corretor_atribuido_id`.** Obrigaria a lista de leads, o recorte do corretor, o aceite e a notificação a olhar duas colunas para responder "de quem é este lead".

**D2 — Emendas ao SRS** (texto a acrescentar como item aninhado, sem reescrever o original):

- Abaixo de **RN-16.2**: **Emenda E-07 (TEC-404, 09/10/2026)**.
  - `handoffs.corretor_id` ganha um **segundo escritor**: a atribuição manual do admin (`domain/handoff/atribuicao.py::atribuir`). A Emenda E-06 o fazia escrito só pela notificação.
  - A atribuição **sobrescreve** de propósito, porque é o admin trocando o dono.
  - A regra "grava apenas quando a coluna está nula" continua valendo para a notificação, que é o que protege o dono contra uma retentativa do arq.
- Abaixo de **RN-16.3**: **Emenda E-08 (TEC-404, 09/10/2026)**.
  - A atribuição manual **reinicia o SLA**. O atendimento volta a `PENDENTE`, sem aceite e sem prazo, e a notificação ao novo corretor calcula o prazo pela jornada dele.
  - Um atendimento `ESCALADO` atribuído volta a `PENDENTE` pelo mesmo caminho.

**D3 — O e-mail vai para `solicitacoes_de_interesse.email_cifrado`** (bytea, nulo). Migration `0071`, com `down_revision` `0070`.

- O valor é cifrado com `mobia.infra.crypto.encrypt` e uma AAD própria: `interesse:email:{id}`, com o `id` da linha, gerado antes do insert.
- `registrar_interesse` ganha o parâmetro `email` e o grava no insert. No conflito (o mesmo telefone pedindo o mesmo imóvel, D2/L3 da TEC-389) a linha antiga fica como estava, e o e-mail novo se perde.
  - É a deduplicação que a TEC-389 já decidiu. Fica declarado aqui para não parecer bug.

**D3a — Uma coluna cifrada a mais tem dois compromissos fora deste módulo**, achados ao planejar:

- **Rotação de chave.** A coluna entra em `admin/recifrar.py::COLUNAS_CIFRADAS`, com a AAD `aad_de(id, "email_interesse")`. A guarda `test_colunas_cifradas.py` só varre módulos chamados `models.py`, e `SolicitacaoDeInteresse` mora em `portal/interesse.py`, então ela não pegaria o esquecimento. O teste desta card afirma a entrada diretamente.
- **Anonimização (LGPD).** `titular/anonimizacao.py` já zera `nome` desta tabela e passa a zerar `email_cifrado` no mesmo `UPDATE`.

**D4 — Cada pedido aponta para o atendimento mais recente do mesmo lead criado até o momento do pedido.** A ligação é por `(channel, conversation_key)`, com `handoffs.criado_em <= solicitacoes_de_interesse.criado_em`, o maior primeiro (`LATERAL ... LIMIT 1`).

- O atendimento nasce na mesma transação, logo antes do pedido. Se já havia um aberto para o mesmo telefone, porque o lead pediu outro imóvel antes, é esse que aparece. Isso cumpre a decisão 2.
- Depois de um atendimento `CONCLUIDO`, um pedido novo abre outro atendimento, e os pedidos antigos continuam apontando para o antigo.
- **Limite declarado:** o mesmo telefone no WhatsApp tem outra `conversation_key` (`chave_de` inclui o canal). Por isso um atendimento aberto no WhatsApp **não** se liga ao pedido do portal. Ligar canais é a absorção de identidade, outra discussão.

**D5 — A revelação tem rota própria, `POST /api/v1/interesses/{id}/revelar`, com `{campo: "telefone" | "email"}`.** Ela não reaproveita a de `/leads`, por dois motivos:

- o e-mail é por pedido, não por lead;
- abrir a rota de leads ao corretor ampliaria o acesso dele a todo lead vinculado, o que a decisão 5 não pediu.

**Regras:**

- **Quem pode:** quem tem `VER_DADOS_COMPLETOS` revela qualquer pedido. O CORRETOR revela só os pedidos cujo atendimento (D4) tem `corretor_id` igual ao dele. Fora disso a resposta é 403, com `exigir_dono`, que grava `ACESSO_NEGADO`. Quem não é nem uma coisa nem outra recebe 403.
- **Trilha:** `registrar_evento(acao=DADO_PESSOAL_ACESSADO, entidade=Entidade.LEAD, entidade_id=<leadId>, campo=<campo>, lead=<par>)`, gravado com commit **antes** de ler o valor, como em `leads.py::revelar`.
- **Telefone:** `identidade/indice.py::revelar(session, channel, chave)`, formatado com `+`. **E-mail:** a coluna decifrada.
- **Valor ausente** (e-mail nulo, ou pedido anterior à migration): responde `{valor: null}`, e a tela mostra "não informado".

**D6 — A trilha ganha a ação `HANDOFF_ATRIBUIDO`** em `domain/auditoria/vocabulario.py::Acao`.

- Entidade `HANDOFF`, `entidade_id` = id do atendimento.
- `detalhes = {"corretor_anterior": <uuid ou null>, "corretor_novo": <uuid>, "aceito_desfeito": "sim" | "nao"}`.
- **O `CHECK` de `eventos_auditoria.acao` é recriado** na migration `0071`, como fizeram a 0057, a 0059 e a 0063, porque o Postgres não estende `CHECK`. O downgrade o recria `NOT VALID`.
- **`detalhes` hoje só aceita vocabulário fechado** (`validar_detalhes`). Id de corretor não é vocabulário, mas também não é texto livre. As duas chaves de corretor passam a ser validadas como **UUID ou nulo**, e `aceito_desfeito` como `"sim"`/`"nao"`. Um texto qualquer nessas chaves continua sendo `ValueError`.
- O aceite (`handoffs.py::aceitar`) continua sem trilha, como hoje: mudar isso é outra card.

**D7 — Permissões**

| ação | quem | recorte |
| --- | --- | --- |
| listar (`GET /api/v1/interesses`) | `VER_LEADS` | CORRETOR só os dele, pelo mesmo `RecorteDoPapel` de `/leads`; sem vínculo, lista vazia |
| revelar | `VER_DADOS_COMPLETOS`, ou CORRETOR dono | D5 |
| assumir (`POST /api/v1/handoffs/{id}/aceitar`, existente) | `ATENDER_LEAD` | a rota já exige o dono para o CORRETOR |
| atribuir (`POST /api/v1/handoffs/{id}/atribuir`) | `GERIR_CORRETORES` | só ADMIN tem; é a mesma permissão de `GET /api/v1/corretores`, que preenche o seletor |

`atribuir` recusa:

- corretor inexistente ou inativo: 422;
- atendimento inexistente: 404;
- atendimento `CONCLUIDO`: 409;
- atribuir ao mesmo corretor de um atendimento ainda `PENDENTE`: 200, sem efeito e sem trilha. Não reenvia a notificação.

**D8 — A listagem**

`GET /api/v1/interesses?estado=pendentes|todos&limite=&cursor=`

- `pendentes`, o padrão, mostra atendimentos `PENDENTE` ou `ESCALADO`.
- A ordem é por `criado_em` decrescente e depois `id`. A paginação é por posição (keyset), com cursor opaco, e a resposta não traz total, como em `/leads`.
- Cada item:

```
{ id, criadoEm,
  imovel: { id, codigo, titulo },
  nome, telefoneMascarado, emailMascarado, leadId,
  atendimento: { id, status, corretor: { id, nome } | null,
                 notificadoEm, semCorretor } }
```

- `leadId` é o apelido de `referencias_para`, para o link "ver lead" e para a trilha. `semCorretor` é `aviso_manual_pendente`.
- **Máscaras:** `mascarar_telefone`; `mascarar_email` existe em `domain/leads/mascara.py` sem uso e passa a ter um.
- **Telefone em lote: corrigir `identidade/indice.py::telefones_de`.** Hoje ele só lê `IdentidadeDeLead` para o canal WhatsApp; os demais canais vão a `VinculoDeSessao`. O portal grava em `IdentidadeDeLead` (`registrar_identidade`), então hoje o telefone de um lead do portal sai `None`. O canal `portal` passa a ler `IdentidadeDeLead`, como o WhatsApp.

**D9 — Front**

- **Página `(painel)/interesses/page.tsx`**, Server Component, com `exigirPermissao(..., p => p.has('VER_LEADS'))`, paginada como `/leads`.
- **Item "Pedidos de interesse"** em `lib/navegacao.ts::itensDoMenu`, com `VER_LEADS`.
- **Filtro** pendentes/todos pela URL.
- **Linha com estado "sem corretor"** em destaque.
- **Revelação:** o `DadoRevelavel` existente, generalizado para receber a URL de revelação, em vez de montar a de `/leads`. O botão aparece se o usuário tem `VER_DADOS_COMPLETOS`, ou se é corretor e o atendimento é dele.
- **"Assumir":** aparece se `quem.corretorId` existe, o atendimento é dele e está `PENDENTE` ou `ESCALADO`.
- **"Atribuir":** um seletor com os corretores ativos, que vêm de `GET /api/v1/corretores?ativos=true`, e o botão. Só com `GERIR_CORRETORES`. Depois da ação, a tela recarrega (`router.refresh()`).
- **Allowlist do `bff.ts`:** `POST handoffs/*/aceitar`, `POST handoffs/*/atribuir`, `POST interesses/*/revelar`.
- **Textos:** português com acento (é produto).

## Testes

- **Unitários:**
  - a cifra e a AAD do e-mail;
  - o recorte de quem revela (D5);
  - a montagem do item da listagem;
  - `telefones_de` com o canal `portal`;
  - o front: página, linha, atribuição e allowlist.
- **Integração, contra o Postgres:**
  - a listagem para admin, corretor A, corretor B e corretor sem vínculo;
  - o filtro de estado;
  - um pedido ligado a um atendimento já aberto (decisão 2);
  - a revelação pelo corretor dono, pelo corretor alheio (403 e `ACESSO_NEGADO`) e pelo admin, com o evento na trilha;
  - a atribuição em três cenários: sem corretor; aceito por A e passado a B, que zera o aceite, grava a trilha e enfileira o job com id novo; e `CONCLUIDO` (409);
  - a notificação depois da atribuição, que calcula o prazo pela jornada de B e não de A;
  - o e-mail gravado cifrado.

## Fora

- Mostrar o pedido do portal em `/leads`.
- Trilha no aceite.
- Ligar o pedido do portal a um atendimento do WhatsApp do mesmo telefone.
- Backfill do e-mail dos pedidos antigos.
- Envio de WhatsApp ao corretor.
- Responder ao visitante pelo painel.

# TEC-389 — Solicitar interesse em um imóvel pelo portal do cliente

Card: https://eduardodurieuxlopes.atlassian.net/browse/TEC-389
Depende de: TEC-387 (busca), TEC-388 (detalhe).

## Contexto

Hoje, pedir um imóvel significa abrir uma conversa com o agente (WhatsApp/widget).
A TEC-389 adiciona um canal estruturado: a partir do detalhe de um imóvel
(TEC-388), o cliente envia telefone (+ nome/e-mail opcionais) e isso vira um
handoff para o corretor responsável — sem nenhuma conversa.

## Perguntas bloqueantes da card, e a decisão

A card lista duas perguntas bloqueantes. Ambas foram decididas com o Eduardo
antes deste desenho:

**B1 — Quais dados o formulário exige, e o pedido se unifica ao histórico do
WhatsApp pelo telefone?** Telefone é obrigatório (normalizado pela mesma
função que o WhatsApp usa, `domain/identidade/telefone.py::normalizar`); nome
e e-mail são opcionais. O telefone é gravado sob o mesmo índice de identidade
(HMAC) que o WhatsApp usa — isso NÃO ativa unificação automática de
qualificação agora (ver L1, abaixo), mas deixa o terreno preparado: uma card
futura que estenda `domain/identidade/absorcao.py` ao canal `portal` consegue
reusar o mesmo telefone já indexado, sem precisar de nenhum dado retroativo.

**B2 — Reaproveitar a notificação de handoff existente, ou um fluxo novo?**
Reaproveita. Um pedido de interesse chama `registrar_handoff` com um
`Gatilho` novo (`INTERESSE_PORTAL`) e o mesmo `notificar` (e-mail/WhatsApp,
alocação por corretor de plantão) que já atende o fluxo conversacional. Isso
evita o risco que a própria card cita: um segundo caminho de "lead pronto"
divergindo da régua existente.

## Decisões de desenho

**D1 — Canal novo `"portal"` (`CANAL_PORTAL`), não reaproveita `"web"`.**
O widget (`"web"`) já tem semântica própria (sessão anônima de chat,
`VinculoDeSessao`, reengajamento). Misturar um pedido de formulário sem
conversa nesse canal faria qualquer leitura futura de "mensagens do canal
web" precisar distinguir os dois por fora. Um canal dedicado é mais barato
que essa ambiguidade — mesmo raciocínio que separou `"whatsapp"` de `"web"`
na TEC-124.

**D2 — O pedido em si vira uma linha em `solicitacoes_de_interesse`,
independente do ciclo de vida do handoff.** O handoff tem um estado
(PENDENTE → ACEITO/CONCLUÍDO) e uma restrição de unicidade por lead aberto —
não é o lugar certo para registrar "o cliente pediu o imóvel X", porque um
handoff já aberto por outro motivo (ex.: o mesmo telefone já conversou no
WhatsApp e tem handoff pendente) absorveria o gatilho sem deixar rastro do
imóvel pedido. A tabela nova guarda `imovel_id`, `conversation_key`, `nome`
(opcional) e `criado_em`, com `UNIQUE(conversation_key, imovel_id)` — é o que
resolve CA-04 (duplicidade) de forma idempotente: pedir de novo o mesmo
imóvel com o mesmo telefone não duplica a linha nem é erro, apenas confirma
de novo (`ON CONFLICT DO NOTHING`, mesma resposta de sucesso).

**D3 — Resumo determinístico, nunca o pipeline de LLM/dossiê.**
`handoff/geracao.py::gerar_resumo` lê um `Dossie` montado de
`LeadQualification`/`Recomendacao` — dados de uma conversa que este fluxo não
tem. Chamar esse pipeline aqui devolveria sempre "sem dossiê" (nenhum
template, porque não há fatos de conversa) e, pior, não incluiria a
informação que de fato importa: qual imóvel e o nome do interessado. Em vez
de estender `Dossie` para um caso que não é conversa, o handler grava o
resumo diretamente (`gravar_resumo`, `modelo=None`, `fallback=True`) com um
texto fixo: nome (ou "não informado"), telefone e o título/código/link do
imóvel. O campo já é cifrado pela própria coluna (`Handoff.resumo`), então
não há diferença de tratamento de dado sensível em relação ao resumo gerado
por LLM.

**D4 — Notificação só dispara quando o handoff É NOVO.**
Mesma regra que `_agendar_resumo` já aplica no fluxo conversacional (um
gatilho adicional em handoff já aberto não reagenda nada): se o telefone já
tem um handoff aberto — de qualquer gatilho, inclusive um iniciado no
WhatsApp —, o pedido de interesse grava a linha em
`solicitacoes_de_interesse` e acrescenta `INTERESSE_PORTAL` a
`gatilhos_adicionais` do handoff existente (comportamento padrão de
`registrar_handoff` em ON CONFLICT), mas não reescreve o resumo nem
reenfileira notificação — o corretor já foi acionado. Evitar isso seria
reabrir um aviso para quem já está atendendo o lead.

**D5 — Mesma recusa 404 da TEC-388 para imóvel indisponível (CA-03).**
Reaproveita o helper já existente em `portal.py` — nenhuma mensagem nova,
nenhuma diferença de tratamento entre "nunca existiu" e "saiu de disponível
entre a visualização e o envio".

**D6 — Validação do telefone é 422, não 400.**
Mesmo padrão de `id` malformado na TEC-388: o FastAPI valida o corpo antes de
qualquer lógica de domínio rodar, e um telefone vazio ou não reconhecível por
`normalizar` (devolve `None`) vira `422` com o campo citado — CA-02.

**D7 — Rate limit por telefone, além do rate limit por IP que todo POST já
ganha de graça.** O middleware global (`RateLimitPorIP`) já cobre a rota.
Mas um formulário público sem sessão é alvo fácil de flood pelo mesmo
telefone em imóveis diferentes — por isso o handler também chama
`infra/rate_limit.py::consumir` com um escopo dedicado
(`"interesse_portal"`), chaveado pelo HMAC do telefone, no mesmo padrão que
`domain/messages/service.py` já usa para limitar por número.

## Fora de escopo / lacunas

- **L1 — Sem unificação automática com o WhatsApp.** O telefone entra no
  mesmo índice de identidade, mas `domain/identidade/absorcao.py` só lê
  sessões do canal `"web"` hoje; estender a canal `"portal"` fica para uma
  card futura. Até lá, um corretor que já atende esse telefone pelo WhatsApp
  não vê o pedido do portal automaticamente unificado — só os dois handoffs
  separados (se ambos chegarem a notificar).
- **L2 — Sem confirmação ao cliente** (e-mail/SMS de "recebemos seu pedido").
  A card já marcava isso como "a confirmar", não como critério de aceite.
- **L3 — Duplicidade (CA-04) é silenciosa, não visível ao cliente.** O
  cliente que reenvia o mesmo pedido recebe a mesma resposta de sucesso; o
  portal não informa "você já tinha pedido isso" — decisão deliberada para
  não vazar, a quem reusa o formulário, se um pedido anterior já existe.

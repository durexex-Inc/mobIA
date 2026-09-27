# TEC-124 — Atender pelo widget web via WebSocket

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-124](https://eduardodurieuxlopes.atlassian.net/browse/TEC-124) — épico TEC-123
**Branch:** `feat/tec-124-widget-web-via-websocket`
**Origem:** RF-01, RN-01.1 (SRS v1.0); RNF-16 para o limite de abuso.

## Objetivo

Abrir o segundo canal de entrada: a visitante do site conversa pelo chat da própria página, e a resposta do agente volta na mesma sessão. O pipeline não muda — muda quem entrega na ponta.

## O que o repo já preparou, e o que ele prometeu errado

Quatro sítios desta árvore foram escritos antecipando esta card. Três estavam certos:

| sítio | o que reservou | vale? |
| --- | --- | --- |
| `messages.channel` + `IngestionService.ingest(..., channel=)` | a coluna e o parâmetro | sim |
| UNIQUE `(channel, provider_message_id)` | "o widget web (TEC-124) tem espaço de ids próprio" | sim |
| docstring de `OutboundPort` | "o canal web da TEC-124 não tem janela nenhuma" | sim — ver a D4 |
| comentário de `create_app` | "aplica-se por omissão e não por opt-in: uma lista de rotas incluídas erraria para o lado de esquecer o widget do TEC-124" | **não** — ver a D7 |

O quarto é o achado que muda o desenho, e está na D7.

## D1 — O canal se chama `web`, minúsculo, e ganha vocabulário próprio

A card escreve `canal = WEB`. **A implementação grava `web`.**

O único literal que `messages.channel` conhece hoje é `whatsapp`, minúsculo — e é com ele que a coluna está povoada desde a TEC-122. Um `WEB` maiúsculo ao lado faria toda consulta por canal depender de caixa, e o primeiro `WHERE channel = 'web'` escrito de memória sairia vazio sem erro nenhum.

Nasce `domain/messages/canais.py`, e o `channel: str = "whatsapp"` solto no default de `IngestionService.ingest` passa a apontar para lá. O módulo guarda três nomes:

- `CANAL_WHATSAPP`, `CANAL_WEB` — os dois valores da coluna;
- `CANAIS_COM_REENGAJAMENTO` — allowlist, hoje só o WhatsApp, usada pela D8.

**Não entra CHECK no banco.** A coluna não tem um hoje, e acrescentá-lo é migration sobre uma tabela que já tem volume, por um vocabulário que esta card não fecha — a TEC-131 e a TEC-132 podem trazer mais. A divergência de caixa em relação ao texto da card vai no comentário dela.

## D2 — A sessão é emitida pelo servidor, e o id nunca viaja em URL

`WS /widget/chat`. O servidor aceita a conexão e espera o primeiro frame, que tem de ser o cumprimento:

```json
{"tipo": "ola", "sessao": null}
```

Com `sessao: null`, o servidor gera um UUIDv4 e responde `{"tipo":"sessao","sessao":"…"}`. Com um UUID, retoma aquela sessão. Qualquer outro `tipo` como primeiro frame fecha o socket com 1002 — não há caminho em que a mensagem preceda a identidade.

**Nada de `?sessao=` na query string.** O id é portador anônimo: quem o tiver lê aquela conversa. Num query string ele entraria em log de acesso, em `Referer` e no histórico do navegador — três cópias que ninguém pretendia criar. Dentro do frame ele fica no corpo da conexão e em mais lugar nenhum.

O que a sessão preenche em `messages`:

| coluna | valor |
| --- | --- |
| `channel` | `web` |
| `conversation_key` | o UUID da sessão |
| `sender_external_id` | o UUID da sessão |
| `recipient_external_id` | a constante `widget` |

`recipient_external_id` não é decoração: `indicador_de_digitacao` e `_avisar_lead_da_janela_humana` leem esse campo como o "de" do canal, e o primeiro desiste cedo quando ele é nulo.

**A identidade é a sessão, e não a pessoa.** Quem abrir o widget noutro navegador é outra conversa. Unificar isso com o telefone é a TEC-129, e a própria card já a exclui do escopo.

## D3 — A entrada passa pelo `IngestionService`, inteira, sem desvio

Frame de mensagem:

```json
{"tipo": "mensagem", "id": "<uuid gerado pela página>", "texto": "…"}
```

O endpoint monta um `ParsedMessage` e chama `IngestionService.ingest([…], channel=CANAL_WEB)`. Nada mais. Com isso a card herda, sem escrever linha nenhuma: persistir antes de enfileirar, o rate limit por número (a chave já é `(channel, conversation_key)`), o debounce de rajada, o atalho que fura a janela para opt-out e pedido de humano, e o registro de duplicata descartada.

**O `id` vem do cliente e vira `provider_message_id`.** É o que faz o reenvio depois de uma queda cair na UNIQUE `(channel, provider_message_id)` que já existe — dedup sem código novo, pelo mesmo mecanismo que absorve a reentrega da Meta. Sem `id` no frame, o servidor gera um: um cliente ingênuo funciona, só não ganha a dedup.

> **Correção (24/09/2026, revisão final):** gravado cru, o `id` era chave **global** do canal — a UNIQUE é `(channel, provider_message_id)`, e no web quem cunha o id é a página, não a Meta. Dois visitantes que mandassem `"m-1"` colidiam: o segundo recebia `recebido` e perdia a mensagem. O `provider_message_id` gravado passou a ser `{sessão}:{id}`, e o `id` precisa ser texto de 1 a 128 caracteres — fora disso a conexão fecha com 1002. Antes do teto, um id acima dos 255 da coluna estourava no banco e fechava com 1011, um código de erro de servidor sobre o qual o cliente reenviaria para sempre.

`raw_payload` recebe o frame cru, cifrado como todo o resto. `content_type` é sempre `TEXTO` — áudio e mídia no web são a TEC-131 e a TEC-132.

**Teto de tamanho por frame.** Texto acima do limite é recusado com um frame de erro e a conexão **continua aberta**: derrubar o socket transformaria um engano de colar texto grande em perda da conversa inteira.

> **Correção (26/09/2026, TEC-364):** os frames de confirmação e de erro trocaram de nome, para o contrato das telas do chat web. A confirmação é `{"tipo": "ack", "messageId": "<id>"}` — era `{"tipo": "recebido", "id"}` — e continua confirmando o id, e não o conteúdo: o reenvio deduplicado recebe `ack` de novo. O erro é `{"tipo": "erro", "codigo", "mensagem", "messageId"?}` — era `{"tipo": "erro", "motivo"}` —, com os mesmos códigos de antes, uma frase em português que a tela pode mostrar como está, e o `messageId` quando a recusa é de uma mensagem. E a ficha de imóvel passou a chegar ao web como `{"tipo": "imovel", "imovel": ImovelCard, "texto": <prosa ou null>, "kind"}`, com ou sem foto, em vez do frame `imagem` com a legenda de texto. Nenhum cliente consumia o protocolo, então não houve convivência entre os formatos. Ver o desenho da TEC-364.

**O que o WebSocket não pode fazer é o que o webhook já não faz:** nenhuma chamada a modelo dentro do ciclo da conexão. A RN-01.2 escreve isso para o webhook, e a razão — o ciclo de requisição não é lugar de LLM — vale igual aqui.

## D4 — `WebOutbound` publica, e nunca levanta

`domain/outbound/web.py`, herdando de `GuardedOutbound` — que é a rota segura, e a única forma de o canal novo nascer com as guardas de opt-out e de atendimento humano que o docstring de `OutboundPort` avisa não serem automáticas.

`_deliver` publica em `mobia:web:{payload["para"]}` o texto que sairia pelo WhatsApp. Cada conexão aberta assina esse canal do Redis enquanto vive.

**Este adaptador não levanta `EnvioRetentavel`, e isso é divergência deliberada do contrato de `OutboundPort`.** Lá, falha de rede é retentável porque no WhatsApp a rede é o único caminho até o lead: sem ela, ele nunca recebe. Aqui não é. Assim que `send` devolve, o turno grava a fala do agente em `messages` pelo `MessageRecorder`, e a reconexão a mostra (D6). Como este adaptador nunca levanta, a gravação não depende de haver alguém ouvindo — a publicação é o atalho que a faz chegar **agora**, não o caminho que a faz chegar. Retentar custaria uma chamada nova e paga ao modelo para reentregar o que a gravação seguinte já vai guardar, por causa de uma aba que a visitante fechou.

> **Correção (24/09/2026, durante a implementação):** a primeira versão deste parágrafo dizia que a fala era gravada *antes* de qualquer publicação. É o contrário: em `turno.py` o `outbound.send` vem antes do `record_agent_message`. A garantia continua valendo pelo motivo escrito acima, mas sobra uma janela que a versão anterior escondia — o worker cancelado **entre** publicar e gravar. A reserva em `outbound_dispatches` já está commitada, a retentativa cai na supressão de reentrega, e a fala nunca chega a `messages`; se ninguém ouvia, a visitante não a vê nem na reconexão. O WhatsApp tem a mesma janela, e fechá-la exigiria inverter a ordem do turno para os dois canais.

Então: publicação sem ouvinte é o caso **normal** e sai em `info`; falha do Redis sai em `warning` e o turno segue como entregue. `EnvioForaDaJanela` nunca sai daqui — o web não tem janela.

**Isso vira emenda no docstring de `OutboundPort`**, porque aquele texto é o documento que diz qual exceção significa qual desfecho, e a partir desta card ele passa a ter um adaptador que escolhe nenhuma.

## D5 — O roteador lê a linha; o indicador escolhe no sítio de chamada

`ctx["outbound"]` hoje é uma instância única de `WhatsAppOutbound`, cega a canal. Passa a ser `RoteadorPorCanal`, que recebe `{canal: OutboundPort}`, lê `messages.channel` do `message_id` que lhe deram, e delega.

Custa um SELECT por chave primária a cada envio. Em troca, **nenhum dos sítios de chamada muda** — inclusive os seis dentro de `turno.py`, que tem mais de quatro mil linhas, e `_avisar_lead_da_janela_humana`, que fala com o lead de dentro da notificação de handoff. E um caminho de envio novo, escrito por quem não leu esta card, nasce roteado em vez de mandar tudo por WhatsApp.

O roteador **não herda de `GuardedOutbound`**: as guardas e a reserva em `outbound_dispatches` moram no adaptador de destino, e duplicá-las aqui reservaria duas vezes o mesmo envio. Linha inexistente levanta, alto — é defeito de chamador, não indisponibilidade.

**O indicador de digitação é outro caso, e não pode ser esquecido.** `indicar_digitacao(provider_message_id, de)` não recebe `message_id`, então não há o que rotear por linha. E o perigo é concreto: no web os dois campos que fazem `indicador_de_digitacao` desistir cedo — `provider_message_id` e `recipient_external_id` — **estarão preenchidos** (o id do cliente e a constante `widget`), então o `WhatsAppIndicador` de hoje dispararia um POST para a Meta com um UUID de sessão no lugar do `wamid`. A escolha passa a ser por canal no sítio de chamada de `process_message`, que já tem `linha.channel` em mãos, com `IndicadorNoop` para o web.

**Lacuna declarada:** o web fica sem indicador de digitação. Publicá-lo exigiria pôr a sessão na assinatura do `IndicadorDePresencaPort` — mexida de contrato que esta card não faz. Vai no comentário.

> **Emenda E-01 (TEC-362, 24/09/2026): a lacuna fechou, e o contrato mudou como esta seção previa.**
> `IndicadorDePresencaPort.indicar_digitacao` ganhou `para`, alimentado por `message.sender_external_id` — que no canal web **é a sessão**, enquanto o `recipient_external_id` usado por `de` é a constante `widget`. Era exatamente essa distribuição de campos que impedia a publicação.
> O `IndicadorNoop` do web saiu; quem entrou foi o `WebIndicador`, em `domain/outbound/web.py`, que publica em `canal_da_sessao(para)` o mesmo Redis do `WebOutbound`.
> **O formato do frame**, que a card manda registrar aqui:
> ```json
> { "tipo": "digitando", "ate": "<ISO-8601 com fuso>" }
> ```
> `ate` é quando o cliente deve parar de mostrar o indicador, e vale `agora + 25 s` — o mesmo prazo em que o indicador da Meta expira (Emenda E-01 da RN-04.7), por paridade entre os canais. **Continua não havendo quem o desenhe no navegador:** isso é a TEC-351.

## D6 — Histórico: as últimas 50, decifradas, sem a fala bloqueada

Na retomada, o servidor lê as últimas 50 linhas (configurável) de `(web, sessão)` com `role IN (LEAD, AGENTE)`, decifra `text_body` e manda um frame `historico` em ordem cronológica, antes de qualquer fala nova.

Fica de fora a linha com `bloqueada_em` preenchido, pelo mesmo critério da TEC-236 e da Emenda E-01 da RN-02.2: a fala que a moderação bloqueou não entra em contexto nem em resumo, e devolvê-la à tela seria o único lugar do sistema em que ela reaparece.

**É daqui que vem a garantia da card de não perder o que já foi dito**, e ela vale dos dois lados: a mensagem da visitante porque o `IngestionService` a commitou antes de enfileirar, e a resposta do agente porque o turno a grava assim que o `WebOutbound` devolve — e ele nunca levanta. A queda do socket não participa de nenhum dos dois. A exceção é a janela da D4: o worker cancelado entre publicar e gravar.

## D7 — O limite por IP não alcança WebSocket hoje, e o comentário diz que alcança

`RateLimitPorIP` é `BaseHTTPMiddleware`, e essa classe devolve cedo para todo escopo que não seja `http`: **o handshake de um `ws://` nunca é contado**. O comentário de `create_app` diz que o middleware se aplica por omissão justamente "para não errar para o lado de esquecer o widget do TEC-124" — e é exatamente esse o erro que ele deixa passar. A RNF-16 pede "100 req/min por IP **no widget**", e a Emenda E-01 dela fecha dizendo que o limite "se aplica a toda rota **HTTP** restante": o texto está certo, e é por isso que ele não cobre este caso.

Então o endpoint consome `chave_de_ip` com o mesmo limite e a mesma janela do middleware **antes de aceitar a conexão**, e fecha com 1013 quando estoura. O comentário de `create_app` é corrigido na mesma branch — comentário desatualizado é defeito, e este já nasceu prometendo o que não cumpre.

> **Correção (24/09/2026, revisão final):** o 1013 nunca chegava ao navegador. O uvicorn transforma o fechamento antes do `accept` em HTTP `403` nas três implementações de WebSocket, e o cliente via `onclose` 1006 — "proibido" no lugar de "tente de novo". O teste passava porque olhava o evento ASGI, não o fio. O handshake excedente passou a ser recusado com `send_denial_response`: HTTP `429` com `Retry-After`, a mesma resposta do middleware.

O limite por número continua valendo por dentro, via `IngestionService`: uma conexão aceita não é licença para inundar.

## D8 — Reengajamento não alcança o web

`sweep_followups` e a seleção de candidatos passam a filtrar por `CANAIS_COM_REENGAJAMENTO`. **Allowlist, e não `channel <> 'web'`**: canal novo nasce de fora do reengajamento e entra quando alguém decidir que ele tem para onde empurrar mensagem.

A razão é que o web não tem push. Um follow-up de 24h numa sessão de navegador não chega a ninguém: vira linha em `followups` marcada como enviada, e texto que a visitante só veria se voltasse por conta própria — caso em que ela não precisava do follow-up.

`_avisar_lead_da_janela_humana` **não** é filtrada. Ela não é reengajamento: é resposta dentro de uma conversa viva, e chega pela sessão aberta via o roteador da D5.

O encerramento por inatividade da TEC-130 alcança o web sem nada a fazer, e é desejável — sessão de navegador abandonada é o caso mais comum que existe.

## Emendas ao SRS

- **RN-01.1** — a identidade do canal web é o UUID de sessão emitido pelo servidor, não o telefone. A segunda frase da regra ("um mesmo lead identificado pelo telefone tem histórico unificado entre canais") descreve a TEC-129 e não esta card: aqui, duas sessões da mesma pessoa são duas conversas.
- **RN-13.1** — a cadência de reengajamento vale só para canal com push. O web fica de fora, por construção (D8).
- **RNF-16** — o limite por IP passa a ser aplicado também no handshake do WebSocket, por dentro do endpoint. A Emenda E-01 limita o middleware às rotas HTTP, e o widget não é uma.

## Testes

- **unit** — vocabulário de canal; `RoteadorPorCanal` escolhendo e levantando; `WebOutbound` com dublê de Redis, inclusive sem ouvinte e com Redis fora; o parser dos frames, com frame fora de ordem, texto acima do teto e `id` ausente.
- **integration** — o endpoint com o cliente WebSocket do Starlette: sessão nova, retomada com histórico, dedup por `id` do cliente, handshake recusado no limite por IP, e a resposta chegando pela publicação.
- **features** — os três cenários Gherkin da card, incluindo o terceiro: com o WhatsApp fora do ar, o canal web atende.

Nomes de arquivo distintos entre `tests/unit` e `tests/integration` — basename repetido aborta a coleta da suíte inteira e não aparece quando se roda o arquivo sozinho.

## Custo

Quatro arquivos novos: `api/routes/widget.py`, `domain/messages/canais.py`, `domain/outbound/web.py`, `domain/outbound/roteador.py`. Edições em `app/main.py`, `api/middleware.py` (o comentário da D7), `workers/main.py`, `domain/messages/service.py`, `domain/followup/repositorio.py`, `workers/jobs/process_message.py` (o indicador da D5), `app/config.py`, e o docstring de `domain/outbound/port.py`.

**Nenhuma migration.** A coluna `channel` já existe, não tem CHECK, e nada mais precisa de espaço novo.

## O que este desenho não entrega

- **O widget.** Não há HTML nem JS nesta árvore, e não passa a haver. Esta card entrega o canal do lado servidor; a página que conecta nele não existe, e a stack do front será decidida nas cards de dashboard. **Consequência prática, dita sem rodeio: ninguém consegue conversar pelo site quando este PR entrar** — existe o canal, não existe o chat.
- **O indicador de digitação no web** (D5). *Entregue depois, pela TEC-362 — ver a Emenda E-01 da D5.*
- **Histórico unificado entre canais** — é a TEC-129, e a própria card exclui.
- **Reengajamento no web** (D8) — é decisão de produto, não lacuna de código.
- **Autenticação.** A sessão é portador anônimo: quem tiver o UUID lê aquela conversa. É a mesma exposição de um link mágico, mitigada por ser UUIDv4 e por não viajar em URL (D2). Autenticar visitante de site é outro problema, e não é o desta card.

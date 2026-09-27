# TEC-365 — Validar a origem no handshake do WebSocket do chat web

**Status:** implementado
**Card:** [TEC-365](https://eduardodurieuxlopes.atlassian.net/browse/TEC-365) — épico TEC-123
**Branch:** `feat/tec-365-origem-no-handshake`
**Depende de:** TEC-124 (`WS /widget/chat`), TEC-344 (a página `/embed/chat` que abre a conexão)
**Bloqueia:** TEC-345 (domínios cadastrados)

## O que existe quando a card começa

- **O handshake não olha o `Origin`.** `chat` (`src/mobia/api/routes/widget.py::chat`) só confere o limite por IP (`_cabe_no_limite_por_ip`) antes do `accept`. Qualquer página, em qualquer domínio, abre a conexão e conversa com o agente do tenant.
- **Quem abre a conexão é o iframe, não o site da imobiliária.** A TEC-346 escreve isso na regra: "O `iframe` conecta direto ao `WS /widget/chat`". O `widget.js` da TEC-344 só desenha o botão e cria o iframe `<painel>/embed/chat`. O navegador manda como `Origin` a origem **do documento que abre o socket**, que é a do painel, e não a do site que embute o iframe.
- **Não existe lista de domínios do tenant.** Ela é da TEC-345, que ainda não decidiu nem onde o administrador a cadastra.
- **Não existe backend de métricas.** Sem Prometheus nem contador: a instrumentação é a TEC-211, ainda em "A fazer". O que conta evento hoje é log estruturado, e `rate_limit_events` para o limite por IP.

## D1 — A lista permitida é a origem do painel, e não os domínios do tenant

A card diz "contra a origem do iframe do mobIA **e/ou** a lista de domínios do tenant". Fica só a primeira.

A página que abre o socket é sempre `/embed/chat`, servida pelo painel. Num navegador, o `Origin` do handshake é então a origem do painel, qualquer que seja o site que embute o iframe. **O domínio do tenant nunca aparece nesse header** numa conexão legítima.

Pôr os domínios do tenant na lista não protegeria nada a mais e abriria uma porta: um script qualquer no site da imobiliária poderia falar com o WebSocket sem passar pelo iframe, e portanto sem o aviso de privacidade que a TEC-352 põe nele. Quem restringe **em que site** o chat aparece é o `frame-ancestors` da TEC-345. As duas travas se completam:

- a da TEC-345 impede outro site de embutir o iframe;
- a desta card impede outra página de abrir o socket sem o iframe.

## D2 — `ORIGENS_DO_WIDGET`, vazia por padrão, e vazia recusa tudo

- **`origens_do_widget`** em `Settings`: texto separado por vírgula, no molde de `whatsapp_templates_aprovados`. O conjunto já normalizado sai da propriedade `origens_permitidas_do_widget`.
- **Vazia por padrão, e vazia quer dizer que nenhum handshake passa.** É o mesmo lado seguro do `TENANT_SLUG` (D2 da TEC-344): um deploy que esqueceu a variável fica sem chat, e não com um chat aberto a qualquer página. Hoje isso não custa nada, porque sem `TENANT_SLUG` nenhum botão aparece.
- **Cada entrada é conferida na subida** (`Settings._origens_do_widget_sao_origens`). Tem de ser `http` ou `https`, com host e porta opcional, sem caminho, sem barra final, sem query e sem porta padrão. `https://painel.x/` ou `https://painel.x:443` nunca casariam com o que o navegador manda, e o chat morreria em todo site sem uma linha de log que explicasse o porquê. É o argumento que já justificou `_tenant_slug_no_formato_do_next`.
- Maiúsculas no esquema e no host são normalizadas para minúsculas, nos dois lados da comparação: host não diferencia caixa.
- Em desenvolvimento o painel roda em `http://localhost:3000`, e o `.env.example` traz esse valor comentado.

Não entra guarda de produção recusando `http://`. A card não pede, e a TEC-219 (deploy) é quem decide o esquema do ambiente real.

## D3 — Recusa com `403` antes do `accept`, depois do limite por IP

- **`403` por `send_denial_response`**, o mesmo mecanismo do `429` (`_recusar_por_excesso`). "Proibido, não tente de novo" é exatamente a leitura certa aqui, e não era no `429`. Sem a extensão `websocket.http.response`, o `close()` antes do `accept` vira `403` no uvicorn do mesmo jeito.
- **Sem `Origin` também é recusado.** Todo navegador manda o header num handshake de WebSocket, e o único cliente legítimo é um navegador. O valor `null` (documento sandboxed, `file://`) é recusado pelo mesmo caminho, porque não está na lista.
- **A checagem vem depois do limite por IP.** Toda tentativa conta contra o balde do IP, inclusive a recusada. Na ordem inversa, quem martela o handshake de outra página nunca seria contido, e cada tentativa ainda geraria uma linha de log.

## D4 — Log, e a métrica fica com a TEC-211

- A recusa emite **`widget.origem_recusada`** (warning) com `origem` e `ip`. A `origem` vem truncada em 200 caracteres: é texto que o cliente escolhe, e sem teto encheria o log. O `ip` segue o que `ratelimit.blocked` já registra.
- **A card pede métrica, e não há onde pô-la.** Não existe backend de métricas (TEC-211). O nome do evento é estável para virar contador quando a TEC-211 chegar. Gravar numa tabela, como faz `rate_limit_events`, criaria um segundo mecanismo que a TEC-211 teria de absorver. Esta é uma divergência declarada.

## Testes

- **Unitários de `Settings`:** lista vazia, várias origens com espaços, normalização de caixa, e recusa na subida de caminho, barra final, esquema `ws`, porta padrão e texto sem esquema.
- **Unitários de `origem_permitida`:** casa exato, caixa diferente, `None`, `"null"`, lista vazia e subdomínio de uma origem permitida.
- **Integração do handshake (`ClienteWebSocket`):**
  - origem permitida é aceita (o primeiro cenário da card);
  - `https://copia-do-site.com` recebe `403`, não chega ao `accept` e deixa `widget.origem_recusada` no log (o segundo cenário);
  - sem `Origin`, `403`;
  - com a lista vazia, `403` até da origem do painel.
- **`ClienteWebSocket` passa a mandar `Origin`**, e `app_do_widget` configura a lista com a mesma origem. Sem isso, todos os testes do widget passariam a receber `403`.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Origem permitida: handshake aceito | integração, com a origem do painel na lista |
| Origem desconhecida: recusado e registrado em log | integração com `https://copia-do-site.com`: `403`, sem `accept`, evento no log |

## Lacunas declaradas

- **L1 — Cliente fora do navegador forja o `Origin`.** `curl` ou um script mandam o header que quiserem. Esta trava vale contra **páginas**, que é o risco da RT-FE-09. Contra quem não é navegador, a defesa continua sendo o limite por IP.
- **L2 — Sem métrica.** Ver D4.
- **L3 — Os domínios do tenant não entram.** Ver D1. A TEC-345 deve saber disso: o `frame-ancestors` dela é a única trava sobre em que site o chat aparece.
- **L4 — Quem liga o chat precisa configurar duas variáveis.** `TENANT_SLUG` para o botão aparecer e `ORIGENS_DO_WIDGET` para a conversa conectar. Com só a primeira, o botão aparece e a conversa da TEC-346 é recusada com `403`.

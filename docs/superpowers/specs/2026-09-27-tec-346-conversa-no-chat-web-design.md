# TEC-346 — Conversar pelo site com estados de envio e identificação do assistente

**Status:** implementado (27/09/2026)
**Card:** [TEC-346](https://eduardodurieuxlopes.atlassian.net/browse/TEC-346) — épico TEC-307
**Branch:** `feat/tec-346-conversa-no-chat-web`
**Depende de:** TEC-124 (`WS /widget/chat`), TEC-364 (`ack` e `erro`), TEC-344 (o embed e a página `/embed/chat`)
**Bloqueia:** TEC-347 (retomar), TEC-348 (reconectar), TEC-349 (cards de imóvel), TEC-351 (digitando e estado da conexão), TEC-352 (aviso de privacidade)

## O que existe quando a card começa

- **O protocolo do WebSocket está pronto.**
  - O cliente manda `ola` e depois `mensagem` com `id`.
  - O servidor responde `sessao`, `historico` (só na retomada), `ack {messageId}` e `erro {codigo, mensagem, messageId?}`.
  - As falas do agente chegam como `mensagem {texto, kind}`, uma por frame. Também chegam `imagem`, `imovel`, `digitando` e `consentimento_registrado`.
  - O teto do servidor é de 4096 caracteres por mensagem. Acima disso vem um `erro` com `messageId`, e o socket continua aberto.
- **Nenhum cliente consome o WebSocket.** A página `/embed/chat` só desenha o cabeçalho (L3 da TEC-344).
- **O navegador não enxerga a recusa por limite.** `_recusar_por_excesso` responde HTTP `429` com `Retry-After: 60` antes do `accept`, e a API `WebSocket` do navegador não expõe nem o status nem os cabeçalhos de um handshake recusado: a página só vê `onerror` e depois `onclose` com 1006, igual a qualquer queda de rede. E o valor é sempre 60, a janela inteira, e não o que falta dela.
- **O navegador não sabe onde fica o WebSocket.** Nenhuma variável do frontend aponta para a API pública. E a CSP não tem `connect-src`: vale `default-src 'self'`, que barra um WebSocket para outra origem.

As regras RN-FE-17.x e RN-FE-20.1 vêm do texto da card, porque o SRS do frontend não está no repo (L1 da TEC-344).

## D1 — A recusa por limite vira um frame de erro, e o N é o que falta da janela

Decisão do Eduardo, 27/09/2026.

**O servidor aceita o handshake que passou do limite, manda um `erro` e fecha com 1013** ("Try Again Later", RFC 6455):

```json
{"tipo": "erro", "codigo": "muitas_tentativas", "mensagem": "Muitas tentativas, aguarde 20 s.", "aguardeSegundos": 20}
```

- **O formato é o da TEC-364.** `mensagem` já está em português, pronta para a tela, e usa a frase do terceiro cenário da card. `aguardeSegundos` é o número que a tela usa para reabilitar a conexão.
- **Aceitar custa um `accept` a mais por conexão barrada.** É o preço de a visitante ler "espere" em vez de uma falha genérica. O limite continua contando o handshake antes de qualquer outra coisa: o banco não é tocado, nenhuma sessão é criada e nenhum `ola` é lido.
- **O N é o tempo até caber de novo um pedido**, e não a janela inteira. O limitador é uma janela deslizante (zset no Redis), que mantém os `limite + 1` pedidos mais recentes. Um pedido novo cabe quando sobram no máximo `limite - 1` pedidos antigos na janela, ou seja, quando os dois mais velhos do zset saem dela. A espera é `score[1] + janela - agora`, arredondada para cima e nunca menor que 1 s.
- **Com o Redis fora, a espera vale 60 s.** O limitador já deixa passar tudo nesse caso (fail-open), então esse ramo só aparece se o Redis cair entre a contagem e a leitura.
  - **Nota (27/09/2026):** os 60 s valem também quando o zset tem menos de 2 entradas, em que `score[1]` não existe. E o handshake barrado custa, além do `accept`, um `ZRANGE` a mais no Redis para ler a espera, e segura o socket aceito até o fim do handshake de fechamento — um custo limitado.
- **Emenda à D7 da TEC-124**, que escolheu o `429` com `Retry-After`: a escolha era a certa para um cliente HTTP, e o cliente desta rota é um navegador, que não lê status de handshake. O `Retry-After` HTTP deixa de existir nesta rota.

Descartadas: tratar 1006 antes do frame `sessao` como "muitas tentativas" (mentiria para toda queda de rede, e o N seria sempre 60); tirar o cenário da card.

## D2 — O endereço do WebSocket vem do servidor Next, e a CSP de `/embed/*` o autoriza

- **`MOBIA_WIDGET_WS_URL`**, variável do servidor Next. Sem ela, o padrão é derivado de `MOBIA_API_BASE`: `http` vira `ws`, `https` vira `wss`, e o caminho é `/widget/chat`.
- **Não é `NEXT_PUBLIC_`.** A página `/embed/chat` é server component: ela lê a variável e passa o endereço por prop ao componente cliente. É a regra do README do frontend, de nenhuma variável `NEXT_PUBLIC_`.
- **A CSP de `/embed/*` ganha `connect-src 'self' <origem do WebSocket>`.** A origem sai da mesma função que monta o endereço, então as duas não divergem. O painel continua sem `connect-src`.
  - **Nota (27/09/2026):** com `MOBIA_WIDGET_WS_URL` ou `MOBIA_API_BASE` malformada, o proxy loga o erro e omite o `connect-src`, em vez de responder 500: as outras rotas de `/embed/*` — `/embed/aparencia`, que o botão do site lê — continuam de pé. A página `/embed/chat` falha alto por conta própria, porque chama `enderecoDoChat()`.

## D3 — A conversa é um módulo sem React, com um redutor puro

`frontend/src/lib/conversa.ts`, testável sem DOM e sem socket:

- **Estado:** as mensagens em ordem, cada uma com autor (visitante ou agente), texto, e, para as da visitante, `messageId` e `estado` (`enviando`, `recebida`, `falhou`); e o estado da conexão, inclusive a espera por `muitas_tentativas`.
- **Eventos:** `enviar`, `frame recebido`, `socket fechou`, `prazo do ack venceu`, `reenviar`.
- **Os frames que esta card trata:**
  - `sessao` grava o UUID;
  - `mensagem` do agente vira um balão por frame, na ordem de chegada (segundo cenário);
  - `ack` marca `recebida`;
  - `erro` com `messageId` marca `falhou`;
  - `muitas_tentativas` guarda a mensagem e a espera;
  - `imovel` vira um balão com o texto que o acompanha, quando houver (os cards são da TEC-349);
  - `digitando`, `imagem`, `historico` e `consentimento_registrado` são ignorados aqui (TEC-351, TEC-349, TEC-347 e TEC-352).
- **O `messageId` é UUIDv4** de `crypto.randomUUID()`, com gerador de reserva por `crypto.getRandomValues` para contexto sem `randomUUID`.
- **`falhou` tem três causas:** `erro` com o `messageId`, socket fechado com a mensagem ainda em `enviando`, e 10 s sem `ack`.
- **"Reenviar" usa o mesmo `messageId`.** O servidor deduplica pela UNIQUE (D3 da TEC-124) e confirma de novo (D1 da TEC-364). Com o socket fechado, reenviar reabre a conexão. A reconexão **automática** é da TEC-348.
  - **Nota (27/09/2026):** os eventos implementados incluem também `abriu` e `reabrindo`. O `reabrindo` encerra a espera de `muitas_tentativas` quando o socket novo começa a abrir, para que uma reabertura que falhe não congele o chat na espera. E não só reenviar: enviar com o socket fechado também reabre a conexão.

## D4 — O UUID da sessão é gravado, mas ainda não é usado para retomar

A card manda guardar o UUID emitido pelo servidor no `localStorage` da origem do iframe. **A retomada a partir dele é da TEC-347**: validade de 30 dias, mostrar o `historico`, "Encerrar conversa".

Esta card grava o UUID ao receber `sessao` e manda sempre `ola` com `sessao: null`. Retomar sem mostrar o histórico deixaria a visitante numa tela vazia enquanto o agente lembra da conversa, que é pior do que começar de novo. O acesso ao `localStorage` fica em try/catch: modo privado ou storage bloqueado não vira erro.

- **Nota (27/09/2026):** o "sempre `sessao: null`" vale só para a primeira conexão de cada carregamento da página. As reconexões na mesma página — reenviar, enviar com o socket fechado, o fim da espera de `muitas_tentativas` — mandam a sessão que o servidor emitiu nela, guardada em memória, nunca lida do `localStorage`. Sem isso cada queda abria uma sessão nova no servidor: o agente perdia o contexto, e a deduplicação por `messageId`, que é por sessão, não valia entre as duas — uma queda entre a gravação e o `ack` duplicava a mensagem. Nessas reconexões a tela já mostra os balões, então o argumento acima (tela vazia com o agente lembrando) não se aplica; o `historico` que o servidor devolve continua ignorado.

## D5 — A tela

- **Cabeçalho:** "Lia · Assistente virtual" com nome configurado, "Assistente virtual" sem ele (quarto cenário), visível durante toda a conversa. É texto que a visitante lê: com acento.
- **Lista de mensagens com `aria-live="polite"`**, um balão por fala. O balão da visitante mostra o estado em texto ("Enviando…", "Recebida", "Não enviada") e, em `falhou`, o botão "Reenviar".
- **Campo com limite de 1000 caracteres**, `maxLength` e contador. O teto de 4096 do servidor continua sendo a rede.
- **`muitas_tentativas`:** a mensagem do servidor aparece no lugar do campo, e o chat reabre a conexão sozinho depois de `aguardeSegundos`.
- **Cores só por classe e pela variável `--cor-primaria`** do `<style nonce>` da TEC-344, nunca por atributo `style` (a CSP de produção não tem `'unsafe-inline'` em `style-src`).
  - **Nota (27/09/2026):** "Reenviar" fica desabilitado enquanto a espera de `muitas_tentativas` corre — reenviar ali só estenderia o bloqueio. Enter envia e Shift+Enter quebra a linha; o Enter que confirma uma composição de IME não envia. A lista fica dentro de um `role="log"` com `aria-relevant="additions"`, para que a troca de "Enviando…" por "Recebida" não seja anunciada a cada mensagem; o papel fica num invólucro porque `log` não é permitido num `<ol>`. E ela só rola sozinha até o fim se a visitante já estava perto do fim, ou se a mensagem nova é dela.

## Testes

- **Backend:** a função pura da espera (vários volumes e instantes, borda de 1 s); `test_widget_limite_por_ip.py` passa a afirmar o frame `muitas_tentativas`, o `aguardeSegundos` e o fechamento 1013; o evento de bloqueio continua gravado.
- **Redutor:** cada transição de estado da D3, os três caminhos para `falhou`, o reenvio com o mesmo id, os três balões em ordem, os frames ignorados.
- **Componente:** com um WebSocket falso (`vi.stubGlobal`, sem dependência nova), os quatro cenários do Gherkin.
- **CSP:** `connect-src` com a origem do WebSocket em `/embed/*`, e o painel sem ele.
- **Navegador:** verificação no Edge com o backend de pé, como na TEC-344.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Mensagem confirmada pelo servidor | redutor e componente: `enviando` → `recebida` no `ack`; navegador |
| Resposta com várias falas | redutor e componente: três frames, três balões em ordem |
| Limite de tentativas ("aguarde 20 s") | backend: espera calculada da janela; componente: mensagem do frame |
| Identificação como assistente virtual | componente do cabeçalho |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — `upgrade-insecure-requests` pode transformar `ws://` em `wss://`** numa página servida por HTTP. Em produção a página é HTTPS e o WebSocket é `wss://`, então não há o que transformar; em desenvolvimento, a verificação no navegador decide se a diretiva precisa sair de `/embed/*` fora de produção.
  - **Nota (27/09/2026):** resolvida pela verificação no Edge de 27/09/2026: `ws://localhost` conectou sob o `upgrade-insecure-requests` da CSP. A CSP não precisou mudar.
- **L3 — Até a TEC-347, cada abertura do chat é uma conversa nova** (D4).
- **L4 — O WebSocket não confere a origem** (TEC-365). Com o `connect-src` desta card, a página embutida alcança o WebSocket; quem o alcança de outras páginas continua sem barreira até lá.
- **L5 — A reconexão é só manual.** Queda de conexão marca as pendentes como `falhou`; reconectar sozinho é da TEC-348.

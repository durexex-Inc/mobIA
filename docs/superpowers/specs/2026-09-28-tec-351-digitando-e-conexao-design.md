# TEC-351 — Mostrar o indicador de digitação e o estado da conexão no chat

**Status:** implementado (28/09/2026)
**Card:** [TEC-351](https://eduardodurieuxlopes.atlassian.net/browse/TEC-351) — épico TEC-307
**Branch:** `feat/tec-351-digitando-e-conexao`
**Depende de:** TEC-362 (o frame `digitando`), TEC-346 (a conversa), TEC-348 (os estados da queda)

## O que existe quando a card começa

- **O servidor já emite `digitando` no canal web.** A TEC-362 entrou na `main` (`54b58e31`): o worker liga o `WebIndicador` ao canal web, e ele publica `{"tipo": "digitando", "ate": "<ISO 8601>"}` 4 s depois de a mensagem entrar, com `ate` = agora + 25 s (`src/mobia/domain/outbound/web.py`, a constante `DURACAO_DO_INDICADOR`). O redutor do chat ignora o frame.
- **O cabeçalho só tem o nome e o menu.** O estado da conexão aparece numa linha acima do campo desde a TEC-348 ("Reconectando…", "Sem conexão."), e a D6 de lá deixou para esta card decidir o lugar.

A regra RN-FE-19.x vem do texto da card: o SRS do frontend não está no repo.

## D1 — Não há indicador provisório: o servidor já emite o evento

A card pede um indicador local, a partir de 4 s depois do `ack`, **"enquanto o backend não emitir o evento no canal web"**, e o chama de provisório. Essa condição já não vale: a TEC-362 emite o evento. Fazer os dois poria dois indicadores disputando a mesma tela, e o local mentiria nos turnos em que o servidor decide não mostrar. As guardas de opt-out e de atendimento humano moram no agendador do servidor, e o local não as enxerga.

O primeiro cenário da card ("Indicador provisório após 4 segundos") não é exercitado, porque a premissa dele ("o servidor ainda não envia o evento") é falsa desde a TEC-362. O que ele pede — o indicador aparecer uns 4 s depois da mensagem e sumir quando a resposta chega — acontece pelo evento do servidor, que dispara no mesmo prazo.

## D2 — O indicador

- **Texto:** "Lia está digitando…" com nome configurado; "O assistente está digitando…" sem ele. É texto que a visitante lê: com acento.
- **Some com a próxima fala do agente:** frame `mensagem`, `imovel` ou `imagem`.
- **Some também quando o socket fecha e quando a visitante encerra a conversa.** O indicador fala do socket que caiu; depois da reconexão, o que o agente disse chega pelo `historico`.
- **Prazo:** o que o `ate` do frame disser, com teto de 30 s a partir da chegada do frame (a regra da card). Hoje o servidor manda 25 s, então vale o `ate`.
  - `ate` inválido, já passado ou a mais de 30 s — relógio da visitante adiantado ou atrasado em relação ao servidor — vira 30 s.
  - O relógio do aparelho não é confiável o bastante para descartar o frame.
- **Um `digitando` novo renova o prazo.**
- **Fica fora do `role="log"`**, numa linha própria com `role="status"`, acima do campo. Dentro do log ele seria anunciado como mensagem nova da conversa.

## D3 — O estado da conexão vai para o cabeçalho

| `Conexao` do redutor | texto no cabeçalho |
| --- | --- |
| `aberta` | Conectado |
| `reconectando` | Reconectando… |
| `offline`, `fechada`, `aguardando`, `adormecida` | Offline |
| `conectando` | Conectando… |

- **"Conectando…" não está na card**, que tem três estados. Existe porque a primeira conexão de cada carregamento, e a que "Tentar de novo" abre, não é nenhum dos três: chamá-la de "Reconectando…" diria à visitante que caiu algo que nunca esteve de pé.
- **Texto e marcador.** O texto vem sempre ao lado de um ponto colorido que é só decoração (`aria-hidden`). A cor não carrega informação sozinha.
- **`role="status"`:** a mudança de estado é anunciada.
- **A linha acima do campo da TEC-348 fica só com o que o cabeçalho não diz:** a frase de atendimento instável (`1011`) e o botão "Tentar de novo". "Reconectando…" e "Sem conexão." saem de lá, porque repetiriam o cabeçalho.

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `/embed/chat` no `next dev`, API local. O `digitando` foi publicado direto no canal Redis da sessão, com `ate` = agora + 25 s, como o `WebIndicador` faz.

| passo | resultado |
| --- | --- |
| página aberta | cabeçalho "Conectado", com o ponto |
| `digitando` publicado | "O assistente está digitando…" acima do campo (sem nome configurado); some sozinho aos 25 s |
| API parada | cabeçalho "Reconectando…"; nenhuma linha repetindo o estado acima do campo |

"Offline" aos 5 minutos não foi repetido no navegador: tem teste de componente, e o caminho da desistência foi verificado no navegador na TEC-348.

## Testes

- Redutor: `digitando` liga o indicador (com o `ate` lido ou nulo); `mensagem`, `imovel` e `imagem` o desligam; `fechou` e `encerrou` também; `expirou` desliga só o indicador daquele frame.
- Cabeçalho: o texto de cada estado; o marcador `aria-hidden`.
- Componente (relógio falso):
  - O indicador com e sem nome, e ele sumindo com a resposta.
  - O prazo: o `ate` de 25 s, o teto de 30 s com `ate` a 60 s, e os 30 s com `ate` passado.
  - A renovação por um frame novo.
  - O cabeçalho em cada estado do esquema da card.
- Navegador: o frame publicado no Redis e a troca de estado derrubando a API.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Indicador provisório após 4 segundos | **não exercitado** — a premissa é falsa desde a TEC-362 (D1) |
| Indicador do servidor expira em 30 segundos | componente com relógio falso |
| Estado da conexão no cabeçalho | cabeçalho e componente, com os três textos |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — O turno que passa de 25 s fica sem indicador no fim.** O servidor não renova o evento (L1 da TEC-274, D2 da TEC-362). A tela obedece o `ate`, então um turno de 40 s mostra o indicador dos 4 aos 29 s.
- **L3 — A visitante que recarrega a página durante o turno não vê o indicador.** O evento só vai a quem estava conectado quando ele saiu.

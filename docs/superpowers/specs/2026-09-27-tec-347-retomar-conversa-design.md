# TEC-347 — Retomar a conversa ao recarregar a página e poder encerrá-la

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-347](https://eduardodurieuxlopes.atlassian.net/browse/TEC-347) — épico TEC-307
**Branch:** `feat/tec-347-retomar-conversa`
**Depende de:** TEC-346 (a conversa), TEC-124 (`historico` na retomada), TEC-344 (o loader)

## O que existe quando a card começa

- **A sessão já é gravada, mas não é lida.** `Conversa.tsx` grava o UUID em `localStorage['mobia:sessao']` como texto puro quando chega o frame `sessao`, e a primeira conexão de cada carregamento manda `ola` com `sessao: null` (D4 da TEC-346). Reconexões dentro da mesma página já reaproveitam a sessão em memória.
- **O servidor já sabe retomar.** `ola` com um UUID devolve `sessao` e `historico {mensagens: [{papel: "lead"|"agente", texto, em}]}` — as últimas 50 falas (`historico_do_widget_mensagens`), em ordem cronológica, sem as retidas pela moderação (`domain/messages/historico.py::historico_da_sessao`). O redutor ignora o `historico`.
- **O iframe não sabe quando está minimizado.** O `widget.js` só troca `display` do painel; um iframe escondido assim não muda `document.visibilityState`.

As regras RN-FE-17.2, RN-FE-17.7, RNF-FE-11 e RT-FE-04 vêm do texto da card: o SRS do frontend não está no repo.

## D1 — A sessão guardada tem validade de 30 dias desde a criação

Decisão do Eduardo, 27/09/2026: o prazo conta **desde a criação** e não renova com o uso. É a leitura literal de "no máximo 30 dias" e garante o teto de retenção no aparelho.

- **Formato:** `localStorage['mobia:sessao'] = {"sessao": "<uuid>", "criadaEm": <epoch ms>}`.
- **Gravação só quando o servidor emite uma sessão nova** — o `sessao` do frame difere do guardado. Retomar não regrava, então o prazo não anda.
- **Leitura ao montar:** vale se o JSON é um objeto, `sessao` é UUID e `agora - criadaEm < 30 dias` (e `criadaEm` não está no futuro). Qualquer outra coisa — inclusive o texto puro gravado pela TEC-346, que nunca foi a produção — é apagada, e a conexão sai com `null`.
- **Sem storage** (Safari ITP, modo privado, storage bloqueado): toda leitura e escrita em try/catch; o chat abre sessão anônima sem erro.
- Módulo puro `frontend/src/lib/sessaoGuardada.ts`, que recebe o storage e o instante — testável sem relógio real.

## D2 — O `historico` é a verdade do servidor

- **A primeira conexão manda o UUID guardado**, quando há um válido (D1).
- **Ao receber `historico`, a tela passa a ser o histórico** mais as mensagens locais da visitante ainda não confirmadas (`enviando` e `falhou`), que ficam no fim, na ordem em que estavam.
- **Isso vale também para as reconexões da TEC-346.** O que o agente disse enquanto o socket estava fechado não chega por frame — chega pelo histórico. Ignorar o `historico` na reconexão, como fazia a TEC-346, perdia essas falas.
- Fala da visitante vinda do histórico entra como `recebida`, com id sintético, e sem "Reenviar". Fala do agente entra como balão do agente.
- **Limites, registrados como lacunas:** uma resposta do agente em duas partes pode voltar como um balão só, porque o servidor pode guardá-las numa linha (L2); conversa com mais de 50 falas volta só com as 50 últimas (L3).

## D3 — "Encerrar conversa" fica num menu do cabeçalho, com confirmação

- Um botão "Opções da conversa" no cabeçalho abre um menu com "Encerrar conversa".
- Escolher pede confirmação na própria tela: "Encerrar esta conversa? O histórico some desta tela." com "Encerrar" e "Cancelar". Um toque acidental não apaga a conversa da tela.
- Confirmar apaga o storage, fecha o socket, zera a tela e abre uma conexão nova com `sessao: null`.
- **O servidor não é avisado.** A sessão antiga deixa de ser usada por este aparelho; as mensagens ficam onde já ficavam, para o painel e a trilha.

## D4 — Minimizado por 30 minutos sem atividade, o socket dorme

- **O loader avisa o iframe.** Ao abrir e ao fechar o painel, `widget.js` manda `postMessage({tipo: 'mobia:visibilidade', aberto: true|false}, origemDoChat)` para a janela do iframe.
- **O iframe só aceita o aviso do próprio pai:** `event.source === window.parent` e `event.data.tipo === 'mobia:visibilidade'` com `aberto` booleano.
- **Minimizado, corre um prazo de 30 minutos**, reiniciado por qualquer frame enviado ou recebido. Ao vencer, o chat fecha o socket num estado próprio, `adormecida`, que não aparece como falha e não marca nada como "Não enviada" que não estivesse já pendente.
- **Ao reabrir, reconecta com a sessão**, e o `historico` (D2) traz o que o agente tiver dito nesse meio-tempo.
- O loader continua dentro do teto de 5 KB gzip.

## Testes

- `sessaoGuardada`: grava, lê, 29 e 31 dias, `criadaEm` no futuro, JSON torto, texto puro antigo, UUID inválido, storage que lança.
- Redutor: `historico` substitui as confirmadas e preserva as pendentes; falas do histórico sem "Reenviar"; `encerrou` volta ao inicial; `adormeceu` e o fechamento seguinte não viram falha.
- Componente (WebSocket falso, relógio falso): os quatro cenários do Gherkin; primeira conexão com a sessão guardada; sessão de 31 dias abre com `null`; minimizado 30 min fecha e reabrir retoma; aviso de visibilidade de outra janela é ignorado.
- Loader: manda o aviso ao abrir e fechar, para a origem do chat.
- Navegador: recarregar no meio da conversa, encerrar, e o ciclo de minimizar (com o prazo encurtado só no roteiro de verificação, se preciso).

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Recarregar com 12 falas confirmadas | componente: storage com sessão + `historico` de 12 → 12 balões; navegador |
| Encerrar a conversa | componente: menu → confirmar → storage apagado, `ola` com `null`, tela vazia; navegador |
| Sessão salva há 31 dias | `sessaoGuardada` e componente: `ola` com `null`, storage apagado |
| Minimizado por 30 minutos | componente com relógio falso: socket fecha; reabrir → `ola` com a sessão |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — Resposta em duas partes pode voltar como um balão só** no histórico.
- **L3 — O histórico traz no máximo as 50 últimas falas.**
- **L4 — Uma mensagem cujo `ack` se perdeu mas que o servidor gravou** aparece no histórico e continua pendente na tela; o reenvio é deduplicado pelo servidor, mas a tela pode mostrá-la duas vezes até recarregar.
- **L5 — Encerrar não avisa o servidor.** Apagar dados do titular é o fluxo de direitos do titular (TEC-207/TEC-342), não este botão.

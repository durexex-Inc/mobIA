# TEC-347 — Retomar a conversa ao recarregar a página e poder encerrá-la

**Status:** implementado (27/09/2026)
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
  - **Nota (27/09/2026):** a comparação que decide gravar é com a sessão que o `ola` daquela conexão levou, não com a guardada. Comparar com o storage regravava a sessão retomada, com `criadaEm` de agora, se outra aba a tivesse apagado entre o `ola` e o frame `sessao` — e o prazo de 30 dias recomeçava. Agora grava-se só quando o servidor cunhou uma sessão nova (`frontend/src/components/Conversa.tsx::Conversa`); a conferência com o guardado, dentro de `frontend/src/lib/sessaoGuardada.ts::gravarSessao`, ficou como segunda rede.
- **Leitura ao montar:** vale se o JSON é um objeto, `sessao` é UUID e `agora - criadaEm < 30 dias` (e `criadaEm` não está no futuro). Qualquer outra coisa — inclusive o texto puro gravado pela TEC-346, que nunca foi a produção — é apagada, e a conexão sai com `null`.
- **Sem storage** (Safari ITP, modo privado, storage bloqueado): toda leitura e escrita em try/catch; o chat abre sessão anônima sem erro.
- Módulo puro `frontend/src/lib/sessaoGuardada.ts`, que recebe o storage e o instante — testável sem relógio real.

## D2 — O `historico` é a verdade do servidor

- **A primeira conexão manda o UUID guardado**, quando há um válido (D1).
- **Ao receber `historico`, a tela passa a ser o histórico** mais as mensagens locais da visitante ainda não confirmadas (`enviando` e `falhou`), que ficam no fim, na ordem em que estavam.
- **Isso vale também para as reconexões da TEC-346.** O que o agente disse enquanto o socket estava fechado não chega por frame — chega pelo histórico. Ignorar o `historico` na reconexão, como fazia a TEC-346, perdia essas falas.
- Fala da visitante vinda do histórico entra como `recebida`, com id sintético, e sem "Reenviar". Fala do agente entra como balão do agente.
  - **Nota (27/09/2026):** o id sintético vale só para a fala que ainda não estava na tela. A que já estava — a `recebida` da visitante, com o `messageId` dela, e o balão do agente em memória — continua sendo o mesmo objeto, com a mesma chave: histórico e tela andam juntos, em ordem, casando autor e texto exato (`frontend/src/lib/conversa.ts::aplicarHistorico`). Sem isso cada reconexão remontava todos os balões, e o `role="log"` com `aria-relevant="additions"` lia de novo a conversa inteira para quem usa leitor de tela. A chave nova nunca repete uma que esteja na lista, nem uma que esteja saindo dela; e um `historico` igual à tela, sem pendentes, não muda o estado.
- **Limites, registrados como lacunas:** uma resposta do agente em duas partes pode voltar como um balão só, porque o servidor pode guardá-las numa linha (L2); conversa com mais de 50 falas volta só com as 50 últimas (L3).

## D3 — "Encerrar conversa" fica num menu do cabeçalho, com confirmação

- Um botão "Opções da conversa" no cabeçalho abre um menu com "Encerrar conversa".
- Escolher pede confirmação na própria tela: "Encerrar esta conversa? O histórico some desta tela." com "Encerrar" e "Cancelar". Um toque acidental não apaga a conversa da tela.
- Confirmar apaga o storage, fecha o socket, zera a tela e abre uma conexão nova com `sessao: null`.
  - **Nota (27/09/2026):** encerrar durante a espera de um `muitas_tentativas` não fura a espera: a conexão nova só abre quando ela acaba, no prazo original. Nesse caso não há campo de mensagem na tela, e o foco volta ao botão "Opções da conversa"; fora dela, vai para o campo.
- **O servidor não é avisado.** A sessão antiga deixa de ser usada por este aparelho; as mensagens ficam onde já ficavam, para o painel e a trilha.

## D4 — Minimizado por 30 minutos sem atividade, o socket dorme

- **O loader avisa o iframe.** Ao abrir e ao fechar o painel, `widget.js` manda `postMessage({tipo: 'mobia:visibilidade', aberto: true|false}, origemDoChat)` para a janela do iframe.
  - **Nota (27/09/2026):** antes do primeiro aviso o painel conta como aberto — o primeiro clique cria o iframe já visível e não avisa nada. Um fechar antes de o chat escutar `message` se perderia, então o loader, ao receber `mobia:pronto`, manda também o estado atual do painel.
- **O iframe só aceita o aviso do próprio pai:** `event.source === window.parent` e `event.data.tipo === 'mobia:visibilidade'` com `aberto` booleano.
- **Minimizado, corre um prazo de 30 minutos**, reiniciado por qualquer frame enviado ou recebido. Ao vencer, o chat fecha o socket num estado próprio, `adormecida`, que não aparece como falha e não marca nada como "Não enviada" que não estivesse já pendente.
  - **Nota (27/09/2026):** um socket que já estava fechado quando o prazo vence — uma queda, a espera de `muitas_tentativas` — não dorme: a tela já diz o que houve, e `adormecida` apagaria a espera ou faria o painel reaberto reconectar sozinho depois de uma queda, o que é da TEC-348.
- **Ao reabrir, reconecta com a sessão**, e o `historico` (D2) traz o que o agente tiver dito nesse meio-tempo.
  - **Nota (27/09/2026):** reabrir o painel só reconecta a partir de `adormecida`. E uma mensagem enviada com o chat em `adormecida` reconecta direto, pelo mesmo caminho de enviar com o socket fechado.
- O loader continua dentro do teto de 5 KB gzip.

## Notas de implementação (27/09/2026)

- O cabeçalho é desenhado por `Conversa`, que põe o menu dentro dele: `CabecalhoDoChat` passou a receber `children`.
- A sessão guardada é lida no efeito de montagem, não no render — ler o storage é I/O —, uma vez por componente: o StrictMode repete o efeito, e reler depois de um encerramento traria de volta o que ele apagou se o storage estivesse bloqueado para `removeItem`.
- A sessão só é gravada quando o servidor cunha uma nova (ver a nota na D1).

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
- **L6 — Recarregar descarta as mensagens pendentes** (`enviando` e `falhou`), que só existiam na memória da página. Se o servidor recebeu uma delas, ela volta no `historico`; se não, some.
- **L7 — A L3 vale também para as reconexões dentro da página.** Numa conversa com mais de 50 falas, a primeira reconexão troca a tela pelo `historico` e as falas mais antigas saem dela.
- **L8 — Fala retida pela moderação some da tela da visitante na reconexão**, porque o servidor não a devolve no `historico`.
- **L9 — A sessão em memória sobrevive aos 30 dias enquanto a aba fica aberta.** O prazo só é conferido ao ler o storage, na montagem; vence no próximo carregamento.
- **L10 — Várias abas na mesma origem compartilham a chave, e a última gravação vence.** Encerrar numa aba apaga a sessão guardada, mas as outras seguem com a delas em memória.

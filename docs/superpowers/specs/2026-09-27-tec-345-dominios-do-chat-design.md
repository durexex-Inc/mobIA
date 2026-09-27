# TEC-345 — Carregar o chat apenas nos domínios cadastrados do tenant

**Status:** implementado
**Card:** [TEC-345](https://eduardodurieuxlopes.atlassian.net/browse/TEC-345) — épico TEC-307
**Branch:** `feat/tec-345-dominios-do-chat`
**Depende de:** TEC-344 (embed, `frame-ancestors *` provisório), TEC-365 (`Origin` no handshake do WebSocket), TEC-198 (configuração versionada do agente)

## O que existe quando a card começa

- **`/embed/*` aceita qualquer ancestral.** `politicaDeSeguranca()` (`frontend/src/proxy.ts`) manda `frame-ancestors *` quando `embutivel`, deliberadamente provisório (L5 da TEC-344).
- **`/embed/aparencia` responde a qualquer site.** O loader de `copia-do-site.com` recebe a aparência e desenha o botão. O clique abre um iframe que hoje carrega normalmente.
- **`connect-src` não é declarado.** Ele herda `default-src 'self'`, e o WebSocket que a TEC-346 vai abrir, direto para a API (regra da TEC-346), seria recusado pelo navegador.
- **O proxy é síncrono** e não chama a API.
- **O socket já está travado.** Desde a TEC-365, só a origem do painel abre `WS /widget/chat`. O que falta é travar em que site o iframe aparece.

## D1 — Os domínios entram na configuração versionada do agente

Decisão do Eduardo, 27/09/2026, que resolve o **[CONFIRMAR]** da card. É o molde da cor e da posição do botão (D1 da TEC-344): versão, histórico e autoria sem código novo. A tela que edita é da TEC-337.

- **`dominios_do_chat`**: lista de até 5 entradas, `ARRAY(Text)` não nulo, com padrão `{}`. A migration `0065` põe um `CHECK` de cardinalidade.
- **Cada entrada é `host` ou `host:porta`, em minúsculas.** Sem esquema, sem caminho, sem curinga, sem repetição. `validar()` recusa o resto e junta os erros com os dos outros campos.
  - A forma é a de um *host-source* de CSP, e é interpolada nela. Um `;` ou um espaço abririam uma diretiva nova, e é isso que o formato fechado impede. O Next confere o mesmo formato de novo antes de interpolar.
  - Sem esquema, o `frame-ancestors` casa com o esquema do próprio iframe (CSP3): `https` em produção e `http` em desenvolvimento. Com isso uma mesma entrada vale nos dois ambientes.
  - **`www.` e o domínio nu são entradas diferentes.** Quem tem os dois cadastra os dois. Curinga (`*.x.com.br`) ficou de fora: a card fala em domínios, e um curinga abriria subdomínios que a imobiliária não controla.
  - A porta existe para o desenvolvimento, em que o site de teste roda em `localhost:5500`.
- **Vazio por padrão, e vazio quer dizer que nenhum site embute o chat.** Isso troca o `*` provisório pelo lado seguro, como o `TENANT_SLUG` e o `ORIGENS_DO_WIDGET`.
- `GET` e `PATCH /api/v1/configuracao/agente` leem e aceitam `dominiosDoChat`, e `limites` informa o máximo.

## D2 — `GET /widget/aparencia` devolve os domínios

O FastAPI acrescenta `dominios` à resposta que o Next já consome, e o formato continua um URL só e sempre 200 (emenda da TEC-344 ao D3). Os domínios não são segredo: são os sites onde o chat aparece. O navegador também não fala com esta rota (TEC-302).

## D3 — `/embed/aparencia` responde 404 fora dos domínios

Quem pede a aparência é o loader, rodando no site da imobiliária. O `fetch` dele é de outra origem, então o navegador manda `Origin`. O route handler compara o *host* desse `Origin` com os domínios e responde o **mesmo 404** do slug errado quando não bate, ou quando o header falta.

- **Por isso o botão nem aparece em `copia-do-site.com`**, que é o segundo cenário da card lido ao pé da letra: "o chat não é exibido". Sem esta checagem, o botão apareceria, o clique abriria um painel com o iframe recusado pelo navegador, e só depois de 10 s o `mobia:pronto` ausente o removeria (D7 da TEC-344).
- **A trava de verdade continua sendo a CSP (D4).** Qualquer um pode pedir `/embed/aparencia` mandando o `Origin` que quiser. Esta checagem é de experiência, e a CSP é de segurança.
- `Vary: Origin` entra na resposta, porque ela agora depende do header.
- O loader não muda. Ele já trata o 404 como "sem botão".

## D4 — O proxy monta `frame-ancestors` e `connect-src` do embed

Para `/embed/*`, o proxy passa a buscar os domínios e monta:

- **`frame-ancestors <dominio> <dominio> ...`**, ou `'none'` se a lista estiver vazia ou a busca falhar. Falhar fechado: sem resposta da API, nenhum site embute.
- **`connect-src 'self' <api> <ws da api>`**, com a origem pública da API em `MOBIA_ORIGEM_PUBLICA_DA_API`. A mesma origem aparece com o esquema de WebSocket correspondente (`https` vira `wss`, `http` vira `ws`), porque o casamento de `https:` com `wss:` não é uniforme entre navegadores. Sem a variável, fica só `'self'`, e a conversa não conecta.
- O painel continua com `frame-ancestors 'none'` e sem `connect-src` próprio.
  - **Emenda (TEC-384, 27/09/2026):** `MOBIA_ORIGEM_PUBLICA_DA_API` não existe mais. A TEC-346 entrou na mesma tarde com o endereço do socket em `enderecoDoChat()` (`MOBIA_WIDGET_WS_URL`, ou o derivado de `MOBIA_API_BASE`). Com duas variáveis, o socket podia ir para uma origem que a CSP não admitia. O `connect-src` do embed passou a ser `'self'` mais `origemDoChat()`, a mesma fonte, só com o esquema de WebSocket. Sem origem válida, a diretiva é omitida e o embed herda `'self'`, como a TEC-346 fazia. O merge das duas cards também deixou `proxy.ts` sem compilar, e é isso que a TEC-384 conserta.

**A busca tem memória de 60 s no processo, e não o Data Cache.** A referência de `proxy` do Next 16 não documenta `fetch` com `next.revalidate` no proxy, e contar com isso seria repetir a TEC-344 aprendendo o comportamento do cache em produção. Um `Map` de módulo com prazo resolve e se testa com relógio falso:

- a promessa em voo é compartilhada, então cem requisições simultâneas no vencimento fazem uma chamada só;
- a falha também fica memorizada, por 5 s: a API caída não é martelada a cada visita, e volta sozinha.

O proxy passa a ser `async`. O `chamarApi` fica de fora porque arrasta `server-only`. O proxy monta a URL a partir do mesmo `MOBIA_API_BASE`.

## D5 — Nenhum recurso de terceiros

O terceiro cenário da card já é garantido pela CSP que existe: `default-src`, `script-src`, `style-src`, `img-src` e `font-src` só admitem `'self'`, nonce, `blob:` e `data:`. As fontes Geist vêm de `next/font/google`, que as baixa **no build** e as serve de `_next/static`, e não do Google em tempo de execução. Esta card acrescenta o teste que prende isso: a CSP do embed não cita host nenhum fora dos domínios e da API.

## Testes

- **Backend:**
  - unitários de `validar()` para os domínios: formato, caixa, porta, esquema, caminho, curinga, `;`, repetição e mais de 5;
  - feature de `GET`/`PATCH /agente` com `dominiosDoChat`;
  - `/widget/aparencia` com `dominios`.
- **Next:**
  - `lerDominios` e `fonteDeAncestral` (formato conferido de novo);
  - `/embed/aparencia` com `Origin` cadastrado (200 e `Vary`), não cadastrado (404), ausente (404) e com porta;
  - proxy: `frame-ancestors` com os domínios; `'none'` sem domínios e com a API fora; o painel continua `'none'`; `connect-src` com `https` e `wss` da API; memória de 60 s com relógio falso; uma chamada só para requisições simultâneas; nenhum host de terceiros na CSP do embed.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Domínio cadastrado: o chat carrega | proxy: `frame-ancestors imobiliariasol.com.br`; `/embed/aparencia` 200 com esse `Origin` |
| Domínio não cadastrado: o chat não é exibido | proxy: `copia-do-site.com` fora do `frame-ancestors`; `/embed/aparencia` 404 com esse `Origin` |
| Nenhum recurso de terceiros | teste da CSP do embed (D5). **O navegador não é exercitado**: não há teste de ponta a ponta |

O "critério de release 7.2" da card (`frame-ancestors` testado com domínio permitido e negado) é exercitado sobre o cabeçalho, e não num navegador real.

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo**, como nas cards anteriores. RN-FE-16.3 e RT-FE-09 vêm só do texto da card.
- **L2 — Sem tela.** Até a TEC-337, os domínios só se cadastram por `PATCH /api/v1/configuracao/agente`.
- **L3 — Três variáveis para o chat funcionar.** `TENANT_SLUG` (botão), os domínios na configuração (onde aparece), `ORIGENS_DO_WIDGET` no backend e `MOBIA_ORIGEM_PUBLICA_DA_API` no Next (conversa). **Emenda (TEC-384):** a última virou `MOBIA_WIDGET_WS_URL`, opcional, derivada de `MOBIA_API_BASE`. A falta de qualquer uma falha fechado, e em silêncio para o visitante.
- **L4 — Mudança de domínio leva até dois minutos.** Até 60 s na memória do proxy e até 60 s no Data Cache da aparência, que são independentes.
- **L5 — A TEC-346 precisa abrir o socket em `MOBIA_ORIGEM_PUBLICA_DA_API`.** Esta card fixa o nome da variável. Se a TEC-346 usar outro, o `connect-src` recusa a conexão.
  - **Emenda (TEC-384, 27/09/2026):** foi o que aconteceu. A TEC-346 usou `MOBIA_WIDGET_WS_URL`, e a TEC-384 fez o `connect-src` ler a mesma fonte. Ver a emenda da D4.

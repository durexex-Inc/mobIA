# TEC-344 — Instalar o chat no site da imobiliária com uma linha de script

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-344](https://eduardodurieuxlopes.atlassian.net/browse/TEC-344) — épico TEC-307
**Branch:** `feat/tec-344-embed-do-chat`
**Depende de:** TEC-124 (`WS /widget/chat`), TEC-198 (configuração versionada do agente), TEC-356 (CSP), TEC-309 (`/embed/*` já é rota pública)
**Bloqueia:** TEC-345 (domínios cadastrados), TEC-346 (a conversa)

## O que existe quando a card começa

- **Nenhum cliente do chat web.** Não há `widget.js`, rota `/embed` nem código de iframe. O `WS /widget/chat` existe e é anônimo, mas ninguém o consome (TEC-364, "O que existe").
- **`/embed/*` já abre sem sessão.** `rotaPublica()` em `frontend/src/proxy.ts` já o exclui do redirecionamento ao login, com a TEC-344 citada no comentário (D5 da TEC-309).
- **A CSP proíbe exatamente o que esta card precisa.** `politicaDeSeguranca()` manda `frame-ancestors 'none'` em toda rota, e `proxy.test.ts` afirma isso inclusive para `/embed/chat`. Sem mudança, o navegador recusaria o iframe em qualquer site.
- **Não há modelo de tenant.** O SRS (PR-03) fixa um tenant único na POC, e não existe `tenant_id` no código.
- **Da aparência só existe o nome.** `nome_do_assistente` está em `ConfiguracaoDoAgente` (`domain/configuracao/vigente.py`) e só é lido por `GET /agente`, autenticado. Cor primária e posição do botão não existem em lugar nenhum.

## D1 — Cor e posição entram na configuração versionada do agente

Decisão do Eduardo, 27/09/2026. A card diz que a aparência "vem da configuração do tenant", e a configuração que existe é a do agente, onde o nome do assistente já está. Os dois campos novos ganham versão, histórico e autoria sem código novo para isso.

- **`cor_primaria`**: texto `#RRGGBB`. `validar()` recusa qualquer outra forma, e um `CHECK` no banco repete a regra.
- **`posicao_do_botao`**: enum `DIREITA | ESQUERDA`, também com `CHECK`.
- **Migration nova** em `configuracoes_do_agente`, no molde da `0060` (TEC-191): colunas não nulas, com padrão.
- **O padrão é `DIREITA` e uma cor neutra.** Não há comportamento anterior a preservar, ao contrário do que diz a docstring de `vigente.py` sobre os outros campos: antes desta card não existia botão.
- `GET` e `PATCH /agente` passam a ler e aceitar os dois campos. A tela que os edita é da TEC-337; esta card não mexe no painel admin.

Atributos na tag (`data-cor`, `data-posicao`) foram descartados: a configuração viraria texto colado no site do cliente, e mudar a cor exigiria editar o site.

## D2 — `data-tenant` é conferido contra `MOBIA_TENANT_SLUG`

Decisão do Eduardo, 27/09/2026. Tenant único não significa atributo decorativo: um snippet colado com o valor errado precisa falhar no primeiro teste de quem o instala, não no dia em que houver multi-tenant.

- **`MOBIA_TENANT_SLUG`** em `app/config.py`, **nulo por padrão**.
- Nulo quer dizer que nenhum slug casa: nenhum widget aparece em lugar nenhum até alguém configurar. É o lado seguro. Um deploy que esqueceu a variável fica sem chat, não com um chat que aceita qualquer valor.
- O contrato do endpoint já nasce com o tenant no caminho (D3). O multi-tenant troca a comparação por uma busca, sem mudar a URL.

## D3 — Endpoint público `GET /widget/aparencia/{slug}`

No router de `api/routes/widget.py`, com entrada em `ROTAS_PUBLICAS` (`test_toda_rota_declara_autorizacao` exige).

- **Devolve só `{nome_do_assistente, cor_primaria, posicao_do_botao}`** da configuração vigente. O resto da configuração (tom, pesos, cadência, orçamento) é do administrador e não sai por uma rota anônima.
- **`404` quando o slug não casa, e também quando não há slug configurado**, com o mesmo corpo. Distinguir os dois diria a quem sonda se existe algum tenant.
- **`nome_do_assistente` pode ser `null`.** O que o visitante vê nesse caso é decisão do frontend (D6), porque é texto de tela.

## D4 — O Next faz cache de 60 s, porque o limite por IP enxerga o servidor, não o visitante

O navegador nunca fala com a API direto (TEC-302). Quem chama `GET /widget/aparencia` é o servidor do Next, e o `RateLimitPorIP` da API vê o IP dele. **Todos os visitantes de todos os sites cairiam no mesmo balde**, e um pico de tráfego num site derrubaria o botão em todos.

O route handler `/embed/aparencia` (D5) chama a API com `revalidate: 60`. A API recebe cerca de uma chamada por minuto, qualquer que seja o tráfego, e uma mudança de cor feita pelo admin leva até 60 s para chegar ao site.

## D5 — O loader é JavaScript puro em `frontend/public/widget.js`

Não há etapa de build. O Next serve o arquivo como está, e "sem dependências" fica literal: não existe bundler que possa arrastar nada para dentro.

- **ES2017 dentro de uma IIFE.** Não há conferência de tipos: o `include` do `tsconfig.json` só cobre `*.ts` e `*.tsx`, então um `// @ts-check` aqui não seria lido por gate nenhum, e escrevê-lo sugeriria uma garantia que não existe. Os testes da seção "Testes" executam o arquivo real e são a rede.
- **O tamanho é conferido** por `npm run verificar:widget` (`frontend/scripts/verificar-widget.mjs`), que comprime com gzip e reprova acima de 5120 bytes. Entra no job `frontend` do CI, ao lado de `verificar:bundle`.

Descartadas:
- **TypeScript compilado por esbuild.** Acrescenta uma etapa de build e um artefato gerado, que teria de ser versionado ou gerado num deploy que ainda não existe (TEC-219). E o gate de tamanho passaria a medir a saída do compilador, não o arquivo que alguém lê.
- **Script montado por route handler, com a aparência embutida.** Economizaria uma requisição, mas o `data-tenant` é atributo da tag e não chega ao servidor no pedido do script. Exigiria trocar o snippet da card por `?tenant=`.

### O fluxo

1. **Identificação.** A primeira linha captura `document.currentScript`. Se vier nulo, o loader procura `script[data-tenant][src*="widget.js"]`. Sem `data-tenant`, ou se o loader já rodou na página (snippet colado duas vezes), sai sem fazer nada.
2. **Aparência.** A origem vem do `src` do próprio script. O loader faz `GET <origem>/embed/aparencia?tenant=<slug>` com `AbortController` e timeout de 5 s.
   - O route handler responde com `Access-Control-Allow-Origin: *` e `Cache-Control: public, max-age=60`.
   - O botão só é desenhado se a cor casar com `#RRGGBB` e a posição for uma das duas conhecidas. Qualquer outra resposta conta como falha.
3. **Botão.** Mora num Shadow DOM fechado, para o CSS do site não entrar e o nosso não sair.
   - **O estilo entra via CSSOM (`el.style.x = ...`), e não por `<style>`.** A CSP do próprio site hospedeiro pode bloquear um `<style>` injetado; não bloqueia o CSSOM.
   - `aria-label` é "Abrir o chat com {nome}", ou "Abrir o chat" sem nome.
4. **Painel.** O primeiro clique cria o painel com `<iframe src="<origem>/embed/chat?tenant=<slug>">`. Os cliques seguintes só abrem e fecham o painel. O bundle do chat só é baixado a partir desse clique (terceira regra da card).

## D6 — A página `/embed/chat`

Server component. Lê a aparência pela mesma função com cache da D4 e responde `404` se o slug não casar.

- Renderiza um cabeçalho com o nome do assistente, ou **"Assistente virtual"** quando o nome é nulo, e a cor primária como variável CSS.
- Um componente cliente pequeno manda `postMessage({tipo: 'mobia:pronto'})` ao pai quando a página monta (D7).
- **A conversa não entra.** É da TEC-346 (L3).

## D7 — Nenhuma falha vira erro de JS no site hospedeiro

Esta é a quinta regra da card e o quarto cenário do Gherkin.

- **Tudo roda dentro de `try/catch`, e toda promise tem `catch`.** Nada chega ao `window.onerror` nem ao `unhandledrejection` do site.
- Falha ao buscar a aparência (rede, `404`, timeout, JSON torto, cor ou posição inválidas) quer dizer que nenhum botão é desenhado.
- **A falha do iframe se detecta por aperto de mão.** Um iframe de outra origem não dispara `onerror` quando a página dele falha. O loader espera o `mobia:pronto` da D6 e, se ele não chegar em 10 s, remove o painel e o botão.
  - A mensagem só vale se `event.origin` for a origem do script e `event.source` for a janela daquele iframe. Qualquer outra é ignorada.
- Se o próprio `widget.js` não carregar, o navegador só registra a falha de rede da tag `async`. Não há código nosso para errar.

## D8 — `/embed/*` recebe `frame-ancestors *`

`politicaDeSeguranca()` passa a variar por rota. `/embed/*` recebe `frame-ancestors *`, e todo o resto continua com `'none'`. A TEC-345 troca o `*` pelos domínios cadastrados do tenant.

- O teste de `proxy.test.ts` que afirma `'none'` para `/embed/chat` muda de expectativa.
- **Entra um teste que afirma que o painel continua `'none'`.** É ele que pega uma mudança que afrouxe a CSP da rota errada.
- `connect-src` para o WebSocket não entra aqui: quem abre a conexão é a TEC-346 (L4).

## Testes

- **Loader (vitest/jsdom, executando o arquivo real de `public/`):**
  - cor e posição do botão, e o `aria-label` com e sem nome;
  - nenhum iframe antes do clique;
  - primeiro clique cria o iframe; cliques seguintes só abrem e fecham;
  - sem botão e sem erro em cada falha: `404`, JSON torto, cor inválida, posição inválida, timeout, rede fora;
  - snippet duplicado desenha um botão só;
  - sem `data-tenant`, nada acontece;
  - sem `mobia:pronto` em 10 s, painel e botão somem;
  - `postMessage` de outra origem é ignorado.
- **Tamanho:** `verificar:widget` no CI.
- **CSP:** `/embed/chat` com `frame-ancestors *`, o painel com `'none'`.
- **`/embed/aparencia` e `/embed/chat`:** cabeçalhos CORS e de cache, e o `404` repassado.
- **Backend:**
  - unitários de `validar()` para cor e posição;
  - integração do endpoint: `200` com os três campos, slug errado e slug não configurado;
  - `GET` e `PATCH /agente` com os campos novos;
  - `test_uma_cabeca_de_migration.py` na `main` atualizada, depois do merge.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Visitante que não abre o chat não baixa o chat | teste do loader: nenhum iframe antes do clique; `verificar:widget` prende os 5 KB |
| Abrir o chat carrega isolado em até 1,5 s em 4G | isolamento: iframe, teste do loader. **Tempo não exercitado** (L2) |
| Aparência do tenant (`#0A7F5A`, esquerda, "Lia") | teste do loader (botão) e da página `/embed/chat` (nome) |
| Servidor fora do ar não quebra o site | testes de falha do loader, com espião em `window.onerror` e `unhandledrejection` |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** RN-FE-16.x, RNF-FE-04 e RNF-FE-12a vêm só do texto da card, como já registraram a TEC-302, a TEC-313 e a TEC-356.
- **L2 — O "1,5 s em 4G" não é medido.** Não há deploy (TEC-219) nem medição de Web Vitals (TEC-357). A card entrega o que torna o número alcançável (loader pequeno, iframe só no clique) sem provar o número.
- **L3 — Até a TEC-346, quem abre o chat vê só o cabeçalho.** Hoje ninguém é afetado, porque não há deploy. Mas o botão não deve ir a um site real antes da conversa existir.
- **L4 — O WebSocket não confere origem**, e isso é a TEC-365. O `connect-src` do WebSocket em `/embed/*` fica para a TEC-346.
- **L5 — Até a TEC-345, qualquer site pode embutir o chat.** O `frame-ancestors *` da D8 é deliberado e provisório. Com `MOBIA_TENANT_SLUG` nulo por padrão, nenhum ambiente mostra o botão sem que alguém o ligue.

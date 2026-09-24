# TEC-356 — Cabeçalhos de segurança nas rotas do dashboard

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-356](https://eduardodurieuxlopes.atlassian.net/browse/TEC-356) — épico TEC-308
**Branch:** `feat/tec-356-cabecalhos-de-seguranca`
**Origem:** RNF-FE-09, RNF-FE-10 (SRS mobIA Frontend v1.0 — ver a lacuna L1)

## O problema

O dashboard responde hoje **sem cabeçalho de segurança nenhum**. `next.config.ts` está vazio (`/* config options here */`) e não existe `proxy.ts` nem `middleware.ts` na árvore. Qualquer site pode embutir o painel num iframe, o navegador pode sniffar tipo de conteúdo, o referer completo vaza para terceiros e não há CSP alguma.

## D1 — O arquivo é `proxy.ts`, e não `middleware.ts`

**Este é o ponto onde memória de modelo erra**, e o `AGENTS.md` do frontend avisa exatamente sobre isso: *"This is NOT the Next.js you know"*. O projeto está em **Next 16.3.6**, e a referência empacotada em `node_modules/next/dist/docs` diz, em `01-app/03-api-reference/03-file-conventions/middleware.md`:

> The `middleware.js` file convention has been **deprecated** in Next.js 16 and renamed to `proxy.js`. All functionality remains the same — only the file and export names have changed.

Então: arquivo `src/proxy.ts`, função exportada `proxy`, não `middleware`. Escrever `middleware.ts` daria um arquivo que **o Next 16 simplesmente não executa** — sem erro, sem aviso, e com os testes de unidade passando, porque eles chamam a função direto. O sintoma seria "os cabeçalhos não chegam em produção" e nada apontaria a causa.

## D2 — Os estáticos vão no `next.config.ts`; só a CSP com nonce vai no proxy

É a única divisão que não deixa buraco, e a razão é de alcance.

O matcher recomendado para o proxy exclui `_next/static`, `_next/image` e os prefetches — e deve mesmo, porque gerar um nonce por asset é desperdício e o CSP de documento não se aplica a um `.js` servido como asset. Mas `X-Content-Type-Options: nosniff` **importa justamente nesses assets**: é neles que sniffing de tipo tem consequência. Se os estáticos morassem no proxy, todo arquivo sob `_next/static` sairia sem `nosniff`.

O `next.config.ts` não tem esse buraco, e a referência de `headers` é explícita:

> Headers are checked before the filesystem which includes pages and `/public` files.

Portanto:

| cabeçalho | onde | por quê |
| --- | --- | --- |
| `Content-Security-Policy` | `proxy.ts` | o nonce muda a cada requisição; configuração estática não consegue |
| `X-Content-Type-Options` | `next.config.ts` | precisa alcançar `_next/static` e `/public` |
| `Referrer-Policy` | `next.config.ts` | idem, e não depende da requisição |
| `Strict-Transport-Security` | `next.config.ts` | idem |

**O risco da divisão é conhecido e é ele que o teste ataca**: com duas moradas, alguém pode mexer numa e achar que mexeu nas duas. Por isso o teste de integração afirma **o conjunto inteiro sobre a mesma resposta** — não um teste por cabeçalho, por morada.

## D3 — `frame-ancestors 'none'`, e nada de `X-Frame-Options`

O primeiro cenário do Gherkin ("o navegador recusa a exibição dentro de um iframe") é atendido por `frame-ancestors 'none'` na CSP, que é o mecanismo moderno e o que a card pede nominalmente.

**Não acrescento `X-Frame-Options: DENY` junto.** Ele é o predecessor, e onde os dois existem os navegadores modernos ignoram o `X-Frame-Options` em favor do `frame-ancestors` — então o segundo não compra proteção, compra uma segunda fonte para o mesmo fato, que é a classe de defeito que este repo trata como bug. Fica registrado aqui para que a ausência não pareça esquecimento.

## D4 — HSTS de um ano, com `includeSubDomains` e **sem** `preload`

`max-age=31536000; includeSubDomains`. O ano é o que a card pede.

**`preload` fica de fora deliberadamente, e a razão é que ele é quase irreversível.** Entrar na lista de preload dos navegadores é rápido; sair leva meses e chega aos usuários só na versão seguinte do navegador. É um compromisso sobre **todos** os subdomínios do domínio, incluindo os que ainda não existem — e este projeto nem escolheu a nuvem ainda (é a TEC-219). Comprometer o domínio inteiro antes de saber onde ele vai morar é decisão que não cabe a esta card. Fica como lacuna declarada.

Em desenvolvimento o cabeçalho é inofensivo: o navegador ignora HSTS recebido por HTTP.

## D5 — A CSP tem forma diferente em desenvolvimento, e isso vem da referência

Da referência do Next:

> In development, `'unsafe-eval'` is required because React uses `eval` to provide enhanced debugging information (...). `unsafe-eval` is not required for production.

E o mesmo para estilo: em desenvolvimento, `style-src` precisa de `'unsafe-inline'`; em produção usa o nonce. A política fica:

```
default-src 'self';
script-src 'self' 'nonce-<n>' 'strict-dynamic' [dev: 'unsafe-eval'];
style-src 'self' [dev: 'unsafe-inline'] [prod: 'nonce-<n>'];
img-src 'self' blob: data:;
font-src 'self';
object-src 'none';
base-uri 'self';
form-action 'self';
frame-ancestors 'none';
upgrade-insecure-requests;
```

**`form-action 'self'` não é enfeite aqui**: o painel é `<form method="get">` (ver `app/page.tsx`), então é a diretiva que impede que uma injeção redirecione o envio do filtro para outro host.

**`connect-src` fica no `default-src 'self'`**, e isso basta porque o painel fala só com o próprio domínio — o `/bff/*` da TEC-302 existe justamente para que o navegador nunca chame o FastAPI direto. Se um dia chamar, é aqui que se acrescenta.

## D6 — O nonce obriga renderização dinâmica, e o painel já é dinâmica

A referência é dura nesse ponto: com nonce, *"all pages must be dynamically rendered"*, e PPR é incompatível.

**Não é custo novo para este projeto**: `app/page.tsx` recebe `searchParams: Promise<Busca>`, e ler `searchParams` já força renderização dinâmica. Não há página estática a perder, não há ISR configurado e o painel é uma tela autenticada por natureza — não é conteúdo de CDN.

O que isto **compromete o futuro a fazer** fica dito: toda tela nova do dashboard nasce dinâmica. Quem quiser uma estática vai ter de tirá-la do matcher do proxy, e aí ela fica sem CSP com nonce.

## D7 — O `/bff/*` fica fora do matcher

Ele devolve JSON, não documento: não tem script a autorizar, não é embutível em iframe e não renderiza nada. Gerar nonce para ele seria trabalho por requisição sem nenhum efeito.

O que importa naquela rota — `nosniff` — vem do `next.config.ts`, que a alcança. E as recusas dela já montam `Headers` próprios (ver `app/bff/[...rota]/route.ts`), que continuam intactos.

## D8 — O autolink é função pura, e **nada o chama ainda**

A terceira regra da card ("links em mensagens são autolinkados apenas para `http(s)` com `rel="noopener noreferrer nofollow"`") e o terceiro cenário do Gherkin ("`javascript:alert(1)` aparece como texto simples") supõem uma tela de transcrição. **Ela não existe**: a transcrição é a TEC-324, e não há nenhum componente no repo que renderize mensagem de lead.

Entrego a função pura, `lib/autolink.ts`, com os testes que provam o comportamento — inclusive `javascript:`, `data:` e `vbscript:` ficando como texto. **Não invento a tela para ter onde chamá-la.** É o mesmo raciocínio que a TEC-302 escreveu sobre o `/bff/*` nascer sem consumidor de cliente:

> Inventar um componente de cliente so para lhe dar consumidor seria inventar entidade para um criterio se auto-satisfazer.

Consequência declarada: o cenário 3 do Gherkin fica exercitado **na função**, não na tela. Quem fizer a TEC-324 tem de chamá-la — e é por isso que ela nasce com o nome e a assinatura prontos, não como um `TODO`.

## Arquivos

```
frontend/src/proxy.ts              # CSP com nonce (D1, D5)
frontend/src/proxy.test.ts
frontend/next.config.ts            # nosniff, Referrer-Policy, HSTS (D2)
frontend/src/lib/autolink.ts       # D8
frontend/src/lib/autolink.test.ts
```

## Testes

- **`proxy.test.ts`** — a CSP sai com nonce; o nonce **muda entre requisições** (nonce repetido não é nonce); `frame-ancestors 'none'` presente; o `x-nonce` vai na requisição para o render; o matcher não pega `/bff` nem `_next/static`.
- **O conjunto inteiro sobre a mesma resposta** (D2), que é o que pega a divisão entre as duas moradas.
- **`autolink.test.ts`** — `http(s)` vira link com os três `rel`; `javascript:`, `data:`, `vbscript:` e caminho relativo ficam texto; o texto ao redor é preservado e escapado.
- **Verificação no app de verdade**, e não só em unidade: `npm run build && npm start`, e conferir que os cabeçalhos chegam na resposta **e que a página renderiza sem violação de CSP**. Teste de unidade da função `proxy` não pegaria o caso real que mais assusta aqui — o `next/font` do `layout.tsx` injeta `<style>` inline, e uma CSP que o bloqueasse deixaria o painel sem estilo com todos os testes verdes.

### O que a verificação no app de verdade deu

Feita com `next start` na porta 3210 e `curl`:

- **Os quatro cabeçalhos chegam juntos na resposta de `/`** — os três da config e a CSP com nonce.
- **O `next/font` não injeta `<style>` inline**: ele emite `<link rel="stylesheet">`, e o Next põe o nonce nele. Zero tags `<style>` no HTML, então o caso temido não existe nesta versão.
- **Os 8 `<script>` do documento saem com nonce**, nenhum sem — é o que faz `'strict-dynamic'` funcionar em vez de quebrar a página.
- **O asset sob `_next/static` responde com `nosniff`**, que é a prova concreta da D2: se os estáticos morassem no proxy, ele sairia sem nada.
- **O `/bff/*` responde com os três estáticos e sem CSP**, como a D7 quer.
- `next build` classifica `/` como `ƒ (Dynamic)` e registra `ƒ Proxy (Middleware)` — o nonce tem onde ser aplicado.

## Emendas ao SRS

Nenhuma. O SRS do frontend não está no repositório (lacuna L1), então não há texto a emendar aqui.

## Lacunas declaradas

- **L1 — o SRS do frontend não está no repo.** A card cita RNF-FE-09 e RNF-FE-10 do "SRS mobIA Frontend v1.0", e `docs/srs/` só tem o do agente. As regras foram lidas do texto da card, que é a fonte de requisitos. Mesma lacuna que a TEC-302 declarou como L3 — **é a segunda card a esbarrar nela**, o que sugere que subir aquele documento vale uma card própria.
- **L2 — `/leads` e `/admin/prompts` não existem, então o cenário 2 do Gherkin não é exercitável como escrito.** São a TEC-321 e a TEC-338. O proxy é testado sobre os caminhos que a card nomeia (ele roda por caminho, não por rota existente), mas **isso não prova que uma página real nessas rotas responderá com os cabeçalhos** — prova que o proxy os produz para aquele caminho. A prova completa vem quando as telas existirem.
- **L3 — `preload` de HSTS fora (D4).** Compromisso praticamente irreversível sobre todos os subdomínios, antes de a nuvem estar escolhida (TEC-219).
- **L4 — nada chama o autolink (D8).** A tela de transcrição é a TEC-324.
- **L5 — a CSP não é reportada.** Sem `report-uri`/`report-to`, uma violação em produção quebra em silêncio no navegador de quem usa e ninguém fica sabendo. Ligar relatório exige um coletor, que não existe — a observabilidade do frontend é a TEC-358.
- **L6 — RESOLVIDA durante a card: a máquina não tinha o Node que o projeto pede.** `frontend/.nvmrc` pede Node **24** (é o que o CI usa, via `node-version-file`) e a máquina tinha **Node 20.19.6**, sem gerenciador de versão — e sob Node 20 o `jsdom` quebra na carga do `undici` e nenhum arquivo de teste roda. Resolvido instalando `fnm` e o **Node 24.21.0**; a suíte passou a rodar aqui: **14 arquivos, 104 testes, todos passando**, inclusive o `TextoComLinks.test.tsx` desta branch.
  **O `README.md` do frontend já documentava essa falha, com o texto do erro e tudo** — a seção "Comandos" termina exatamente nisso. Fica registrado aqui não como descoberta, mas como lembrete de que o README daquele diretório responde à pergunta antes de qualquer diagnóstico: eu o li tarde.

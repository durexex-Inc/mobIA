import { type NextRequest, NextResponse } from 'next/server'

import { ORIGEM_DO_MAPA, ORIGEM_DOS_TILES } from '@/lib/mapa'
import { origemDoChat } from '@/lib/servidor/enderecoDoChat'
import { dominiosDoEmbed } from '@/lib/servidor/dominiosDoEmbed'

/**
 * A CSP com nonce das rotas do dashboard (TEC-356, RNF-FE-09).
 *
 * **O arquivo se chama `proxy.ts` e a funcao se chama `proxy` porque este e o
 * Next 16, e nao o Next que a memoria de qualquer um lembra.** A convencao
 * `middleware.js` foi DEPRECADA e renomeada; a referencia empacotada diz, em
 * `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/middleware.md`:
 *
 *     The `middleware.js` file convention has been deprecated in Next.js 16
 *     and renamed to `proxy.js`. All functionality remains the same -- only
 *     the file and export names have changed.
 *
 * Isto importa mais do que parece: um `middleware.ts` neste projeto **nao
 * roda**. Sem erro, sem aviso, e com todo teste de unidade verde -- porque os
 * testes chamam a funcao direto, nao pelo Next. O sintoma seria "os
 * cabecalhos nao chegam em producao", meses depois, sem nada apontando a
 * causa. Ver a D1 do desenho.
 *
 * **So a CSP mora aqui.** `nosniff`, `Referrer-Policy` e HSTS moram em
 * `next.config.ts`, e a divisao e por ALCANCE, nao por gosto: o matcher abaixo
 * exclui `_next/static`, e e exatamente nos assets estaticos que `nosniff`
 * importa. Ver a D2 do desenho -- e o teste que afirma o conjunto inteiro
 * sobre a mesma resposta, que e o que pega alguem mexendo numa morada so.
 */

/**
 * Monta a politica. Separada da funcao do proxy para poder ser testada sem
 * `NextRequest`, e para que o unico lugar que varia entre dev e producao seja
 * legivel de uma vez so.
 *
 * **As duas concessoes de desenvolvimento vem da referencia, nao de tentativa
 * e erro.** O guia de CSP do Next diz que o React usa `eval` em
 * desenvolvimento para reconstruir pilha de erro do servidor no navegador, e
 * que isso nao vale para producao. O `'unsafe-inline'` de `style-src` segue o
 * mesmo guia. Quem trocar um `isDev` por `true` aqui esta afrouxando producao.
 *
 * **`embed` so vem nas rotas de `/embed/*`**, com os dominios que podem
 * enquadrar o chat (TEC-345, D4) e a origem do WebSocket dele (TEC-346, D2).
 * Ausente, a politica e a do painel: ninguem enquadra, e `connect-src` herda
 * `default-src 'self'`.
 */
export type PoliticaDoEmbed = {
  /** Os dominios cadastrados, ja conferidos por `lerDominios`. Vazio, ninguem. */
  ancestrais: readonly string[]
  /**
   * `origemDoChat()` -- a MESMA fonte do endereco que a pagina passa ao
   * socket, e por isso os dois nao divergem (TEC-384). `null` quando ela
   * lanca por configuracao invalida.
   */
  conectarA: string | null
}

export function politicaDeSeguranca(
  nonce: string,
  isDev: boolean,
  { embed, portal = false }: { embed?: PoliticaDoEmbed; portal?: boolean } = {},
): string {
  return [
    "default-src 'self'",
    // So o portal enquadra alguem, e so o mapa do detalhe do imovel (D3 do
    // desenho do visual do portal). O painel e o embed nao tem iframe
    // nenhum, e por isso continuam herdando `default-src 'self'`.
    ...(portal ? [`frame-src ${ORIGEM_DO_MAPA}`] : []),
    // So o embed abre WebSocket, e so para a origem do proprio chat (TEC-346,
    // D2): o painel nao tem `fetch` nem socket para fora da propria origem, e
    // por isso continua sem esta diretiva. Sem origem conferida, o embed
    // tambem fica sem ela, e herda `'self'`.
    ...(embed?.conectarA ? [`connect-src 'self' ${embed.conectarA}`] : []),
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ''}`,
    `style-src 'self' ${isDev ? "'unsafe-inline'" : `'nonce-${nonce}'`}`,
    // O portal tambem carrega os tiles do mapa da vitrine (D8 do desenho do
    // visual do portal); o painel e o embed seguem so com a propria origem.
    `img-src 'self' blob: data:${portal ? ` ${ORIGEM_DOS_TILES}` : ''}`,
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    // O painel e `<form method="get">` (ver `app/page.tsx`), entao esta
    // diretiva e a que impede uma injecao de redirecionar o envio do filtro
    // para outro host. Nao e generica: e a defesa da unica forma que existe.
    "form-action 'self'",
    // O cenario 1 do Gherkin da card. Sem `X-Frame-Options` junto: onde os
    // dois existem o navegador moderno ignora o antigo, entao ele nao compraria
    // protecao -- compraria uma segunda fonte para o mesmo fato. Ver a D3.
    // `/embed/*` e o chat que o site da imobiliaria enquadra (TEC-344, D8), e
    // so os dominios cadastrados o enquadram (TEC-345, D4). Sem esquema: um
    // host-source sem esquema casa com o do proprio iframe, entao a mesma
    // entrada vale em `https` e em desenvolvimento. O padrao do parametro e o
    // fechado: esquecer de passa-lo nega o iframe, e nao o abre -- e lista
    // vazia tambem.
    embed && embed.ancestrais.length > 0
      ? `frame-ancestors ${embed.ancestrais.join(' ')}`
      : "frame-ancestors 'none'",
    // Terceira concessao de dev, que faltava ao lado das outras duas acima: o
    // `next dev` so fala HTTP. Incondicional, esta diretiva faz o navegador
    // reescrever fonte, form-action e navegacao para https, e todas quebram
    // com ERR_SSL_PROTOCOL_ERROR contra um servidor sem TLS.
    ...(isDev ? [] : ['upgrade-insecure-requests']),
  ].join('; ')
}

/** `origemDoChat()`, ou `null` com o erro no log -- ver o comentario em `proxy`. */
function conectarDoEmbed(): string | null {
  try {
    return origemDoChat()
  } catch {
    console.error('CSP do embed: MOBIA_WIDGET_WS_URL ou MOBIA_API_BASE invalida')
    return null
  }
}

/** O chat embutido no site da imobiliaria (TEC-344). Casamento por segmento. */
function rotaDoEmbed(caminho: string): boolean {
  return caminho === '/embed' || caminho.startsWith('/embed/')
}

/**
 * O portal publico de busca de imoveis (TEC-387/388/389). Casamento por
 * segmento, mesma razao de `rotaDoEmbed`.
 *
 * **Achado corrigindo aqui, nao numa card propria**: ate esta correcao,
 * `/busca` e `/busca/[id]` nao estavam em `rotaPublica`, entao todo visitante
 * sem cookie de sessao era redirecionado para `/login` antes de a pagina
 * sequer renderizar -- o portal publico, construido para abrir sem login,
 * nunca abria para ninguem que nao estivesse logado no painel. As rotas de
 * API (`/portal/*`, backend) sempre foram publicas; so o proxy do Next e que
 * barrava a pagina.
 */
function rotaDoPortal(caminho: string): boolean {
  return caminho === '/busca' || caminho.startsWith('/busca/')
}

/** A ferramenta de desenvolvimento que simula o WhatsApp. Casamento por segmento. */
function rotaDoSimulador(caminho: string): boolean {
  return caminho === '/dev/simulador-whatsapp' || caminho.startsWith('/dev/simulador-whatsapp/')
}

/**
 * As rotas que abrem sem sessao (TEC-309, D5): o login, o chat embutido no
 * site da imobiliaria, que e do visitante e nao do painel (TEC-344), o portal
 * publico de busca (TEC-387), o simulador de WhatsApp (ferramenta de dev), e
 * o `/sair` (TEC-310, D6) e o batimento `/sessao/atividade` (TEC-311, D3). Os
 * dois ultimos porque quem chega sem cookie tem de receber a resposta do
 * proprio handler: redirecionado daqui, levaria `307`, que repete o POST no
 * destino -- e o batimento e um `fetch`, que espera `401`, nao uma pagina.
 *
 * Casamento por segmento, e nao por prefixo de texto: `/loginx` nao e o login,
 * e liberar por `startsWith('/login')` abriria qualquer rota que um dia
 * comecasse com essas letras.
 */
function rotaPublica(caminho: string): boolean {
  return (
    caminho === '/login' ||
    caminho.startsWith('/login/') ||
    rotaDoEmbed(caminho) ||
    rotaDoPortal(caminho) ||
    rotaDoSimulador(caminho) ||
    caminho === '/sair' ||
    caminho === '/sessao/atividade'
  )
}

/**
 * O cookie da sessao. Repetido aqui, e nao importado de `lib/servidor/sessao`,
 * porque aquele modulo arrasta o cliente do Redis e o `server-only` para o
 * proxy -- que nao precisa de nenhum dos dois, e so confere que o cookie
 * existe. O teste do proxy prende o nome ao da sessao.
 */
export const COOKIE_DA_SESSAO = 'mobia_sessao'

/**
 * Manda ao login quem chega sem o cookie da sessao (TEC-309, D5).
 *
 * **E uma checagem otimista, e nao a guarda.** Qualquer valor no cookie passa
 * por aqui; quem procura o valor no Redis e `exigirSessao`, na pagina. Esta
 * existe por custo: sem ela, a pagina renderizaria so para descobrir que nao
 * ha ninguem. E o desenho que o guia de autenticacao do Next 16 descreve.
 *
 * O destino carrega a busca junto: quem abriu o painel com um filtro volta
 * para o mesmo filtro.
 */
function semSessao(request: NextRequest): NextResponse | null {
  const { pathname, search } = request.nextUrl
  if (rotaPublica(pathname) || request.cookies.has(COOKIE_DA_SESSAO)) {
    return null
  }
  const login = new URL('/login', request.nextUrl)
  if (pathname !== '/' || search) {
    login.searchParams.set('returnTo', `${pathname}${search}`)
  }
  return NextResponse.redirect(login)
}

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const redirecionamento = semSessao(request)
  if (redirecionamento) {
    return redirecionamento
  }

  // `crypto.randomUUID()` e nao um contador ou o horario: nonce que se adivinha
  // nao e nonce. Precisa ser novo a cada requisicao, e ha teste afirmando que
  // duas requisicoes nao recebem o mesmo.
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64')
  // `origemDoChat` lanca se MOBIA_WIDGET_WS_URL ou MOBIA_API_BASE nao forem uma
  // URL valida. O proxy roda em TODA rota `/embed/*`, e um erro de
  // configuracao do WebSocket nao pode derrubar com 500 as que nao dependem
  // dele -- `/embed/aparencia`, que o botao do site le, continua respondendo.
  // O lado seguro e a CSP sem connect-src, o mesmo padrao fechado de
  // frame-ancestors. A pagina `/embed/chat` nao fica meio de pe: ela chama
  // `enderecoDoChat()` e falha alto por conta propria, de proposito.
  //
  // So o embed espera pela API: o painel nao tem ancestral a conferir, e nao
  // paga a chamada.
  //
  // **O simulador entra no mesmo ramo, sem ancestrais.** Ele abre um
  // WebSocket para a MESMA origem do chat (`conectarDoEmbed` reusa
  // `origemDoChat`, e CSP `connect-src` so olha origem, nunca caminho), mas
  // ninguem deve enquadra-lo -- `ancestrais: []` fecha `frame-ancestors`
  // igual ao padrao do painel.
  const caminho = request.nextUrl.pathname
  const embed = rotaDoEmbed(caminho)
    ? { ancestrais: await dominiosDoEmbed(), conectarA: conectarDoEmbed() }
    : rotaDoSimulador(caminho)
      ? { ancestrais: [], conectarA: conectarDoEmbed() }
      : undefined
  const politica = politicaDeSeguranca(nonce, process.env.NODE_ENV === 'development', {
    embed,
    portal: rotaDoPortal(caminho),
  })

  // O nonce vai no cabecalho da REQUISICAO tambem, e nao so no da resposta: e
  // assim que o render o alcanca. O Next extrai o nonce da propria CSP e o
  // aplica sozinho nos scripts do framework e nos bundles da pagina; o
  // `x-nonce` e o que um Server Component le, via `headers()`, quando precisa
  // passa-lo a um `<Script>` proprio.
  const cabecalhosDaRequisicao = new Headers(request.headers)
  cabecalhosDaRequisicao.set('x-nonce', nonce)
  cabecalhosDaRequisicao.set('Content-Security-Policy', politica)

  const resposta = NextResponse.next({ request: { headers: cabecalhosDaRequisicao } })
  resposta.headers.set('Content-Security-Policy', politica)
  return resposta
}

export const config = {
  matcher: [
    {
      /*
       * O que fica de fora, e por que:
       *
       * - `_next/static`, `_next/image`, `favicon.ico` -- assets, nao
       *   documentos. Nao ha script a autorizar neles, e gerar um nonce por
       *   asset seria trabalho por requisicao sem efeito. O `nosniff` que eles
       *   PRECISAM vem do `next.config.ts`, que os alcanca (D2).
       * - `bff` -- devolve JSON. Nao renderiza, nao embute, nao carrega script.
       *   Ver a D7 do desenho; as respostas dele montam `Headers` proprios em
       *   `app/bff/[...rota]/route.ts` e continuam intactas.
       * - `widget.js` -- o loader do chat que o site da imobiliaria carrega
       *   (TEC-344, D9). Sem esta exclusao, o visitante sem cookie levaria
       *   `307` para `/login` em vez do script, e o botao nunca apareceria --
       *   com os testes do loader verdes, porque eles leem o arquivo do disco.
       *   E asset: o `nosniff` vem do `next.config.ts`.
       *   **So o nome exato**: ponto escapado e `$` no fim, senao `/widget.json`
       *   ou `/widgetXjs` tambem pulariam a guarda. As outras alternativas
       *   ficaram como estavam.
       */
      source: '/((?!_next/static|_next/image|favicon.ico|widget\\.js$|bff).*)',
      /*
       * Prefetch do `next/link` nao pinta tela nenhuma: gastar um nonce nele e
       * desperdicio, e a recomendacao e da propria referencia do Next.
       */
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
}

import { type NextRequest, NextResponse } from 'next/server'

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
 */
export function politicaDeSeguranca(nonce: string, isDev: boolean): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ''}`,
    `style-src 'self' ${isDev ? "'unsafe-inline'" : `'nonce-${nonce}'`}`,
    "img-src 'self' blob: data:",
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
    "frame-ancestors 'none'",
    'upgrade-insecure-requests',
  ].join('; ')
}

export function proxy(request: NextRequest): NextResponse {
  // `crypto.randomUUID()` e nao um contador ou o horario: nonce que se adivinha
  // nao e nonce. Precisa ser novo a cada requisicao, e ha teste afirmando que
  // duas requisicoes nao recebem o mesmo.
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64')
  const politica = politicaDeSeguranca(nonce, process.env.NODE_ENV === 'development')

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
       */
      source: '/((?!_next/static|_next/image|favicon.ico|bff).*)',
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

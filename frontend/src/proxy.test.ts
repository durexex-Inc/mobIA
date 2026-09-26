import { NextRequest } from 'next/server'
import { describe, expect, it } from 'vitest'

import { COOKIE_DA_SESSAO as COOKIE_DA_SESSAO_DE_VERDADE } from '@/lib/servidor/sessao'

import { COOKIE_DA_SESSAO, politicaDeSeguranca, proxy } from './proxy'

const PAINEL = 'https://painel.exemplo.com'

/**
 * Por padrao, a requisicao leva o cookie da sessao: os testes da CSP sao
 * sobre quem ja passou pelo login. Os do redirecionamento pedem `false`.
 */
function requisicao(caminho: string, { comSessao = true }: { comSessao?: boolean } = {}) {
  return new NextRequest(new URL(caminho, PAINEL), {
    headers: comSessao ? { cookie: `${COOKIE_DA_SESSAO}=qualquer` } : {},
  })
}

function cspDe(caminho: string): string {
  return proxy(requisicao(caminho)).headers.get('content-security-policy') ?? ''
}

describe('politicaDeSeguranca', () => {
  it('nega o enquadramento em iframe', () => {
    // Cenario 1 do Gherkin: "o navegador recusa a exibicao".
    expect(politicaDeSeguranca('abc', false)).toContain("frame-ancestors 'none'")
  })

  it('autoriza script pelo nonce da requisicao', () => {
    expect(politicaDeSeguranca('abc', false)).toContain("script-src 'self' 'nonce-abc'")
  })

  it('nao afrouxa producao com as concessoes de desenvolvimento', () => {
    // As duas concessoes vem da referencia do Next (React usa `eval` em dev
    // para reconstruir pilha de erro). Este teste e o que reprova quem trocar
    // o `isDev` por `true` para "resolver" um aviso no console.
    const producao = politicaDeSeguranca('abc', false)

    expect(producao).not.toContain('unsafe-eval')
    expect(producao).not.toContain('unsafe-inline')
    expect(producao).toContain("style-src 'self' 'nonce-abc'")
  })

  it('libera eval e estilo inline apenas em desenvolvimento', () => {
    const desenvolvimento = politicaDeSeguranca('abc', true)

    expect(desenvolvimento).toContain('unsafe-eval')
    expect(desenvolvimento).toContain("style-src 'self' 'unsafe-inline'")
  })

  it('prende o envio do formulario de filtros na propria origem', () => {
    // O painel e `<form method="get">`; sem esta diretiva uma injecao poderia
    // apontar o envio para outro host.
    expect(politicaDeSeguranca('abc', false)).toContain("form-action 'self'")
  })
})

describe('proxy', () => {
  it('responde com a CSP nas rotas do dashboard', () => {
    // Os tres caminhos que o cenario 2 do Gherkin nomeia. `/leads` e
    // `/admin/prompts` AINDA NAO EXISTEM como rota (TEC-321 e TEC-338): o que
    // este teste prova e que o proxy produz a politica para esses caminhos,
    // nao que uma pagina real neles responda com ela. Ver a lacuna L2.
    for (const caminho of ['/', '/leads', '/admin/prompts']) {
      expect(cspDe(caminho)).toContain("frame-ancestors 'none'")
    }
  })

  it('gera um nonce novo a cada requisicao', () => {
    // Nonce que se repete nao e nonce: se fosse fixo, bastaria a um atacante
    // le-lo uma vez para injetar script autorizado em toda requisicao seguinte.
    const primeira = cspDe('/')
    const segunda = cspDe('/')

    expect(primeira).not.toBe(segunda)
  })

  it('manda o nonce tambem na requisicao, para o render alcanca-lo', () => {
    // E por `x-nonce` que um Server Component le o valor. Sem isto a CSP
    // sairia na resposta e o render nao teria como marcar script proprio.
    const resposta = proxy(requisicao('/'))
    const politica = resposta.headers.get('content-security-policy') ?? ''
    const nonce = /'nonce-([^']+)'/.exec(politica)?.[1]

    expect(nonce).toBeTruthy()
    expect(resposta.headers.get('x-middleware-request-x-nonce')).toBe(nonce)
  })
})

describe('proxy sem sessao (TEC-309, D5)', () => {
  function destinoDe(caminho: string): string | null {
    return proxy(requisicao(caminho, { comSessao: false })).headers.get('location')
  }

  it('cenario: quem acessa a lista de leads sem sessao vai ao login, com o destino', () => {
    expect(destinoDe('/leads?q=ana')).toBe(`${PAINEL}/login?returnTo=%2Fleads%3Fq%3Dana`)
  })

  it('a raiz sem busca vai ao login sem `returnTo`, que seria a pagina inicial de todo jeito', () => {
    expect(destinoDe('/')).toBe(`${PAINEL}/login`)
  })

  it('a raiz com filtro preserva o filtro', () => {
    expect(destinoDe('/?de=2026-09-01')).toBe(`${PAINEL}/login?returnTo=%2F%3Fde%3D2026-09-01`)
  })

  it.each(['/login', '/login/entrar', '/login/mfa', '/embed/chat', '/sair'])(
    '%s abre sem sessao, e continua recebendo a CSP',
    (caminho) => {
      const resposta = proxy(requisicao(caminho, { comSessao: false }))

      expect(resposta.headers.get('location')).toBeNull()
      expect(resposta.headers.get('content-security-policy')).toContain("frame-ancestors 'none'")
    },
  )

  it('`/loginx` nao e o login: e prefixo de texto, nao de rota', () => {
    expect(destinoDe('/loginx')).toBe(`${PAINEL}/login?returnTo=%2Floginx`)
  })

  it('o nome do cookie e o mesmo que a sessao grava', () => {
    // O proxy repete o nome em vez de importar `lib/servidor/sessao`, para nao
    // arrastar o Redis para ca. Este teste e o que impede os dois de divergirem.
    expect(COOKIE_DA_SESSAO).toBe(COOKIE_DA_SESSAO_DE_VERDADE)
  })
})

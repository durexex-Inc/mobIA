import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { esquecerDominiosDoEmbed } from '@/lib/servidor/dominiosDoEmbed'
import { COOKIE_DA_SESSAO as COOKIE_DA_SESSAO_DE_VERDADE } from '@/lib/servidor/sessao'

import { config, COOKIE_DA_SESSAO, politicaDeSeguranca, proxy } from './proxy'

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

async function cspDe(caminho: string): Promise<string> {
  return (await proxy(requisicao(caminho))).headers.get('content-security-policy') ?? ''
}

// O que `GET /widget/aparencia` devolve, e so os dominios importam ao proxy
// (TEC-345). Toda requisicao ao embed passa por este `fetch` falso.
const DOMINIOS = ['imobiliariasol.com.br', 'www.imobiliariasol.com.br']
let api: ReturnType<typeof vi.fn>

beforeEach(() => {
  esquecerDominiosDoEmbed()
  process.env.MOBIA_API_BASE = 'http://backend:8000'
  process.env.MOBIA_WIDGET_WS_URL = 'wss://api.exemplo.com/widget/chat'
  api = vi.fn(async () => new Response(JSON.stringify({ dominios: DOMINIOS }), { status: 200 }))
  vi.stubGlobal('fetch', api)
})
afterEach(() => {
  delete process.env.MOBIA_WIDGET_WS_URL
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

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

  it('o embed e enquadrado so pelos dominios cadastrados (TEC-345)', () => {
    const politica = politicaDeSeguranca('abc', false, {
      embed: { ancestrais: DOMINIOS, conectarA: null },
    })

    expect(politica).toContain(
      'frame-ancestors imobiliariasol.com.br www.imobiliariasol.com.br',
    )
    expect(politica).not.toContain('frame-ancestors *')
  })

  it('embed sem dominio cadastrado nao e enquadrado por ninguem', () => {
    expect(
      politicaDeSeguranca('abc', false, { embed: { ancestrais: [], conectarA: null } }),
    ).toContain("frame-ancestors 'none'")
  })

  it('o embed conecta so na propria origem e na do WebSocket do chat', () => {
    const politica = politicaDeSeguranca('abc', false, {
      embed: { ancestrais: DOMINIOS, conectarA: 'wss://api.exemplo.com' },
    })

    expect(politica).toContain("connect-src 'self' wss://api.exemplo.com;")
  })

  it('sem a origem do chat, o embed fica sem `connect-src` e herda `self`', () => {
    expect(
      politicaDeSeguranca('abc', false, { embed: { ancestrais: DOMINIOS, conectarA: null } }),
    ).not.toContain('connect-src')
  })

  it('o painel nao ganha `connect-src` proprio: herda `default-src`', () => {
    expect(politicaDeSeguranca('abc', false)).not.toContain('connect-src')
  })

  it('o embed pode abrir o WebSocket do chat, e so ele (TEC-346, D2)', () => {
    const politica = politicaDeSeguranca('abc', false, {
      embed: { ancestrais: DOMINIOS, conectarA: 'wss://api.exemplo.com' },
    })
    expect(politica).toContain("connect-src 'self' wss://api.exemplo.com")
  })

  it('o painel continua sem connect-src', () => {
    expect(politicaDeSeguranca('abc', false)).not.toContain('connect-src')
  })
})

describe('proxy', () => {
  it('responde com a CSP nas rotas do dashboard', async () => {
    // Os tres caminhos que o cenario 2 do Gherkin nomeia. `/leads` e
    // `/admin/prompts` AINDA NAO EXISTEM como rota (TEC-321 e TEC-338): o que
    // este teste prova e que o proxy produz a politica para esses caminhos,
    // nao que uma pagina real neles responda com ela. Ver a lacuna L2.
    for (const caminho of ['/', '/leads', '/admin/prompts']) {
      expect(await cspDe(caminho)).toContain("frame-ancestors 'none'")
    }
  })

  it('gera um nonce novo a cada requisicao', async () => {
    // Nonce que se repete nao e nonce: se fosse fixo, bastaria a um atacante
    // le-lo uma vez para injetar script autorizado em toda requisicao seguinte.
    const primeira = await cspDe('/')
    const segunda = await cspDe('/')

    expect(primeira).not.toBe(segunda)
  })

  it('manda o nonce tambem na requisicao, para o render alcanca-lo', async () => {
    // E por `x-nonce` que um Server Component le o valor. Sem isto a CSP
    // sairia na resposta e o render nao teria como marcar script proprio.
    const resposta = await proxy(requisicao('/'))
    const politica = resposta.headers.get('content-security-policy') ?? ''
    const nonce = /'nonce-([^']+)'/.exec(politica)?.[1]

    expect(nonce).toBeTruthy()
    expect(resposta.headers.get('x-middleware-request-x-nonce')).toBe(nonce)
  })
})

describe('proxy sem sessao (TEC-309, D5)', () => {
  async function destinoDe(caminho: string): Promise<string | null> {
    return (await proxy(requisicao(caminho, { comSessao: false }))).headers.get('location')
  }

  it('cenario: quem acessa a lista de leads sem sessao vai ao login, com o destino', async () => {
    expect(await destinoDe('/leads?q=ana')).toBe(`${PAINEL}/login?returnTo=%2Fleads%3Fq%3Dana`)
  })

  it('a raiz sem busca vai ao login sem `returnTo`, que seria a pagina inicial de todo jeito', async () => {
    expect(await destinoDe('/')).toBe(`${PAINEL}/login`)
  })

  it('a raiz com filtro preserva o filtro', async () => {
    expect(await destinoDe('/?de=2026-09-01')).toBe(`${PAINEL}/login?returnTo=%2F%3Fde%3D2026-09-01`)
  })

  it.each(['/login', '/login/entrar', '/login/mfa', '/sair', '/sessao/atividade'])(
    '%s abre sem sessao, e continua recebendo a CSP que nega iframe',
    async (caminho) => {
      const resposta = await proxy(requisicao(caminho, { comSessao: false }))

      expect(resposta.headers.get('location')).toBeNull()
      expect(resposta.headers.get('content-security-policy')).toContain("frame-ancestors 'none'")
    },
  )

  it.each(['/embed/chat', '/embed/aparencia'])(
    '%s abre sem sessao e aceita ser enquadrada pelos dominios cadastrados (TEC-345)',
    async (caminho) => {
      const resposta = await proxy(requisicao(caminho, { comSessao: false }))

      expect(resposta.headers.get('location')).toBeNull()
      expect(resposta.headers.get('content-security-policy')).toContain(
        'frame-ancestors imobiliariasol.com.br www.imobiliariasol.com.br;',
      )
    },
  )

  it.each(['/', '/leads', '/embedx'])(
    '%s continua negando iframe: afrouxar a rota errada e o que este teste pega',
    async (caminho) => {
      expect(await cspDe(caminho)).toContain("frame-ancestors 'none'")
    },
  )

  it('`/widget.js` nao passa pelo proxy: sem isso o visitante sem cookie levaria 307 (D9)', () => {
    // O `source` do matcher e expressao do path-to-regexp; para estes caminhos
    // ela coincide com uma RegExp ancorada.
    const fonte = (config.matcher[0] as { source: string }).source
    const casa = (caminho: string) => new RegExp(`^${fonte}$`).test(caminho)

    expect(casa('/widget.js')).toBe(false)
    // So o nome exato: `widget.json` ou `widgetXjs` sao rota do painel, e
    // passam pela guarda como qualquer outra.
    expect(casa('/widget.json')).toBe(true)
    expect(casa('/widgetXjs')).toBe(true)
    expect(casa('/embed/chat')).toBe(true)
    expect(casa('/leads')).toBe(true)
  })

  it('`/loginx` nao e o login: e prefixo de texto, nao de rota', async () => {
    expect(await destinoDe('/loginx')).toBe(`${PAINEL}/login?returnTo=%2Floginx`)
  })

  it('o nome do cookie e o mesmo que a sessao grava', () => {
    // O proxy repete o nome em vez de importar `lib/servidor/sessao`, para nao
    // arrastar o Redis para ca. Este teste e o que impede os dois de divergirem.
    expect(COOKIE_DA_SESSAO).toBe(COOKIE_DA_SESSAO_DE_VERDADE)
  })

  it('a resposta de /embed/chat autoriza a origem do WebSocket', async () => {
    process.env.MOBIA_WIDGET_WS_URL = 'wss://api.exemplo.com/widget/chat'
    try {
      expect(await cspDe('/embed/chat')).toContain("connect-src 'self' wss://api.exemplo.com")
      expect(await cspDe('/leads')).not.toContain('connect-src')
    } finally {
      delete process.env.MOBIA_WIDGET_WS_URL
    }
  })

  describe('com MOBIA_WIDGET_WS_URL invalida', () => {
    afterEach(() => {
      delete process.env.MOBIA_WIDGET_WS_URL
      vi.restoreAllMocks()
    })

    it('o proxy nao derruba as outras rotas do embed: CSP sem connect-src, e loga o erro uma vez', async () => {
      process.env.MOBIA_WIDGET_WS_URL = 'nao e url'
      const erro = vi.spyOn(console, 'error').mockImplementation(() => {})

      // `/embed/aparencia` nao usa o WebSocket e tem de continuar de pe; a
      // pagina `/embed/chat` falha sozinha, e isso nao e do proxy.
      const politica = await cspDe('/embed/aparencia')

      expect(politica).toContain(`frame-ancestors ${DOMINIOS.join(' ')}`)
      expect(politica).not.toContain('connect-src')
      expect(erro).toHaveBeenCalledTimes(1)
    })
  })
})

describe('proxy no embed (TEC-345, D4 e D5)', () => {
  it('cenario 2: `copia-do-site.com` nao esta entre os ancestrais permitidos', async () => {
    const politica = await cspDe('/embed/chat')
    const ancestrais = /frame-ancestors ([^;]+)/.exec(politica)?.[1].split(' ') ?? []

    expect(ancestrais).toEqual(DOMINIOS)
    expect(ancestrais).not.toContain('copia-do-site.com')
  })

  it('a API fora do ar fecha o embed: ninguem enquadra', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('fetch failed')
      }),
    )

    expect(await cspDe('/embed/chat')).toContain("frame-ancestors 'none'")
  })

  it('o painel nao chama a API: so o embed tem ancestral a conferir', async () => {
    await cspDe('/')
    await cspDe('/leads')

    expect(api).not.toHaveBeenCalled()
  })

  it('TEC-384: o `connect-src` sai da mesma fonte do endereco do socket', async () => {
    // `enderecoDoChat()` e o que a pagina passa ao `WebSocket`, e `origemDoChat()`
    // e o que a CSP admite. Com duas variaveis, uma podia apontar para onde a
    // outra nao deixa -- era o que a TEC-345 e a TEC-346 fariam juntas.
    process.env.MOBIA_WIDGET_WS_URL = 'wss://chat.exemplo.com/widget/chat'

    const politica = await cspDe('/embed/chat')

    expect(politica).toContain("connect-src 'self' wss://chat.exemplo.com;")
    expect(politica).toContain(`frame-ancestors ${DOMINIOS.join(' ')};`)
  })

  it('cenario 3: a CSP do embed nao cita host nenhum alem dos dominios e do WebSocket', async () => {
    // Fontes, imagens, estilos e scripts so de `'self'`, nonce, `blob:` e
    // `data:`. As fontes Geist vem de `next/font/google`, que as baixa no
    // build e as serve de `_next/static`: nao ha Google em tempo de execucao.
    const politica = await cspDe('/embed/chat')
    const permitidos = new Set([...DOMINIOS, 'wss://api.exemplo.com'])
    const hosts = politica
      .split(';')
      .flatMap((diretiva) => diretiva.trim().split(' ').slice(1))
      .filter((fonte) => !fonte.startsWith("'") && !fonte.endsWith(':'))

    expect(hosts.filter((host) => !permitidos.has(host))).toEqual([])
  })
})

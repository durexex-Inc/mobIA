import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GET } from './route'

const PAINEL = 'https://painel.exemplo.com'
const APARENCIA = { nomeDoAssistente: 'Lia', corPrimaria: '#0A7F5A', posicaoDoBotao: 'ESQUERDA' }
// O que o FastAPI devolve: a aparencia e o slug configurado, sempre com 200.
const DO_FASTAPI = { tenant: 'imobiliaria-x', ...APARENCIA }
const URL_DO_FASTAPI = 'http://backend:8000/widget/aparencia'

function pedido(tenant?: string) {
  const url = new URL('/embed/aparencia', PAINEL)
  if (tenant !== undefined) url.searchParams.set('tenant', tenant)
  return new NextRequest(url)
}

function apiRespondendo(status: number, corpo: unknown = DO_FASTAPI) {
  const api = vi.fn<(url: URL | string, init: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify(corpo), { status }),
  )
  vi.stubGlobal('fetch', api)
  return api
}

describe('GET /embed/aparencia', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('repassa a aparencia com CORS aberto e cache de um minuto', async () => {
    const api = apiRespondendo(200)

    const resposta = await GET(pedido('imobiliaria-x'))

    expect(String(api.mock.calls[0][0])).toBe(URL_DO_FASTAPI)
    expect(resposta.status).toBe(200)
    // O `tenant` do FastAPI e so para a comparacao; o loader ve os tres campos.
    expect(await resposta.json()).toEqual(APARENCIA)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
    expect(resposta.headers.get('cache-control')).toBe('public, max-age=60')
  })

  it('pede a API com revalidate de 60 s (D4)', async () => {
    const api = apiRespondendo(200)

    await GET(pedido('imobiliaria-x'))

    expect(api.mock.calls[0][1]).toMatchObject({ next: { revalidate: 60 } })
  })

  it('slug que nao e o configurado e 404, com CORS, pelo mesmo URL', async () => {
    const api = apiRespondendo(200)

    const resposta = await GET(pedido('outra'))

    expect(api).toHaveBeenCalledTimes(1)
    expect(String(api.mock.calls[0][0])).toBe(URL_DO_FASTAPI)
    expect(resposta.status).toBe(404)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
  })

  it('sem slug configurado no FastAPI (`tenant: null`) todo slug e 404', async () => {
    apiRespondendo(200, { ...DO_FASTAPI, tenant: null })

    expect((await GET(pedido('imobiliaria-x'))).status).toBe(404)
  })

  it('dois tenants diferentes pedem o mesmo URL: uma entrada so no Data Cache', async () => {
    // O Data Cache do Next so guarda resposta 200 (`patch-fetch.js`). Um URL
    // por slug faria de cada slug errado um 404 fora do cache, e um pedido
    // novo ao FastAPI no balde de rate limit do painel.
    const api = apiRespondendo(200)

    await GET(pedido('imobiliaria-x'))
    await GET(pedido('qualquer-outra'))

    expect(api.mock.calls.map(([url]) => String(url))).toEqual([URL_DO_FASTAPI, URL_DO_FASTAPI])
  })

  it('status que nao e 200 vira 503: o FastAPI nao responde 404 aqui', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    apiRespondendo(404, { detail: 'nao encontrado' })

    expect((await GET(pedido('imobiliaria-x'))).status).toBe(503)
  })

  it.each([undefined, '', '../../health', 'A', 'a/b', 'x'.repeat(65)])(
    'tenant malformado (%s) e 404 sem chamar a API',
    async (tenant) => {
      const api = apiRespondendo(200)

      const resposta = await GET(pedido(tenant))

      expect(resposta.status).toBe(404)
      expect(api).not.toHaveBeenCalled()
    },
  )

  it('API fora do ar vira 503, com CORS, e nao excecao', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<(url: URL | string, init: RequestInit) => Promise<Response>>(async () => {
        throw new TypeError('fetch failed')
      }),
    )

    const erro = vi.spyOn(console, 'error').mockImplementation(() => {})

    const resposta = await GET(pedido('imobiliaria-x'))

    expect(resposta.status).toBe(503)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
    // O 503 sozinho nao diz por que; o log do servidor diz.
    expect(erro).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['cor invalida', { ...DO_FASTAPI, corPrimaria: 'azul' }],
    ['sem tenant', APARENCIA],
    ['tenant que nao e texto', { ...DO_FASTAPI, tenant: 7 }],
  ])('corpo malformado da API (%s) vira 503: e defeito nosso, nao tenant ausente', async (_, corpo) => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    apiRespondendo(200, corpo)

    expect((await GET(pedido('imobiliaria-x'))).status).toBe(503)
  })
})

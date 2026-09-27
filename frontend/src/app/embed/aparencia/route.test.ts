import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GET } from './route'

const PAINEL = 'https://painel.exemplo.com'
const APARENCIA = { nomeDoAssistente: 'Lia', corPrimaria: '#0A7F5A', posicaoDoBotao: 'ESQUERDA' }

function pedido(tenant?: string) {
  const url = new URL('/embed/aparencia', PAINEL)
  if (tenant !== undefined) url.searchParams.set('tenant', tenant)
  return new NextRequest(url)
}

function apiRespondendo(status: number, corpo: unknown = APARENCIA) {
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
  })

  it('repassa a aparencia com CORS aberto e cache de um minuto', async () => {
    const api = apiRespondendo(200)

    const resposta = await GET(pedido('imobiliaria-x'))

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/widget/aparencia/imobiliaria-x')
    expect(resposta.status).toBe(200)
    expect(await resposta.json()).toEqual(APARENCIA)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
    expect(resposta.headers.get('cache-control')).toBe('public, max-age=60')
  })

  it('pede a API com revalidate de 60 s (D4)', async () => {
    const api = apiRespondendo(200)

    await GET(pedido('imobiliaria-x'))

    expect(api.mock.calls[0][1]).toMatchObject({ next: { revalidate: 60 } })
  })

  it('repassa o 404 do FastAPI, com CORS', async () => {
    apiRespondendo(404, { detail: 'nao encontrado' })

    const resposta = await GET(pedido('outra'))

    expect(resposta.status).toBe(404)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
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

    const resposta = await GET(pedido('imobiliaria-x'))

    expect(resposta.status).toBe(503)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
  })

  it('corpo malformado da API vira 503: e defeito nosso, nao tenant ausente', async () => {
    apiRespondendo(200, { corPrimaria: 'azul' })

    expect((await GET(pedido('imobiliaria-x'))).status).toBe(503)
  })
})

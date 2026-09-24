import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DELETE, GET, POST } from './route'

const PAINEL = 'https://painel.exemplo.com'
const FUNIL = ['api', 'v1', 'metricas', 'funil']

function contexto(rota: string[]) {
  return { params: Promise.resolve({ rota }) } as RouteContext<'/bff/[...rota]'>
}

function requisicao(
  caminho: string,
  { metodo = 'GET', origem, id }: { metodo?: string; origem?: string; id?: string } = {},
) {
  const cabecalhos = new Headers()
  if (origem) {
    cabecalhos.set('origin', origem)
  }
  if (id) {
    cabecalhos.set('x-request-id', id)
  }
  return new NextRequest(new URL(caminho, PAINEL), {
    method: metodo,
    headers: cabecalhos,
    // Corpo so nos metodos que o carregam; `NextRequest` recusa corpo em GET.
    body: metodo === 'GET' || metodo === 'HEAD' ? undefined : '{}',
  })
}

function apiRespondendo(corpo: unknown, status = 200) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(corpo), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

describe('proxy /bff/*', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ADMIN_TOKEN = 'segredo'
    process.env.MOBIA_ORIGEM_DO_PAINEL = PAINEL
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.MOBIA_ORIGEM_DO_PAINEL
  })

  describe('cenario: recusar mutation vinda de outra origem', () => {
    it('responde 403 E NAO REPASSA NADA a API', async () => {
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      const resposta = await POST(
        requisicao('/bff/api/v1/metricas/funil', {
          metodo: 'POST',
          origem: 'https://site-externo.com',
        }),
        contexto(FUNIL),
      )

      expect(resposta.status).toBe(403)
      // A segunda metade do criterio, e a que de fato importa: "e nada e
      // repassado a API".
      expect(api).not.toHaveBeenCalled()
      await expect(resposta.json()).resolves.toEqual({ erro: 'origem_nao_permitida' })
    })

    it('recusa tambem leitura de origem estrangeira', async () => {
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      const resposta = await GET(
        requisicao('/bff/api/v1/metricas/funil', { origem: 'https://site-externo.com' }),
        contexto(FUNIL),
      )

      expect(resposta.status).toBe(403)
      expect(api).not.toHaveBeenCalled()
    })

    it('recusa mutation de mesma origem que chega SEM `Origin`', async () => {
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      const resposta = await DELETE(
        requisicao('/bff/api/v1/metricas/funil', { metodo: 'DELETE' }),
        contexto(FUNIL),
      )

      expect(resposta.status).toBe(403)
      expect(api).not.toHaveBeenCalled()
    })
  })

  describe('cenario: recusar rota fora da allowlist', () => {
    it('responde 404 E NAO REPASSA NADA a API', async () => {
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      const resposta = await GET(
        requisicao('/bff/api/v1/corretores', { origem: PAINEL }),
        contexto(['api', 'v1', 'corretores']),
      )

      expect(resposta.status).toBe(404)
      expect(api).not.toHaveBeenCalled()
      await expect(resposta.json()).resolves.toEqual({ erro: 'rota_nao_permitida' })
    })

    it('recusa metodo fora da tabela na rota que existe', async () => {
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      const resposta = await POST(
        requisicao('/bff/api/v1/metricas/funil', { metodo: 'POST', origem: PAINEL }),
        contexto(FUNIL),
      )

      expect(resposta.status).toBe(404)
      expect(api).not.toHaveBeenCalled()
    })

    it('recusa traversal, com a origem correta, sem repassar', async () => {
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      const resposta = await GET(
        requisicao('/bff/api/v1/metricas/..', { origem: PAINEL }),
        contexto(['api', 'v1', 'metricas', '..']),
      )

      expect(resposta.status).toBe(404)
      expect(api).not.toHaveBeenCalled()
    })
  })

  describe('caminho feliz', () => {
    it('repassa com o token, a query e o `X-Request-Id`, e devolve o corpo', async () => {
      const api = apiRespondendo({ etapas: [] })
      vi.stubGlobal('fetch', api)

      const resposta = await GET(
        requisicao('/bff/api/v1/metricas/funil?de=2026-08-01&ate=2026-08-22'),
        contexto(FUNIL),
      )

      expect(resposta.status).toBe(200)
      await expect(resposta.json()).resolves.toEqual({ etapas: [] })

      const [url, init] = api.mock.calls[0]
      expect(String(url)).toBe('http://backend:8000/api/v1/metricas/funil?de=2026-08-01&ate=2026-08-22')
      expect(init.headers['X-Admin-Token']).toBe('segredo')
      expect(init.headers['X-Request-Id']).toBeTruthy()
    })

    it('propaga o `X-Request-Id` de entrada e o devolve na resposta', async () => {
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      const resposta = await GET(
        requisicao('/bff/api/v1/metricas/funil', { id: 'req-abc-123' }),
        contexto(FUNIL),
      )

      expect(api.mock.calls[0][1].headers['X-Request-Id']).toBe('req-abc-123')
      expect(resposta.headers.get('X-Request-Id')).toBe('req-abc-123')
    })

    it('substitui o `X-Request-Id` malformado por um gerado', async () => {
      // Os valores aqui sao os que uma requisicao real PODE carregar. Quebra de
      // linha nao entra nesta lista porque `Headers.set` a recusa na
      // construcao: injecao de CRLF nao chega ao handler, e por isso a forma
      // aceita em `bff.ts` e sobre higiene de tamanho e alfabeto, nao sobre
      // injecao. O caso da quebra esta coberto no teste da funcao pura.
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      for (const malformado of ['tem espaco', 'a'.repeat(201), 'acentuado-ç']) {
        api.mockClear()
        await GET(requisicao('/bff/api/v1/metricas/funil', { id: malformado }), contexto(FUNIL))
        expect(api.mock.calls[0][1].headers['X-Request-Id']).toMatch(/^[0-9a-f-]{36}$/)
      }
    })

    it('NAO cacheia: o proxy e `no-store`, ao contrario da busca do painel', async () => {
      // No dia em que houver sessao por usuario (TEC-309), um cache
      // compartilhado indexado so pela URL serviria a resposta de um usuario
      // para outro.
      const api = apiRespondendo({})
      vi.stubGlobal('fetch', api)

      await GET(requisicao('/bff/api/v1/metricas/funil'), contexto(FUNIL))

      expect(api.mock.calls[0][1].cache).toBe('no-store')
      expect(api.mock.calls[0][1].next).toBeUndefined()
    })

    it('repassa o status de recusa do backend em vez de o traduzir', async () => {
      vi.stubGlobal('fetch', apiRespondendo({ detail: 'filtro invalido' }, 422))

      const resposta = await GET(requisicao('/bff/api/v1/metricas/funil'), contexto(FUNIL))

      expect(resposta.status).toBe(422)
      await expect(resposta.json()).resolves.toEqual({ detail: 'filtro invalido' })
    })
  })

  it('responde 502 sem detalhe quando a API esta inacessivel', async () => {
    // O texto de um erro de rede nomeia host e porta internos, e quem o
    // receberia aqui e o navegador.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED 10.0.0.4:8000')))

    const resposta = await GET(requisicao('/bff/api/v1/metricas/funil'), contexto(FUNIL))

    expect(resposta.status).toBe(502)
    const corpo = await resposta.text()
    expect(corpo).toEqual(JSON.stringify({ erro: 'api_inacessivel' }))
    expect(corpo).not.toContain('10.0.0.4')
  })
})

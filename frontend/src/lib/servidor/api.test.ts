import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { chamarApi } from './api'

function respostaOk() {
  return vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
}

describe('chamarApi', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ADMIN_TOKEN = 'segredo'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('manda o token de admin, que e a unica razao de este modulo existir', async () => {
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/api/v1/metricas/funil', {})

    expect(api.mock.calls[0][1].headers['X-Admin-Token']).toBe('segredo')
  })

  it('monta a URL sobre `MOBIA_API_BASE`', async () => {
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/api/v1/metricas/funil', {
      busca: new URLSearchParams({ de: '2026-08-01' }),
    })

    expect(String(api.mock.calls[0][0])).toBe(
      'http://backend:8000/api/v1/metricas/funil?de=2026-08-01',
    )
  })

  it('cai no localhost quando `MOBIA_API_BASE` nao esta configurada', async () => {
    delete process.env.MOBIA_API_BASE
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/health', {})

    expect(String(api.mock.calls[0][0])).toBe('http://localhost:8000/health')
  })

  it('manda header vazio quando nao ha token, para o backend responder 403', async () => {
    // Levantar aqui trocaria a mensagem util da tela -- "e configuracao do
    // ambiente, nao um problema do seu filtro" -- por um erro generico.
    delete process.env.MOBIA_ADMIN_TOKEN
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/api/v1/metricas/funil', {})

    expect(api.mock.calls[0][1].headers['X-Admin-Token']).toBe('')
  })

  describe('cache e correlacao sao mutuamente exclusivos (D6)', () => {
    it('com `revalidarEmSegundos` a chamada e cacheada e NAO leva `X-Request-Id`', async () => {
      // Header entra na chave do Data Cache do Next. Um id por requisicao daria
      // uma entrada de cache por acesso -- taxa de acerto zero -- e desfaria a
      // propriedade de que N navegadores com o painel aberto viram UMA chamada
      // por minuto ao FastAPI. Nada ficaria vermelho: por isso a asserção.
      const api = respostaOk()
      vi.stubGlobal('fetch', api)

      await chamarApi('/api/v1/metricas/funil', { revalidarEmSegundos: 60 })

      const init = api.mock.calls[0][1]
      expect(init.next).toEqual({ revalidate: 60 })
      expect(init.cache).toBeUndefined()
      expect(init.headers['X-Request-Id']).toBeUndefined()
    })

    it('sem `revalidarEmSegundos` a chamada e `no-store` e pode levar o id', async () => {
      const api = respostaOk()
      vi.stubGlobal('fetch', api)

      await chamarApi('/api/v1/metricas/funil', { idDeRequisicao: 'req-1' })

      const init = api.mock.calls[0][1]
      expect(init.cache).toBe('no-store')
      expect(init.next).toBeUndefined()
      expect(init.headers['X-Request-Id']).toBe('req-1')
    })
  })

  it('repassa metodo, corpo e `Content-Type`', async () => {
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/api/v1/conversas/assumir', {
      metodo: 'POST',
      corpo: '{"a":1}',
      tipoDoCorpo: 'application/json',
    })

    const init = api.mock.calls[0][1]
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"a":1}')
    expect(init.headers['Content-Type']).toBe('application/json')
  })
})

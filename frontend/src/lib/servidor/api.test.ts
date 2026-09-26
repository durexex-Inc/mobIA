import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { chamarApi } from './api'

function respostaOk() {
  return vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
}

describe('chamarApi', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('manda o access token de quem esta logado como Bearer (TEC-309, D7)', async () => {
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/api/v1/metricas/funil', { acesso: 'jwt-da-anelise' })

    expect(api.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-da-anelise')
  })

  it('nunca manda o `X-Admin-Token`, nem com a variavel antiga no ambiente', async () => {
    // A TEC-309 tirou o token compartilhado do frontend. Um ambiente que ainda
    // tenha a variavel nao pode fazer o painel voltar a entrar como um ADMIN
    // sem usuario.
    process.env.MOBIA_ADMIN_TOKEN = 'segredo-antigo'
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/api/v1/metricas/funil', { acesso: 'jwt' })

    expect(JSON.stringify(api.mock.calls[0][1].headers)).not.toContain('segredo-antigo')
    delete process.env.MOBIA_ADMIN_TOKEN
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

  it('sem `acesso`, nao manda credencial nenhuma', async () => {
    // E o caso das rotas de `/auth/*`, que produzem o token. Numa rota
    // protegida, o FastAPI recusa -- que e o certo para quem esqueceu a sessao.
    const api = respostaOk()
    vi.stubGlobal('fetch', api)

    await chamarApi('/api/v1/auth/login', { metodo: 'POST' })

    expect(api.mock.calls[0][1].headers).toEqual({})
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

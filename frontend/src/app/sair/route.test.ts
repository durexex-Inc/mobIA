import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../test/token'
import { criarSessao, lerSessao } from '@/lib/servidor/sessao'
import { POST } from './route'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const PAINEL = 'https://painel.exemplo.com'

function envio({ sessao, origem = PAINEL }: { sessao?: string; origem?: string } = {}) {
  const cabecalhos = new Headers({ origin: origem })
  if (sessao) {
    cabecalhos.set('cookie', `mobia_sessao=${sessao}`)
  }
  return new NextRequest(new URL('/sair', PAINEL), { method: 'POST', headers: cabecalhos })
}

function apiRespondendo() {
  const api = vi.fn<(url: URL | string, init: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify({ ok: true })),
  )
  vi.stubGlobal('fetch', api)
  return api
}

describe('POST /sair', () => {
  let id = ''

  beforeEach(async () => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ORIGEM_DO_PAINEL = PAINEL
    limparArmazem()
    id = await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'refresh-da-sessao' })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.MOBIA_ORIGEM_DO_PAINEL
  })

  it('revoga o refresh no FastAPI', async () => {
    const api = apiRespondendo()

    await POST(envio({ sessao: id }))

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/api/v1/auth/logout')
    expect(JSON.parse(String(api.mock.calls[0][1].body))).toEqual({ refresh: 'refresh-da-sessao' })
  })

  it('apaga a sessao e o cookie, e vai ao login com 303', async () => {
    apiRespondendo()

    const resposta = await POST(envio({ sessao: id }))

    expect(resposta.status).toBe(303)
    expect(resposta.headers.get('location')).toBe(`${PAINEL}/login`)
    expect(await lerSessao(id)).toBeNull()
    const [cookie] = resposta.headers.getSetCookie()
    expect(cookie).toMatch(/^mobia_sessao=;/)
    expect(cookie).toContain('Max-Age=0')
  })

  it('cenario: manda limpar o cache da origem, para o "voltar" nao reexibir o painel', async () => {
    apiRespondendo()

    const resposta = await POST(envio({ sessao: id }))

    expect(resposta.headers.get('clear-site-data')).toBe('"cache"')
  })

  it('com o FastAPI fora do ar, sai assim mesmo', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')))

    const resposta = await POST(envio({ sessao: id }))

    expect(resposta.headers.get('location')).toBe(`${PAINEL}/login`)
    expect(await lerSessao(id)).toBeNull()
  })

  it('sem sessao, so vai ao login, sem chamar o FastAPI', async () => {
    const api = apiRespondendo()

    const resposta = await POST(envio())

    expect(api).not.toHaveBeenCalled()
    expect(resposta.headers.get('location')).toBe(`${PAINEL}/login`)
  })

  it('de outra origem, nao sai', async () => {
    const api = apiRespondendo()

    const resposta = await POST(envio({ sessao: id, origem: 'https://site-externo.com' }))

    expect(api).not.toHaveBeenCalled()
    expect(await lerSessao(id)).not.toBeNull()
    expect(resposta.headers.getSetCookie()).toEqual([])
  })
})

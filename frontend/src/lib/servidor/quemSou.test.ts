import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { limparArmazem } from '../../../test/armazem-em-memoria'
import { ACESSO_VALIDO } from '../../../test/token'
import { quemSou, quemSouDaRequisicao, SessaoRecusada } from './quemSou'
import { criarSessao } from './sessao'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const cookiesDaRequisicao = new Map<string, string>()
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (nome: string) =>
      cookiesDaRequisicao.has(nome) ? { value: cookiesDaRequisicao.get(nome) } : undefined,
  }),
}))

function apiRespondendo(corpo: unknown, status = 200) {
  const api = vi.fn<(url: URL | string, init: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify(corpo), { status }),
  )
  vi.stubGlobal('fetch', api)
  return api
}

const ME = { usuarioId: 'u-1', papel: 'GERENTE', corretorId: null, permissoes: ['VER_FUNIL'] }

describe('quemSou', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('le `/auth/me` com o JWT da sessao e devolve as permissoes como conjunto', async () => {
    const api = apiRespondendo(ME)

    const quem = await quemSou('jwt-da-anelise')

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/api/v1/auth/me')
    expect((api.mock.calls[0][1].headers as Record<string, string>).Authorization).toBe(
      'Bearer jwt-da-anelise',
    )
    expect(quem.papel).toBe('GERENTE')
    expect(quem.permissoes.has('VER_FUNIL')).toBe(true)
  })

  it('401 vira `SessaoRecusada`, que as paginas traduzem em volta ao login', async () => {
    apiRespondendo({ detail: 'x' }, 401)

    await expect(quemSou('jwt-vencido')).rejects.toBeInstanceOf(SessaoRecusada)
  })
})

describe('quemSouDaRequisicao (o que o layout usa)', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
    cookiesDaRequisicao.clear()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sem sessao, `null` -- e o FastAPI nem e chamado', async () => {
    const api = apiRespondendo(ME)

    expect(await quemSouDaRequisicao()).toBeNull()
    expect(api).not.toHaveBeenCalled()
  })

  it('com o FastAPI fora do ar, `null`, e nao excecao: o layout nao e a guarda', async () => {
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')))

    expect(await quemSouDaRequisicao()).toBeNull()
  })

  it('com sessao, a identidade', async () => {
    cookiesDaRequisicao.set('mobia_sessao', await criarSessao({ acesso: ACESSO_VALIDO, refresh: 'r' }))
    apiRespondendo(ME)

    expect((await quemSouDaRequisicao())?.papel).toBe('GERENTE')
  })
})

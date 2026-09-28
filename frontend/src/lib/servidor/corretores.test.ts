import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buscarCorretores, ErroDeCorretores } from './corretores'

function responde(corpo: unknown, status = 200, cabecalhos: Record<string, string> = {}) {
  return new Response(JSON.stringify(corpo), { status, headers: cabecalhos })
}

const CORRETOR = {
  id: 'c-1',
  nome: 'Ana Souza',
  email: 'ana@imobiliaria.com',
  telefone: '11999998888',
  creci: null,
  especialidades: ['COMPRA'],
  regioesAtuacao: ['Centro'],
  horarioInicio: 8,
  horarioFim: 18,
  capacidadeDiaria: 5,
  plantao: false,
  gerente: false,
  ativo: true,
}

describe('buscarCorretores', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('busca SEM `?ativos=` -- a lista traz ativos e inativos juntos (D6)', async () => {
    const api = vi.fn().mockResolvedValue(responde([CORRETOR]))
    vi.stubGlobal('fetch', api)

    const corretores = await buscarCorretores('jwt')

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/api/v1/corretores')
    expect(corretores).toEqual([CORRETOR])
  })

  it('manda o access token como Bearer', async () => {
    const api = vi.fn().mockResolvedValue(responde([]))
    vi.stubGlobal('fetch', api)

    await buscarCorretores('jwt-do-admin')

    expect(api.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-do-admin')
  })

  it('recusa do backend lanca ErroDeCorretores com status e requestId', async () => {
    const api = vi
      .fn()
      .mockResolvedValue(responde({ detail: 'boom' }, 500, { 'x-request-id': 'req-1' }))
    vi.stubGlobal('fetch', api)

    await expect(buscarCorretores('jwt')).rejects.toMatchObject({
      name: 'ErroDeCorretores',
      status: 500,
      requestId: 'req-1',
    })
  })

  it('403 vem sem requestId quando a resposta nao trouxe cabecalho', async () => {
    const api = vi.fn().mockResolvedValue(responde({ detail: 'proibido' }, 403))
    vi.stubGlobal('fetch', api)

    try {
      await buscarCorretores('jwt')
      throw new Error('deveria ter lancado')
    } catch (erro) {
      expect(erro).toBeInstanceOf(ErroDeCorretores)
      expect((erro as ErroDeCorretores).requestId).toBeNull()
    }
  })
})

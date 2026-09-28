import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buscarImoveis, ErroDeImoveis } from './imoveis'

function responde(corpo: unknown, status = 200, cabecalhos: Record<string, string> = {}) {
  return new Response(JSON.stringify(corpo), { status, headers: cabecalhos })
}

const IMOVEL = {
  id: 'i-1',
  codigo: 'AP-001',
  titulo: 'Apartamento no Centro',
  descricao: 'Dois quartos',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  status: 'INATIVO',
  precoVenda: 35_000_000,
  precoAluguel: null,
  condominio: null,
  iptuMensal: null,
  bairro: 'Centro',
  cidade: 'Porto Alegre',
  uf: 'RS',
  zona: null,
  latitude: null,
  longitude: null,
  areaUtilM2: 70,
  quartos: 2,
  suites: 1,
  banheiros: 2,
  vagas: 1,
  caracteristicas: [],
  fotos: [],
  atualizadoEm: '2026-09-28T12:00:00Z',
}

describe('buscarImoveis', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('busca SEM `?status=` -- a lista traz todo status junto, inclusive INATIVO (D6)', async () => {
    const api = vi.fn().mockResolvedValue(responde({ itens: [IMOVEL], proximoCursor: null }))
    vi.stubGlobal('fetch', api)

    const imoveis = await buscarImoveis('jwt')

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/api/v1/imoveis')
    expect(imoveis).toEqual([IMOVEL])
  })

  it('manda o access token como Bearer', async () => {
    const api = vi.fn().mockResolvedValue(responde({ itens: [], proximoCursor: null }))
    vi.stubGlobal('fetch', api)

    await buscarImoveis('jwt-do-admin')

    expect(api.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-do-admin')
  })

  it('devolve so os itens, sem o proximoCursor (D6 -- sem paginacao nesta versao)', async () => {
    const api = vi
      .fn()
      .mockResolvedValue(responde({ itens: [IMOVEL], proximoCursor: 'AP-050' }))
    vi.stubGlobal('fetch', api)

    const imoveis = await buscarImoveis('jwt')

    expect(imoveis).toEqual([IMOVEL])
  })

  it('recusa do backend lanca ErroDeImoveis com status e requestId', async () => {
    const api = vi
      .fn()
      .mockResolvedValue(responde({ detail: 'boom' }, 500, { 'x-request-id': 'req-1' }))
    vi.stubGlobal('fetch', api)

    await expect(buscarImoveis('jwt')).rejects.toMatchObject({
      name: 'ErroDeImoveis',
      status: 500,
      requestId: 'req-1',
    })
  })

  it('403 vem sem requestId quando a resposta nao trouxe cabecalho', async () => {
    const api = vi.fn().mockResolvedValue(responde({ detail: 'proibido' }, 403))
    vi.stubGlobal('fetch', api)

    try {
      await buscarImoveis('jwt')
      throw new Error('deveria ter lancado')
    } catch (erro) {
      expect(erro).toBeInstanceOf(ErroDeImoveis)
      expect((erro as ErroDeImoveis).requestId).toBeNull()
    }
  })
})

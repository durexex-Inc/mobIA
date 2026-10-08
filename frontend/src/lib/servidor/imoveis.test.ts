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

    const { itens } = await buscarImoveis('jwt')

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/api/v1/imoveis')
    expect(itens).toEqual([IMOVEL])
  })

  it('manda o access token como Bearer', async () => {
    const api = vi.fn().mockResolvedValue(responde({ itens: [], proximoCursor: null }))
    vi.stubGlobal('fetch', api)

    await buscarImoveis('jwt-do-admin')

    expect(api.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-do-admin')
  })

  it('uma pagina so, por padrao: com cursor sobrando, diz que ha mais (TEC-401)', async () => {
    const api = vi
      .fn()
      .mockResolvedValue(responde({ itens: [IMOVEL], proximoCursor: 'AP-050' }))
    vi.stubGlobal('fetch', api)

    const resultado = await buscarImoveis('jwt')

    expect(api).toHaveBeenCalledOnce()
    expect(resultado).toEqual({ itens: [IMOVEL], haMais: true })
  })

  it('percorre as paginas em sequencia, cada uma pelo cursor da anterior (TEC-401, D2)', async () => {
    const api = vi
      .fn()
      .mockResolvedValueOnce(responde({ itens: [IMOVEL], proximoCursor: 'c-1' }))
      .mockResolvedValueOnce(responde({ itens: [{ ...IMOVEL, id: 'i-2' }], proximoCursor: 'c-2' }))
      .mockResolvedValueOnce(responde({ itens: [{ ...IMOVEL, id: 'i-3' }], proximoCursor: 'c-3' }))
    vi.stubGlobal('fetch', api)

    const { itens, haMais } = await buscarImoveis('jwt', 3)

    expect(api.mock.calls.map(([url]) => new URL(String(url)).searchParams.get('cursor'))).toEqual([
      null,
      'c-1',
      'c-2',
    ])
    expect(itens.map((i) => i.id)).toEqual(['i-1', 'i-2', 'i-3'])
    expect(haMais).toBe(true)
  })

  it('para quando a API nao devolve mais cursor, mesmo pedindo mais paginas', async () => {
    const api = vi
      .fn()
      .mockResolvedValueOnce(responde({ itens: [IMOVEL], proximoCursor: 'c-1' }))
      .mockResolvedValueOnce(responde({ itens: [{ ...IMOVEL, id: 'i-2' }], proximoCursor: null }))
    vi.stubGlobal('fetch', api)

    const { itens, haMais } = await buscarImoveis('jwt', 5)

    expect(api).toHaveBeenCalledTimes(2)
    expect(itens).toHaveLength(2)
    expect(haMais).toBe(false)
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

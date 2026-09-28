import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buscarImportacaoMaisRecente, ErroDeImportacao } from './importacaoDeImoveis'

function responde(corpo: unknown, status = 200, cabecalhos: Record<string, string> = {}) {
  return new Response(JSON.stringify(corpo), { status, headers: cabecalhos })
}

const IMPORTACAO = {
  importacaoId: 'imp-1',
  status: 'CONCLUIDO',
  nomeArquivo: 'imoveis.csv',
  processados: 10,
  inseridos: 8,
  atualizados: 1,
  inalterados: 1,
  rejeitados: 0,
  erros: [],
}

describe('buscarImportacaoMaisRecente', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('busca `GET /api/v1/imoveis/importacoes?limite=1` (D4)', async () => {
    const api = vi.fn().mockResolvedValue(responde({ itens: [IMPORTACAO] }))
    vi.stubGlobal('fetch', api)

    const importacao = await buscarImportacaoMaisRecente('jwt')

    const url = new URL(String(api.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/imoveis/importacoes')
    expect(url.searchParams.get('limite')).toBe('1')
    expect(importacao).toEqual(IMPORTACAO)
  })

  it('manda o access token como Bearer', async () => {
    const api = vi.fn().mockResolvedValue(responde({ itens: [] }))
    vi.stubGlobal('fetch', api)

    await buscarImportacaoMaisRecente('jwt-do-admin')

    expect(api.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-do-admin')
  })

  it('devolve null quando nunca houve importacao', async () => {
    const api = vi.fn().mockResolvedValue(responde({ itens: [] }))
    vi.stubGlobal('fetch', api)

    expect(await buscarImportacaoMaisRecente('jwt')).toBeNull()
  })

  it('recusa do backend lanca ErroDeImportacao com status e requestId', async () => {
    const api = vi
      .fn()
      .mockResolvedValue(responde({ detail: 'boom' }, 500, { 'x-request-id': 'req-1' }))
    vi.stubGlobal('fetch', api)

    await expect(buscarImportacaoMaisRecente('jwt')).rejects.toMatchObject({
      name: 'ErroDeImportacao',
      status: 500,
      requestId: 'req-1',
    })
  })

  it('403 vem sem requestId quando a resposta nao trouxe cabecalho', async () => {
    const api = vi.fn().mockResolvedValue(responde({ detail: 'proibido' }, 403))
    vi.stubGlobal('fetch', api)

    try {
      await buscarImportacaoMaisRecente('jwt')
      throw new Error('deveria ter lancado')
    } catch (erro) {
      expect(erro).toBeInstanceOf(ErroDeImportacao)
      expect((erro as ErroDeImportacao).requestId).toBeNull()
    }
  })
})

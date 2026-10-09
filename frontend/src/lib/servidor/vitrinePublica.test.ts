import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status })
}

const ITEM = {
  id: 'i-1',
  codigo: 'AP-1',
  titulo: 'Apartamento com vista',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  bairro: 'Centro',
  cidade: 'Florianópolis',
  uf: 'SC',
  areaUtilM2: 74,
  quartos: 2,
  suites: 1,
  banheiros: 2,
  vagas: 1,
  preco: 58000000,
  condominio: null,
  iptuMensal: null,
  caracteristicas: [],
  foto: null,
  latitude: null,
  longitude: null,
}

const VAZIA = { itens: [], total: 0, pagina: 1, porPagina: 12 }

describe('buscarVitrine', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('chama /portal/vitrine sem Authorization -- a rota e publica', async () => {
    const { buscarVitrine } = await import('./vitrinePublica')
    const api = vi.fn().mockResolvedValue(responde(VAZIA))
    vi.stubGlobal('fetch', api)

    await buscarVitrine({ operacao: 'VENDA' })

    const [url, opcoes] = api.mock.calls[0]
    expect(String(url)).toBe('http://backend:8000/portal/vitrine?operacao=VENDA')
    expect(opcoes.headers.Authorization).toBeUndefined()
  })

  it('manda os seis filtros, a ordem e a pagina na query string', async () => {
    const { buscarVitrine } = await import('./vitrinePublica')
    const api = vi.fn().mockResolvedValue(responde(VAZIA))
    vi.stubGlobal('fetch', api)

    await buscarVitrine({
      operacao: 'ALUGUEL',
      precoMinCentavos: 1000,
      precoMaxCentavos: 2000,
      tipo: 'CASA',
      quartosMin: 2,
      vagasMin: 1,
      regioes: ['Centro', 'Trindade'],
      ordem: 'menor_preco',
      pagina: 2,
    })

    const url = new URL(String(api.mock.calls[0][0]))
    expect(url.searchParams.get('operacao')).toBe('ALUGUEL')
    expect(url.searchParams.get('precoMin')).toBe('1000')
    expect(url.searchParams.get('precoMax')).toBe('2000')
    expect(url.searchParams.get('tipo')).toBe('CASA')
    expect(url.searchParams.get('quartosMin')).toBe('2')
    expect(url.searchParams.get('vagasMin')).toBe('1')
    expect(url.searchParams.getAll('regioes')).toEqual(['Centro', 'Trindade'])
    expect(url.searchParams.get('ordem')).toBe('menor_preco')
    expect(url.searchParams.get('pagina')).toBe('2')
  })

  it('descarta item invalido e devolve o total e a pagina', async () => {
    const { buscarVitrine } = await import('./vitrinePublica')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        responde({ itens: [ITEM, { ...ITEM, id: 'i-2', titulo: '' }], total: 30, pagina: 2, porPagina: 12 }),
      ),
    )

    const resultado = await buscarVitrine({ operacao: 'VENDA', pagina: 2 })

    expect(resultado.itens).toEqual([ITEM])
    expect(resultado).toMatchObject({ total: 30, pagina: 2, porPagina: 12 })
  })

  it('resposta que nao e 200 lanca', async () => {
    const { buscarVitrine } = await import('./vitrinePublica')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responde({}, 422)))

    await expect(buscarVitrine({ operacao: 'VENDA' })).rejects.toThrow('422')
  })
})

const DETALHE = {
  id: 'i-1',
  codigo: 'IT-9821',
  titulo: 'Apartamento com vista',
  descricao: 'Sala ampla com varanda.',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  bairro: 'Centro',
  cidade: 'Florianópolis',
  uf: 'SC',
  areaUtilM2: 74,
  quartos: 2,
  suites: 1,
  banheiros: 2,
  vagas: 1,
  precoVenda: 58000000,
  precoAluguel: null,
  condominio: null,
  iptuMensal: null,
  caracteristicas: ['varanda'],
  fotos: ['/portal/imoveis/i-1/fotos/f-1'],
  latitude: null,
  longitude: null,
}

describe('buscarDetalheDoImovel', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('chama /portal/imoveis/{id} sem Authorization', async () => {
    const { buscarDetalheDoImovel } = await import('./vitrinePublica')
    const api = vi.fn().mockResolvedValue(responde(DETALHE))
    vi.stubGlobal('fetch', api)

    const detalhe = await buscarDetalheDoImovel('i-1')

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/portal/imoveis/i-1')
    expect(api.mock.calls[0][1].headers.Authorization).toBeUndefined()
    expect(detalhe).toEqual(DETALHE)
  })

  it('404 lanca ErroDoPortal com o status e a mensagem do detail', async () => {
    const { buscarDetalheDoImovel, ErroDoPortal } = await import('./vitrinePublica')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responde({ detail: 'imovel nao disponivel' }, 404)),
    )

    await expect(buscarDetalheDoImovel('i-1')).rejects.toThrow(ErroDoPortal)
    try {
      await buscarDetalheDoImovel('i-1')
    } catch (erro) {
      expect(erro).toBeInstanceOf(ErroDoPortal)
      expect((erro as InstanceType<typeof ErroDoPortal>).status).toBe(404)
    }
  })

  it('id vai escapado na URL', async () => {
    const { buscarDetalheDoImovel } = await import('./vitrinePublica')
    const api = vi.fn().mockResolvedValue(responde(DETALHE))
    vi.stubGlobal('fetch', api)

    await buscarDetalheDoImovel('a/b')

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/portal/imoveis/a%2Fb')
  })
})

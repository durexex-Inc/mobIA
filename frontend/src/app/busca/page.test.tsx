import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BuscaPublica from './page'

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: () => {} }) }))

const buscarVitrine = vi.fn()
vi.mock('@/lib/servidor/vitrinePublica', () => ({
  buscarVitrine: (...args: unknown[]) => buscarVitrine(...args),
}))

// O Leaflet nao roda no jsdom (precisa de layout real); o que a pagina decide
// sobre o mapa -- quais pontos ele recebe -- e o que se afere aqui.
const mapa = vi.fn()
vi.mock('@/components/MapaDaVitrine', () => ({
  MapaDaVitrine: (props: { pontos: unknown[] }) => {
    mapa(props)
    return null
  },
}))

function imovel(sobrescreve: Record<string, unknown> = {}) {
  return {
    id: 'i-1',
    codigo: 'IT-9821',
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
    condominio: 65000,
    iptuMensal: null,
    caracteristicas: ['varanda'],
    foto: null,
    latitude: -27.584,
    longitude: -48.505,
    ...sobrescreve,
  }
}

function pagina(itens: unknown[], total = itens.length, numero = 1) {
  return { itens, total, pagina: numero, porPagina: 12 }
}

async function paginaCom(parametros: Record<string, string>) {
  return BuscaPublica({ params: Promise.resolve({}), searchParams: Promise.resolve(parametros) })
}

describe('BuscaPublica', () => {
  beforeEach(() => {
    buscarVitrine.mockReset()
    mapa.mockReset()
  })

  it('CA-01: sem filtro (so a operacao padrao), lista os imoveis ativos com o total', async () => {
    buscarVitrine.mockResolvedValue(pagina([imovel()]))

    render(await paginaCom({}))

    expect(buscarVitrine).toHaveBeenCalledWith(expect.objectContaining({ operacao: 'VENDA' }))
    expect(screen.getByRole('heading', { name: 'Imóveis à venda' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Apartamento com vista' })).toHaveAttribute('href', '/busca/i-1')
    expect(screen.getByText('1 imóvel disponível')).toBeInTheDocument()
  })

  it('CA-02: os filtros da URL chegam a busca, e cada um vira uma etiqueta removivel', async () => {
    buscarVitrine.mockResolvedValue(pagina([imovel()]))

    render(await paginaCom({ operacao: 'ALUGUEL', quartosMin: '2', regioes: 'Centro,Trindade' }))

    expect(buscarVitrine).toHaveBeenCalledWith(
      expect.objectContaining({ operacao: 'ALUGUEL', quartosMin: 2, regioes: ['Centro', 'Trindade'] }),
    )
    expect(screen.getByRole('heading', { name: 'Imóveis para alugar em Centro, Trindade' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Remover o filtro 2+ quartos' })).toHaveAttribute(
      'href',
      '/busca?operacao=ALUGUEL&regioes=Centro%2CTrindade',
    )
    expect(screen.getByRole('link', { name: 'Remover o filtro Centro' })).toHaveAttribute(
      'href',
      '/busca?operacao=ALUGUEL&quartosMin=2&regioes=Trindade',
    )
  })

  it('CA-03: sem resultado nenhum, mostra a mensagem em vez de uma lista vazia', async () => {
    buscarVitrine.mockResolvedValue(pagina([]))

    render(await paginaCom({}))

    expect(screen.getByText('Nenhum imóvel encontrado com esses filtros.')).toBeInTheDocument()
    expect(mapa).not.toHaveBeenCalled()
  })

  it('pagina alem da ultima oferece voltar para a primeira', async () => {
    buscarVitrine.mockResolvedValue(pagina([], 30, 9))

    render(await paginaCom({ pagina: '9' }))

    expect(screen.getByRole('link', { name: 'Ir para a primeira página' })).toHaveAttribute(
      'href',
      '/busca?operacao=VENDA',
    )
  })

  it('pagina com o intervalo mostrado e links que preservam os filtros', async () => {
    const itens = Array.from({ length: 12 }, (_, indice) => imovel({ id: `i-${indice}`, codigo: `C-${indice}` }))
    buscarVitrine.mockResolvedValue(pagina(itens, 30, 2))

    render(await paginaCom({ pagina: '2', ordem: 'menor_preco' }))

    expect(screen.getByText('Mostrando 13–24 de 30')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Página 2' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Página 3' })).toHaveAttribute(
      'href',
      '/busca?operacao=VENDA&ordem=menor_preco&pagina=3',
    )
  })

  it('o mapa recebe so os imoveis com coordenada', async () => {
    buscarVitrine.mockResolvedValue(
      pagina([imovel(), imovel({ id: 'i-2', latitude: null, longitude: null })]),
    )

    render(await paginaCom({}))

    expect(mapa).toHaveBeenCalledWith({
      pontos: [
        {
          id: 'i-1',
          titulo: 'Apartamento com vista',
          bairro: 'Centro',
          latitude: -27.584,
          longitude: -48.505,
          preco: 58000000,
        },
      ],
    })
  })
})

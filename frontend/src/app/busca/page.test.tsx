import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BuscaPublica from './page'

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: () => {} }) }))

const buscarVitrinePublica = vi.fn()
vi.mock('@/lib/servidor/vitrinePublica', () => ({
  buscarVitrinePublica: (...args: unknown[]) => buscarVitrinePublica(...args),
}))

function imovel(sobrescreve: Record<string, unknown> = {}) {
  return {
    id: 'i-1',
    titulo: 'Apartamento com vista',
    bairro: 'Centro',
    precoCentavos: 58000000,
    condominioCentavos: null,
    quartos: 2,
    vagas: 1,
    areaUtilM2: 74,
    diferencial: null,
    foto: null,
    url: null,
    ...sobrescreve,
  }
}

async function paginaCom(parametros: Record<string, string>) {
  return BuscaPublica({ params: Promise.resolve({}), searchParams: Promise.resolve(parametros) })
}

describe('BuscaPublica', () => {
  beforeEach(() => buscarVitrinePublica.mockReset())

  it('CA-01: sem filtro (so a operacao padrao), lista os imoveis ativos', async () => {
    buscarVitrinePublica.mockResolvedValue({
      itens: [imovel()],
      totalCandidatos: 1,
      relaxamentoAplicado: false,
    })

    render(await paginaCom({}))

    expect(buscarVitrinePublica).toHaveBeenCalledWith(expect.objectContaining({ operacao: 'VENDA' }))
    expect(screen.getByText('Apartamento com vista')).toBeInTheDocument()
  })

  it('CA-02: os filtros da URL chegam a busca', async () => {
    buscarVitrinePublica.mockResolvedValue({ itens: [], totalCandidatos: 0, relaxamentoAplicado: false })

    await paginaCom({ operacao: 'ALUGUEL', quartosMin: '2' })

    expect(buscarVitrinePublica).toHaveBeenCalledWith(
      expect.objectContaining({ operacao: 'ALUGUEL', quartosMin: 2 }),
    )
  })

  it('CA-03: sem resultado nenhum, mostra a mensagem em vez de uma grade vazia', async () => {
    buscarVitrinePublica.mockResolvedValue({ itens: [], totalCandidatos: 0, relaxamentoAplicado: false })

    render(await paginaCom({}))

    expect(screen.getByText('Nenhum imóvel encontrado com esses filtros.')).toBeInTheDocument()
  })

  it('quando ha mais candidatos do que itens, mostra a nota', async () => {
    buscarVitrinePublica.mockResolvedValue({
      itens: [imovel()],
      totalCandidatos: 5,
      relaxamentoAplicado: false,
    })

    render(await paginaCom({}))

    expect(screen.getByText('Mostrando os 1 mais relevantes de 5.')).toBeInTheDocument()
  })
})

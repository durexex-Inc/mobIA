import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ImovelCard } from '@/lib/imovel'

import { CardDeImovel } from './CardDeImovel'

const BASE: ImovelCard = {
  id: 'i1',
  titulo: 'Casa 3 quartos',
  bairro: 'Lagoa da Conceição',
  precoCentavos: 51_646_430,
  condominioCentavos: 85_000,
  quartos: 3,
  vagas: 2,
  areaUtilM2: 98,
  diferencial: 'Piscina e vista para a lagoa',
  foto: 'https://cdn.exemplo.com/f.jpg',
  url: null,
}

const DADOS_TEXTUAIS = ['R$ 516.464', '3 quartos', '2 vagas', '98 m² de área útil', 'Condomínio R$ 850']

describe('CardDeImovel', () => {
  it('mostra foto, titulo, bairro, preco, quartos, vagas, area util, condominio e diferencial (cenario 1)', () => {
    render(<CardDeImovel imovel={BASE} />)

    const card = screen.getByRole('article')
    expect(within(card).getByRole('img')).toBeInTheDocument()
    expect(within(card).getByRole('heading', { name: 'Casa 3 quartos' })).toBeInTheDocument()
    for (const texto of ['Lagoa da Conceição', ...DADOS_TEXTUAIS, 'Piscina e vista para a lagoa']) {
      expect(within(card).getByText(texto)).toBeInTheDocument()
    }
  })

  it('texto alternativo da foto (cenario 4)', () => {
    render(<CardDeImovel imovel={BASE} />)

    expect(screen.getByRole('img')).toHaveAttribute('alt', 'Foto de Casa 3 quartos em Lagoa da Conceição')
  })

  it('a foto carrega sob demanda e com a caixa reservada', () => {
    render(<CardDeImovel imovel={BASE} />)

    const foto = screen.getByRole('img')
    expect(foto).toHaveAttribute('loading', 'lazy')
    expect(foto).toHaveAttribute('width')
    expect(foto).toHaveAttribute('height')
  })

  it('sem foto, placeholder com o bairro e todos os dados textuais (cenario 2)', () => {
    render(<CardDeImovel imovel={{ ...BASE, bairro: 'Campeche', foto: null }} />)

    const card = screen.getByRole('article')
    expect(within(card).queryByRole('img')).not.toBeInTheDocument()
    // Duas vezes: no placeholder e na linha do bairro.
    expect(within(card).getAllByText('Campeche')).toHaveLength(2)
    for (const texto of DADOS_TEXTUAIS) {
      expect(within(card).getByText(texto)).toBeInTheDocument()
    }
  })

  it('com pagina no site, abre em nova aba (cenario 3)', () => {
    render(<CardDeImovel imovel={{ ...BASE, url: 'https://imobiliaria.com.br/imovel/1' }} />)

    const link = screen.getByRole('link', { name: /Casa 3 quartos/ })
    expect(link).toHaveAttribute('href', 'https://imobiliaria.com.br/imovel/1')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('sem pagina no site, expande a ficha no chat', () => {
    render(<CardDeImovel imovel={BASE} />)

    const botao = screen.getByRole('button', { name: 'Casa 3 quartos' })
    expect(botao).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(botao)

    expect(botao).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('article')).toHaveClass('card-imovel--expandido')
  })

  it('sem condominio nem diferencial, as linhas somem e o card fica', () => {
    render(<CardDeImovel imovel={{ ...BASE, condominioCentavos: null, diferencial: null }} />)

    expect(screen.queryByText(/Condomínio/)).not.toBeInTheDocument()
    expect(screen.getByText('R$ 516.464')).toBeInTheDocument()
  })
})

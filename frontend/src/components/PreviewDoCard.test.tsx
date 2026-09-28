import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Formulario, Imovel } from '@/lib/imoveis'
import { formularioDe } from '@/lib/imoveis'
import { PreviewDoCard } from './PreviewDoCard'

const IMOVEL: Imovel = {
  id: 'i-1',
  codigo: 'AP-001',
  titulo: 'Apartamento no Centro',
  descricao: 'Dois quartos, reformado',
  tipo: 'APARTAMENTO',
  operacao: 'AMBOS',
  status: 'DISPONIVEL',
  precoVenda: 35_000_000,
  precoAluguel: 250_000,
  condominio: 85_000,
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
  caracteristicas: ['Vista para o parque', 'Piscina'],
  fotos: [],
  atualizadoEm: '2026-09-28T12:00:00Z',
}

async function abrir() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Pré-visualizar card' }))
  })
}

beforeEach(() => {
  // jsdom nao implementa <dialog>.showModal/close -- mesmo dublê de
  // DesativarCorretor.test.tsx.
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute('open')
  }
})

describe('PreviewDoCard', () => {
  it('mostra o titulo alterado no formulario, nao o salvo (Gherkin 1)', async () => {
    const formulario: Formulario = { ...formularioDe(IMOVEL), titulo: 'Novo título, ainda não salvo' }
    render(<PreviewDoCard imovel={IMOVEL} formulario={formulario} fotos={[]} />)

    await abrir()

    const card = screen.getByRole('article')
    expect(within(card).getByRole('heading', { name: 'Novo título, ainda não salvo' })).toBeInTheDocument()
    expect(screen.queryByText('Apartamento no Centro')).not.toBeInTheDocument()
  })

  it('sem foto, o placeholder com o bairro aparece (Gherkin 2)', async () => {
    const formulario = formularioDe(IMOVEL)
    render(<PreviewDoCard imovel={IMOVEL} formulario={formulario} fotos={[]} />)

    await abrir()

    const card = screen.getByRole('article')
    expect(within(card).queryByRole('img')).not.toBeInTheDocument()
    expect(within(card).getAllByText('Centro').length).toBeGreaterThan(0)
  })

  it('uma foto da TEC-335 (caminho relativo) tambem cai no placeholder, sem imagem quebrada (D1)', async () => {
    const formulario = formularioDe(IMOVEL)
    render(
      <PreviewDoCard
        imovel={IMOVEL}
        formulario={formulario}
        fotos={['/api/v1/imoveis/i-1/fotos/f-1']}
      />,
    )

    await abrir()

    const card = screen.getByRole('article')
    // `urlSegura` exige URL absoluta -- o caminho relativo da TEC-335 e
    // recusado e o card cai no mesmo placeholder de "sem foto" (D1): a
    // pre-visualizacao reproduz fielmente essa lacuna, nao a esconde.
    expect(within(card).queryByRole('img')).not.toBeInTheDocument()
  })

  it('preco: prioriza venda sobre aluguel quando a operacao e AMBOS (D3)', async () => {
    const formulario = formularioDe(IMOVEL)
    render(<PreviewDoCard imovel={IMOVEL} formulario={formulario} fotos={[]} />)

    await abrir()

    expect(screen.getByText('R$ 350.000')).toBeInTheDocument()
    expect(screen.queryByText('R$ 2.500')).not.toBeInTheDocument()
  })

  it('preco: cai para aluguel quando nao ha venda', async () => {
    const formulario: Formulario = { ...formularioDe(IMOVEL), precoVenda: '' }
    render(<PreviewDoCard imovel={IMOVEL} formulario={formulario} fotos={[]} />)

    await abrir()

    expect(screen.getByText('R$ 2.500')).toBeInTheDocument()
  })

  it('diferencial vem das duas primeiras caracteristicas do formulario (D4)', async () => {
    const formulario = formularioDe(IMOVEL)
    render(<PreviewDoCard imovel={IMOVEL} formulario={formulario} fotos={[]} />)

    await abrir()

    expect(screen.getByText('Vista para o parque e Piscina')).toBeInTheDocument()
  })

  it('o botao comeca desabilitado quando `desabilitado` e passado (D2)', () => {
    const formulario = formularioDe(IMOVEL)
    render(<PreviewDoCard imovel={IMOVEL} formulario={formulario} fotos={[]} desabilitado />)

    expect(screen.getByRole('button', { name: 'Pré-visualizar card' })).toBeDisabled()
  })
})

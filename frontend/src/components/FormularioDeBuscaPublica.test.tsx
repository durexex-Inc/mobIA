import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FormularioDeBuscaPublica } from './FormularioDeBuscaPublica'

const push = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))

describe('FormularioDeBuscaPublica', () => {
  beforeEach(() => push.mockClear())

  it('e um GET para /busca, com "Buscar"', () => {
    render(<FormularioDeBuscaPublica filtros={{ operacao: 'VENDA' }} />)

    const formulario = screen.getByRole('form', { name: 'Buscar imóveis' })
    expect(formulario).toHaveAttribute('method', 'get')
    expect(formulario).toHaveAttribute('action', '/busca')
    expect(screen.getByRole('button', { name: 'Buscar' })).toBeInTheDocument()
  })

  it('enviar com os filtros preenchidos navega para a URL correspondente', () => {
    render(<FormularioDeBuscaPublica filtros={{ operacao: 'VENDA' }} />)

    fireEvent.change(screen.getByLabelText('Operação'), { target: { value: 'ALUGUEL' } })
    fireEvent.change(screen.getByLabelText('Preço mínimo'), { target: { value: '1000' } })
    fireEvent.change(screen.getByLabelText('Quartos (mínimo)'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Bairro ou região'), { target: { value: 'Centro, Trindade' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))

    expect(push).toHaveBeenCalledWith(
      '/busca?operacao=ALUGUEL&precoMin=1000&quartosMin=2&regioes=Centro%2CTrindade',
    )
  })

  it('os valores iniciais vem dos filtros da URL', () => {
    render(
      <FormularioDeBuscaPublica
        filtros={{ operacao: 'ALUGUEL', precoMinCentavos: 150050, quartosMin: 3 }}
      />,
    )

    expect(screen.getByLabelText('Operação')).toHaveValue('ALUGUEL')
    expect(screen.getByLabelText('Preço mínimo')).toHaveValue('1500.5')
    expect(screen.getByLabelText('Quartos (mínimo)')).toHaveValue(3)
  })
})

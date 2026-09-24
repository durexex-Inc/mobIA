import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Filtros } from './Filtros'

const PERIODO = { de: '2026-08-01', ate: '2026-08-22' }

describe('Filtros', () => {
  it('tem os cinco filtros da RN-17.3 mais o periodo', () => {
    render(<Filtros atuais={PERIODO} />)
    expect(screen.getByLabelText('De')).toHaveValue('2026-08-01')
    expect(screen.getByLabelText('Até')).toHaveValue('2026-08-22')
    expect(screen.getByLabelText('Canal')).toBeInTheDocument()
    expect(screen.getByLabelText('Intenção')).toBeInTheDocument()
    expect(screen.getByLabelText('Temperatura')).toBeInTheDocument()
    expect(screen.getByLabelText('Corretor')).toBeInTheDocument()
  })

  it('e um form GET, para funcionar sem JavaScript', () => {
    const { container } = render(<Filtros atuais={PERIODO} />)
    expect(container.querySelector('form')).toHaveAttribute('method', 'get')
  })

  it('mostra qual filtro o backend recusou', () => {
    render(
      <Filtros
        atuais={{ ...PERIODO, temperatura: 'MORNA' }}
        erro="temperatura='MORNA' nao e um valor conhecido"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('MORNA')
  })

  it('sem erro, nao ha alerta', () => {
    render(<Filtros atuais={PERIODO} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('so oferece as temperaturas que existem', () => {
    render(<Filtros atuais={PERIODO} />)
    const opcoes = Array.from(
      screen.getByLabelText('Temperatura').querySelectorAll('option'),
    ).map((o) => o.textContent)
    expect(opcoes).toEqual(['Todas', 'QUENTE', 'MORNO', 'FRIO'])
  })

  it('preserva o filtro ja aplicado ao redesenhar', () => {
    render(<Filtros atuais={{ ...PERIODO, canal: 'web', corretorId: 'abc-123' }} />)
    expect(screen.getByLabelText('Canal')).toHaveValue('web')
    expect(screen.getByLabelText('Corretor')).toHaveValue('abc-123')
  })
})

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FiltrosDeLeads } from './FiltrosDeLeads'

const push = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))

describe('FiltrosDeLeads', () => {
  beforeEach(() => push.mockClear())

  it('mudar uma lista aplica: URL limpa, com busca e ordem, e sem posicao', () => {
    render(
      <FiltrosDeLeads
        busca="centro"
        ordem="ultima_interacao_desc"
        filtros={{ canal: 'whatsapp' }}
        corretor={{ modo: 'oculto' }}
      />,
    )

    fireEvent.change(screen.getByLabelText('Temperatura'), { target: { value: 'QUENTE' } })

    expect(push).toHaveBeenCalledWith('/leads?busca=centro&ordenar=ultima_interacao_desc&temperatura=QUENTE&canal=whatsapp')
  })

  it('"Todos" tira o filtro da URL', () => {
    render(<FiltrosDeLeads ordem="score_desc" filtros={{ temperatura: 'FRIO' }} corretor={{ modo: 'oculto' }} />)

    fireEvent.change(screen.getByLabelText('Temperatura'), { target: { value: '' } })

    expect(push).toHaveBeenCalledWith('/leads')
  })

  it('sem JS o formulario e um GET para /leads, com "Filtrar"', () => {
    render(<FiltrosDeLeads ordem="score_desc" filtros={{}} corretor={{ modo: 'indisponivel' }} />)

    const formulario = screen.getByRole('form', { name: 'Filtros' })
    expect(formulario).toHaveAttribute('method', 'get')
    expect(formulario).toHaveAttribute('action', '/leads')
    expect(screen.getByRole('button', { name: 'Filtrar' })).toBeInTheDocument()
  })
})

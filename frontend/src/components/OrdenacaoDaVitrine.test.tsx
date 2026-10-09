import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { OrdenacaoDaVitrine } from './OrdenacaoDaVitrine'

const push = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))

describe('OrdenacaoDaVitrine', () => {
  beforeEach(() => push.mockClear())

  it('trocar a ordem navega mantendo os filtros e volta para a primeira pagina', () => {
    render(<OrdenacaoDaVitrine filtros={{ operacao: 'ALUGUEL', quartosMin: 2, pagina: 4 }} />)

    fireEvent.change(screen.getByLabelText('Ordenar por'), { target: { value: 'maior_preco' } })

    expect(push).toHaveBeenCalledWith('/busca?operacao=ALUGUEL&quartosMin=2&ordem=maior_preco')
  })

  it('abre na ordem da URL, ou em "Mais recentes"', () => {
    const { unmount } = render(<OrdenacaoDaVitrine filtros={{ operacao: 'VENDA' }} />)
    expect(screen.getByLabelText('Ordenar por')).toHaveValue('recentes')
    unmount()

    render(<OrdenacaoDaVitrine filtros={{ operacao: 'VENDA', ordem: 'maior_area' }} />)
    expect(screen.getByLabelText('Ordenar por')).toHaveValue('maior_area')
  })
})

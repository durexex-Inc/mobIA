import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Menu } from './Menu'

function quem(papel: string, permissoes: string[]) {
  return { usuarioId: 'u-1', papel, corretorId: null, permissoes: new Set(permissoes) }
}

describe('Menu', () => {
  it('desenha os itens que as permissoes abrem, e o nome do papel', () => {
    render(<Menu quem={quem('ADMIN', ['VER_FUNIL', 'CONFIGURAR_AGENTE'])} />)

    const menu = screen.getByRole('navigation', { name: 'Menu principal' })
    expect(menu).toHaveTextContent('Funil')
    expect(screen.getByRole('link', { name: 'Administração' })).toHaveAttribute('href', '/admin')
    expect(screen.getByText('Administrador')).toBeInTheDocument()
  })

  it('GERENTE nao ve a administracao', () => {
    render(<Menu quem={quem('GERENTE', ['VER_FUNIL', 'VER_LEADS'])} />)

    expect(screen.getByRole('link', { name: 'Funil' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Administração' })).not.toBeInTheDocument()
  })

  it('tem o botao "Sair", que e um POST para `/sair` (TEC-310)', () => {
    render(<Menu quem={quem('GERENTE', ['VER_FUNIL'])} />)

    const formulario = screen.getByRole('button', { name: 'Sair' }).closest('form')
    expect(formulario).toHaveAttribute('method', 'post')
    expect(formulario).toHaveAttribute('action', '/sair')
  })

  it('CORRETOR ve leads e pedidos de interesse, e nem funil nem administracao (TEC-321, TEC-404)', () => {
    render(<Menu quem={quem('CORRETOR', ['VER_LEADS', 'ATENDER_LEAD'])} />)

    // Os dois vem de VER_LEADS (D9 da TEC-404); o funil e a administracao
    // continuam fora, porque o CORRETOR nao tem as permissoes deles.
    expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual([
      '/leads',
      '/interesses',
    ])
    expect(screen.getByText('Corretor')).toBeInTheDocument()
  })
})

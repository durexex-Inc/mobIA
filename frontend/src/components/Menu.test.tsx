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

  it('CORRETOR nao ve nenhum dos dois', () => {
    render(<Menu quem={quem('CORRETOR', ['VER_LEADS', 'ATENDER_LEAD'])} />)

    expect(screen.queryAllByRole('link')).toEqual([])
    expect(screen.getByText('Corretor')).toBeInTheDocument()
  })
})

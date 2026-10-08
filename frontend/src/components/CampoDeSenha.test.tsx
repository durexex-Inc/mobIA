import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CampoDeSenha } from './CampoDeSenha'

describe('CampoDeSenha', () => {
  it('comeca mascarado, com o rotulo "Senha"', () => {
    render(<CampoDeSenha />)

    expect(screen.getByLabelText('Senha')).toHaveAttribute('type', 'password')
  })

  it('mostra a senha ao clicar, e oculta de novo no segundo clique', () => {
    render(<CampoDeSenha />)

    fireEvent.click(screen.getByRole('button', { name: 'Mostrar senha' }))
    expect(screen.getByLabelText('Senha')).toHaveAttribute('type', 'text')

    fireEvent.click(screen.getByRole('button', { name: 'Ocultar senha' }))
    expect(screen.getByLabelText('Senha')).toHaveAttribute('type', 'password')
  })

  it('o nome do campo enviado ao formulario continua "senha"', () => {
    render(<CampoDeSenha />)

    expect(screen.getByLabelText('Senha')).toHaveAttribute('name', 'senha')
  })
})

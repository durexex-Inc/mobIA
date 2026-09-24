import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TextoComLinks } from './TextoComLinks'

describe('TextoComLinks', () => {
  it('linka http(s) com os tres rel exigidos', () => {
    render(<TextoComLinks texto="veja https://exemplo.com" />)

    const link = screen.getByRole('link', { name: 'https://exemplo.com' })
    expect(link).toHaveAttribute('href', 'https://exemplo.com/')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow')
  })

  it('mostra javascript: como texto simples, sem link', () => {
    // O cenario 3 do Gherkin da card, na altura em que ele foi escrito: "a
    // transcricao e exibida" e "o texto aparece como texto simples".
    render(<TextoComLinks texto="javascript:alert(1)" />)

    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument()
  })

  it('nao deixa marcacao da mensagem virar elemento', () => {
    // A prova de que nao ha `dangerouslySetInnerHTML` no caminho: um `<script>`
    // escrito pelo lead sai como texto visivel, nao como no do documento.
    const { container } = render(<TextoComLinks texto="<script>alert(1)</script>" />)

    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument()
  })
})

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CabecalhoDoChat } from './CabecalhoDoChat'

describe('CabecalhoDoChat', () => {
  it('se apresenta com o nome do assistente e o papel (cenario 4)', () => {
    render(<CabecalhoDoChat nome="Lia" />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Lia · Assistente virtual$/)
  })

  it('sem nome configurado, so o papel (cenario 4)', () => {
    render(<CabecalhoDoChat nome={null} />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Assistente virtual$/)
  })

  it.each([
    ['conectado', 'Conectado'],
    ['conectando', 'Conectando…'],
    ['reconectando', 'Reconectando…'],
    ['offline', 'Offline'],
  ] as const)('a conexao %s aparece em texto: "%s" (TEC-351)', (conexao, texto) => {
    render(<CabecalhoDoChat nome="Lia" conexao={conexao} />)

    const status = screen.getByRole('status')
    expect(status).toHaveTextContent(new RegExp(`^${texto}$`))
    // O ponto colorido e decoracao: a informacao esta no texto.
    expect(status.querySelector('.chat-embutido__marcador')).toHaveAttribute('aria-hidden', 'true')
  })

  it('sem conexao, nao ha linha de estado', () => {
    render(<CabecalhoDoChat nome="Lia" />)

    expect(screen.queryByRole('status')).toBeNull()
  })
})

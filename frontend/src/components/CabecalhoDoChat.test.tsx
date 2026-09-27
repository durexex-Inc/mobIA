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
})

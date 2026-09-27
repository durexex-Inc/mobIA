import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CabecalhoDoChat } from './CabecalhoDoChat'

describe('CabecalhoDoChat', () => {
  it('se apresenta com o nome do assistente (cenario 3)', () => {
    render(<CabecalhoDoChat nome="Lia" />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Lia')
  })
})

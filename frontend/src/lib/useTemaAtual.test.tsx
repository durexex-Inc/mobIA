import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useTemaAtual } from './useTemaAtual'

function Sonda() {
  return <p>{useTemaAtual()}</p>
}

describe('useTemaAtual', () => {
  afterEach(() => {
    delete document.documentElement.dataset.tema
  })

  it('sem escolha e sem `matchMedia`, e o claro', () => {
    render(<Sonda />)
    expect(screen.getByText('claro')).toBeInTheDocument()
  })

  it('acompanha a troca de `data-tema` sem remontar', async () => {
    render(<Sonda />)
    await act(async () => {
      document.documentElement.dataset.tema = 'escuro'
    })
    expect(await screen.findByText('escuro')).toBeInTheDocument()
  })
})

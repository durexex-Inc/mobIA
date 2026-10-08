import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BotaoDeTema } from './BotaoDeTema'

function sistemaEscuro(escuro: boolean) {
  vi.stubGlobal('matchMedia', (consulta: string) => ({
    matches: escuro && consulta.includes('dark'),
  }))
}

describe('BotaoDeTema', () => {
  beforeEach(() => {
    delete document.documentElement.dataset.tema
    document.cookie = 'mobia_tema=; max-age=0; path=/'
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sem escolha e com o sistema escuro, o clique vai para o claro e o grava', () => {
    sistemaEscuro(true)
    render(<BotaoDeTema />)

    fireEvent.click(screen.getByRole('button', { name: 'Alternar tema claro/escuro' }))

    expect(document.documentElement.dataset.tema).toBe('claro')
    expect(document.cookie).toContain('mobia_tema=claro')
  })

  it('alterna o tema ja escolhido, ignorando o sistema', () => {
    sistemaEscuro(true)
    document.documentElement.dataset.tema = 'claro'
    render(<BotaoDeTema />)

    fireEvent.click(screen.getByRole('button', { name: 'Alternar tema claro/escuro' }))

    expect(document.documentElement.dataset.tema).toBe('escuro')
  })
})

import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { LinkDoMenu } from './LinkDoMenu'

let caminhoAtual = '/'
vi.mock('next/navigation', () => ({ usePathname: () => caminhoAtual }))

describe('LinkDoMenu', () => {
  beforeEach(() => {
    caminhoAtual = '/'
  })

  it('marca a pagina aberta com `aria-current`', () => {
    render(<LinkDoMenu href="/">Funil</LinkDoMenu>)
    expect(screen.getByRole('link', { name: 'Funil' })).toHaveAttribute('aria-current', 'page')
  })

  it('`/` nao e atual numa subrota de outra area', () => {
    caminhoAtual = '/leads'
    render(<LinkDoMenu href="/">Funil</LinkDoMenu>)
    expect(screen.getByRole('link', { name: 'Funil' })).not.toHaveAttribute('aria-current')
  })

  it('a area continua atual nas subrotas dela', () => {
    caminhoAtual = '/leads/123'
    render(<LinkDoMenu href="/leads">Leads</LinkDoMenu>)
    expect(screen.getByRole('link', { name: 'Leads' })).toHaveAttribute('aria-current', 'page')
  })

  it('prefixo de texto nao conta: `/leadsx` nao e `/leads`', () => {
    caminhoAtual = '/leadsx'
    render(<LinkDoMenu href="/leads">Leads</LinkDoMenu>)
    expect(screen.getByRole('link', { name: 'Leads' })).not.toHaveAttribute('aria-current')
  })
})

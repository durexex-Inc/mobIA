import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AtualizacaoAutomatica } from './AtualizacaoAutomatica'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

/** Avanca o relogio falso e deixa o React aplicar o que os timers fizeram. */
async function passar(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

/** `document.visibilityState` e so leitura em navegador de verdade; em jsdom
 * da para redefinir, e e assim que o teste simula a aba oculta/visivel. */
function mudarVisibilidade(estado: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => estado,
  })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('AtualizacaoAutomatica', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    refresh.mockClear()
    mudarVisibilidade('visible')
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('nao atualiza antes de 30s', async () => {
    render(<AtualizacaoAutomatica atualizadoEm={new Date().toISOString()} />)

    await passar(29_000)

    expect(refresh).not.toHaveBeenCalled()
  })

  it('atualiza uma vez aos 30s, com a aba visivel', async () => {
    render(<AtualizacaoAutomatica atualizadoEm={new Date().toISOString()} />)

    await passar(30_000)

    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('mostra "Atualizado ha N s" contando a partir de `atualizadoEm`', async () => {
    render(<AtualizacaoAutomatica atualizadoEm={new Date().toISOString()} />)

    await passar(5_000)

    expect(screen.getByText('Atualizado há 5 s')).toBeInTheDocument()
  })

  it('nao atualiza durante 2 minutos com a aba oculta', async () => {
    render(<AtualizacaoAutomatica atualizadoEm={new Date().toISOString()} />)
    mudarVisibilidade('hidden')

    await passar(2 * 60_000)

    expect(refresh).not.toHaveBeenCalled()
  })

  it('ao voltar a ficar visivel depois de mais de 30s oculta, atualiza uma unica vez', async () => {
    render(<AtualizacaoAutomatica atualizadoEm={new Date().toISOString()} />)
    mudarVisibilidade('hidden')
    await passar(90_000)

    mudarVisibilidade('visible')

    expect(refresh).toHaveBeenCalledTimes(1)

    // E nao dispara de novo so por avancar mais um pouco, antes dos proximos 30s.
    await passar(5_000)
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('nao chama refresh a cada segundo -- so a cada 30s', async () => {
    render(<AtualizacaoAutomatica atualizadoEm={new Date().toISOString()} />)

    await passar(65_000)

    expect(refresh).toHaveBeenCalledTimes(2)
  })
})

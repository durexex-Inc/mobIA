import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AvisoDePronto } from './AvisoDePronto'

describe('AvisoDePronto', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('avisa o loader do site que o chat carregou (D7)', () => {
    // No jsdom a pagina nao esta num iframe, e `window.parent` e a propria janela.
    const aviso = vi.spyOn(window.parent, 'postMessage')

    render(<AvisoDePronto />)

    expect(aviso).toHaveBeenCalledTimes(1)
    expect(aviso).toHaveBeenCalledWith({ tipo: 'mobia:pronto' }, '*')
  })
})

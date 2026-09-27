import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BuscaDeLeads, ESPERA_DA_BUSCA_MS } from './BuscaDeLeads'

const replace = vi.fn<(url: string) => void>()
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }))

async function passar(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

function digitar(valor: string) {
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: valor } })
}

describe('BuscaDeLeads', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    replace.mockClear()
  })
  afterEach(() => vi.useRealTimers())

  it('espera 300 ms depois da ultima tecla', async () => {
    render(<BuscaDeLeads inicial="" ordem="score_desc" />)

    digitar('ce')
    await passar(ESPERA_DA_BUSCA_MS - 1)
    digitar('centro')
    await passar(ESPERA_DA_BUSCA_MS - 1)
    expect(replace).not.toHaveBeenCalled()

    await passar(1)
    expect(replace).toHaveBeenCalledExactlyOnceWith('/leads?busca=centro')
  })

  it('cenario: busca curta nao dispara consulta, e a lista continua como estava', async () => {
    render(<BuscaDeLeads inicial="" ordem="score_desc" />)

    digitar('a')
    await passar(10 * ESPERA_DA_BUSCA_MS)

    expect(replace).not.toHaveBeenCalled()
  })

  it('o telefone vai como foi digitado: quem normaliza e o backend', async () => {
    render(<BuscaDeLeads inicial="" ordem="score_desc" />)

    digitar('(48) 99999-0021')
    await passar(ESPERA_DA_BUSCA_MS)

    expect(replace).toHaveBeenCalledExactlyOnceWith('/leads?busca=%2848%29+99999-0021')
  })

  it('apagar a busca devolve a lista inteira', async () => {
    render(<BuscaDeLeads inicial="centro" ordem="score_desc" />)

    digitar('')
    await passar(ESPERA_DA_BUSCA_MS)

    expect(replace).toHaveBeenCalledExactlyOnceWith('/leads')
  })

  it('a busca que a URL ja tem nao navega de novo', async () => {
    render(<BuscaDeLeads inicial="centro" ordem="score_desc" />)

    digitar('centro ')
    await passar(ESPERA_DA_BUSCA_MS)

    expect(replace).not.toHaveBeenCalled()
  })

  it('buscar nao desfaz a ordenacao', async () => {
    render(<BuscaDeLeads inicial="" ordem="ultima_interacao_desc" />)

    digitar('centro')
    await passar(ESPERA_DA_BUSCA_MS)

    expect(replace).toHaveBeenCalledExactlyOnceWith(
      '/leads?busca=centro&ordenar=ultima_interacao_desc',
    )
  })

  it('Enter aplica na hora, sem esperar os 300 ms', () => {
    render(<BuscaDeLeads inicial="" ordem="score_desc" />)

    digitar('centro')
    fireEvent.submit(screen.getByRole('search'))

    expect(replace).toHaveBeenCalledExactlyOnceWith('/leads?busca=centro')
  })

  it('sem JS, e um GET para /leads com a busca e a ordem', () => {
    render(<BuscaDeLeads inicial="" ordem="ultima_interacao_desc" />)

    const formulario = screen.getByRole('search')
    expect(formulario).toHaveAttribute('method', 'get')
    expect(formulario).toHaveAttribute('action', '/leads')
    expect(screen.getByRole('searchbox')).toHaveAttribute('name', 'busca')
    expect(formulario.querySelector('input[type="hidden"]')).toHaveAttribute(
      'value',
      'ultima_interacao_desc',
    )
  })
})

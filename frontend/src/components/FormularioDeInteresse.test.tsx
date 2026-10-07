import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FormularioDeInteresse } from './FormularioDeInteresse'

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status })
}

function digitar(rotulo: string, valor: string) {
  fireEvent.change(screen.getByLabelText(rotulo), { target: { value: valor } })
}

async function enviar() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: /Quero ser contatado/ }))
  })
}

describe('FormularioDeInteresse', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('CA-01: envia o telefone e mostra a confirmacao', async () => {
    const api = vi.fn().mockResolvedValue(responde({ recebido: true }, 201))
    vi.stubGlobal('fetch', api)

    render(<FormularioDeInteresse imovelId="i-1" />)
    digitar('Telefone', '11988887777')
    await enviar()

    expect(screen.getByRole('status')).toHaveTextContent('Recebemos seu pedido!')
    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/portal/imoveis/i-1/interesse')
  })

  it('CA-02: telefone invalido mostra a mensagem do backend, sem sumir o formulario', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responde({ detail: 'telefone invalido' }, 422)),
    )

    render(<FormularioDeInteresse imovelId="i-1" />)
    digitar('Telefone', 'abc')
    await enviar()

    expect(screen.getByRole('alert')).toHaveTextContent('telefone invalido')
    expect(screen.getByRole('button', { name: /Quero ser contatado/ })).toBeInTheDocument()
  })

  it('CA-03: imovel indisponivel mostra a mensagem do 404', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responde({ detail: 'imovel nao disponivel' }, 404)),
    )

    render(<FormularioDeInteresse imovelId="i-1" />)
    digitar('Telefone', '11988887777')
    await enviar()

    expect(screen.getByRole('alert')).toHaveTextContent('imovel nao disponivel')
  })
})

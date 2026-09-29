import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { ReverterVersao } from './ReverterVersao'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { 'Content-Type': 'application/json' } })
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

describe('ReverterVersao', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    // jsdom nao implementa <dialog>.showModal/close -- mesmo dublê de
    // `EliminarDadosDoTitular.test.tsx`.
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open')
    }
    refresh.mockClear()
    api = vi.fn()
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('confirmar com o numero certo reverte e mostra o tempo (cenario: reverter com confirmacao)', async () => {
    api.mockResolvedValueOnce(responde({ ativa: { versao: 6 }, tempoDeAtivacaoMs: 12 }, 200))

    render(<ReverterVersao agente="agente" versao={6} />)
    await clicar('Reverter para esta versão')

    // O botao de confirmar comeca desabilitado.
    expect(screen.getByRole('button', { name: 'Confirmar reversão' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Número da versão'), { target: { value: '6' } })
    expect(screen.getByRole('button', { name: 'Confirmar reversão' })).toBeEnabled()

    await clicar('Confirmar reversão')

    expect(api).toHaveBeenCalledWith(
      '/bff/api/v1/prompts/AGENTE/rollback',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(JSON.parse(String(api.mock.calls[0][1]?.body))).toEqual({ versao: 6 })
    expect(screen.getByText('Revertido para a versão 6 em 12 ms.')).toBeInTheDocument()
    expect(refresh).not.toHaveBeenCalled()

    await clicar('Fechar')
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('numero errado mantem o botao desabilitado e nao chama a rede (cenario: confirmacao com numero errado)', async () => {
    render(<ReverterVersao agente="agente" versao={6} />)
    await clicar('Reverter para esta versão')

    fireEvent.change(screen.getByLabelText('Número da versão'), { target: { value: '5' } })

    expect(screen.getByRole('button', { name: 'Confirmar reversão' })).toBeDisabled()
    expect(api).not.toHaveBeenCalled()
  })

  it('404 (versao inexistente) mostra a mensagem do backend', async () => {
    api.mockResolvedValueOnce(responde({ detail: 'versao 6 nunca existiu' }, 404))

    render(<ReverterVersao agente="investidor" versao={6} />)
    await clicar('Reverter para esta versão')
    fireEvent.change(screen.getByLabelText('Número da versão'), { target: { value: '6' } })
    await clicar('Confirmar reversão')

    expect(screen.getByText('versao 6 nunca existiu')).toBeInTheDocument()
    expect(refresh).not.toHaveBeenCalled()
  })

  it('409 (ja e a ativa) mostra a mensagem do backend', async () => {
    api.mockResolvedValueOnce(responde({ detail: 'a versao 6 ja e a ativa' }, 409))

    render(<ReverterVersao agente="agente" versao={6} />)
    await clicar('Reverter para esta versão')
    fireEvent.change(screen.getByLabelText('Número da versão'), { target: { value: '6' } })
    await clicar('Confirmar reversão')

    expect(screen.getByText('a versao 6 ja e a ativa')).toBeInTheDocument()
  })
})

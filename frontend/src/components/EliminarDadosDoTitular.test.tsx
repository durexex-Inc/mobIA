import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { EliminarDadosDoTitular } from './EliminarDadosDoTitular'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const LEAD = '6f1c2a4e-0000-4000-8000-000000000001'

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

function digitar(texto: string) {
  fireEvent.change(screen.getByLabelText('Identificador do lead'), { target: { value: texto } })
}

describe('EliminarDadosDoTitular', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    // jsdom nao implementa <dialog>.showModal/close -- e testing-library trata
    // o conteudo de um <dialog> sem `open` como oculto da arvore de acessibilidade,
    // entao o dublê precisa refletir o atributo de verdade.
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open')
    }
    api = vi.fn(async () => new Response('{}'))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('o botao de confirmar comeca desabilitado', async () => {
    render(<EliminarDadosDoTitular leadId={LEAD} />)
    await clicar('Eliminar dados do titular')

    expect(screen.getByRole('button', { name: 'Confirmar eliminação' })).toBeDisabled()
  })

  it('digitar o identificador errado mantem desabilitado, e nada e chamado', async () => {
    render(<EliminarDadosDoTitular leadId={LEAD} />)
    await clicar('Eliminar dados do titular')
    digitar('id-errado')

    expect(screen.getByRole('button', { name: 'Confirmar eliminação' })).toBeDisabled()
    expect(api).not.toHaveBeenCalled()
  })

  it('digitar o identificador certo habilita, e confirmar faz o DELETE pelo proxy', async () => {
    render(<EliminarDadosDoTitular leadId={LEAD} />)
    await clicar('Eliminar dados do titular')
    digitar(LEAD)

    const confirmar = screen.getByRole('button', { name: 'Confirmar eliminação' })
    expect(confirmar).not.toBeDisabled()

    await clicar('Confirmar eliminação')

    expect(api).toHaveBeenCalledExactlyOnceWith(
      `/bff/api/v1/leads/${LEAD}/dados-pessoais`,
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(refresh).toHaveBeenCalledOnce()
    expect(screen.getByRole('status')).toHaveTextContent('Eliminação solicitada.')
  })

  it('cancelar fecha sem chamar nada', async () => {
    render(<EliminarDadosDoTitular leadId={LEAD} />)
    await clicar('Eliminar dados do titular')
    digitar(LEAD)

    await clicar('Cancelar')

    expect(api).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
  })

  it('401 diz que a sessao terminou', async () => {
    api.mockResolvedValue(new Response('{}', { status: 401 }))
    render(<EliminarDadosDoTitular leadId={LEAD} />)
    await clicar('Eliminar dados do titular')
    digitar(LEAD)

    await clicar('Confirmar eliminação')

    expect(screen.getByRole('alert')).toHaveTextContent('Sua sessão terminou.')
    expect(refresh).not.toHaveBeenCalled()
  })

  it('outro erro pede para tentar de novo', async () => {
    api.mockResolvedValue(new Response('{}', { status: 503 }))
    render(<EliminarDadosDoTitular leadId={LEAD} />)
    await clicar('Eliminar dados do titular')
    digitar(LEAD)

    await clicar('Confirmar eliminação')

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível concluir. Tente de novo.')
  })
})

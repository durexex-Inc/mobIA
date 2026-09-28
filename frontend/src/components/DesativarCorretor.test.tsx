import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Corretor } from '@/lib/corretores'
import { DesativarCorretor } from './DesativarCorretor'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const CORRETOR: Corretor = {
  id: 'c-1',
  nome: 'Ana Souza',
  email: 'ana@imobiliaria.com',
  telefone: '11999998888',
  creci: null,
  especialidades: ['COMPRA'],
  regioesAtuacao: ['Centro'],
  horarioInicio: 8,
  horarioFim: 18,
  capacidadeDiaria: 5,
  plantao: false,
  gerente: false,
  ativo: true,
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

describe('DesativarCorretor', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    // jsdom nao implementa <dialog>.showModal/close -- mesmo dublê de
    // EliminarDadosDoTitular.test.tsx.
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

  it('a confirmacao cita o texto exigido pela card', async () => {
    render(<DesativarCorretor corretor={CORRETOR} />)
    await clicar('Desativar')

    expect(screen.getByText(/histórico e os leads atribuídos são mantidos/)).toBeInTheDocument()
  })

  it('confirmar faz o PATCH com `{ ativo: false }` pelo proxy, e recarrega', async () => {
    render(<DesativarCorretor corretor={CORRETOR} />)
    await clicar('Desativar')

    await clicar('Confirmar desativação')

    expect(api).toHaveBeenCalledExactlyOnceWith(
      '/bff/api/v1/corretores/c-1',
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ ativo: false }) }),
    )
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('cancelar nao chama nada', async () => {
    render(<DesativarCorretor corretor={CORRETOR} />)
    await clicar('Desativar')

    await clicar('Cancelar')

    expect(api).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
  })

  it('401 diz que a sessao terminou', async () => {
    api.mockResolvedValue(new Response('{}', { status: 401 }))
    render(<DesativarCorretor corretor={CORRETOR} />)
    await clicar('Desativar')

    await clicar('Confirmar desativação')

    expect(screen.getByRole('alert')).toHaveTextContent('Sua sessão terminou.')
    expect(refresh).not.toHaveBeenCalled()
  })

  it('outro erro pede para tentar de novo', async () => {
    api.mockResolvedValue(new Response('{}', { status: 503 }))
    render(<DesativarCorretor corretor={CORRETOR} />)
    await clicar('Desativar')

    await clicar('Confirmar desativação')

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível desativar. Tente de novo.')
  })
})

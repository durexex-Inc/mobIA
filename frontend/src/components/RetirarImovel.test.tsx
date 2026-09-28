import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { Imovel } from '@/lib/imoveis'
import { RetirarImovel } from './RetirarImovel'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const IMOVEL: Imovel = {
  id: 'i-1',
  codigo: 'AP-001',
  titulo: 'Apartamento no Centro',
  descricao: 'Dois quartos',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  status: 'DISPONIVEL',
  precoVenda: 35_000_000,
  precoAluguel: null,
  condominio: null,
  iptuMensal: null,
  bairro: 'Centro',
  cidade: 'Porto Alegre',
  uf: 'RS',
  zona: null,
  latitude: null,
  longitude: null,
  areaUtilM2: 70,
  quartos: 2,
  suites: 1,
  banheiros: 2,
  vagas: 1,
  caracteristicas: [],
  fotos: [],
  atualizadoEm: '2026-09-28T12:00:00Z',
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

describe('RetirarImovel (D4)', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    // jsdom nao implementa <dialog>.showModal/close -- mesmo dublê de
    // DesativarCorretor.test.tsx.
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open')
    }
    api = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('a confirmacao explica a consequencia', async () => {
    render(<RetirarImovel imovel={IMOVEL} />)
    await clicar('Retirar das buscas')

    expect(
      screen.getByText(/deixa de ser recomendado pelo agente.*marcado como retirado/),
    ).toBeInTheDocument()
  })

  it('confirmar faz o DELETE pelo proxy, e recarrega', async () => {
    render(<RetirarImovel imovel={IMOVEL} />)
    await clicar('Retirar das buscas')

    await clicar('Confirmar retirada')

    expect(api).toHaveBeenCalledExactlyOnceWith(
      '/bff/api/v1/imoveis/i-1',
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('cancelar nao chama nada', async () => {
    render(<RetirarImovel imovel={IMOVEL} />)
    await clicar('Retirar das buscas')

    await clicar('Cancelar')

    expect(api).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
  })

  it('401 diz que a sessao terminou', async () => {
    api.mockResolvedValue(new Response('{}', { status: 401 }))
    render(<RetirarImovel imovel={IMOVEL} />)
    await clicar('Retirar das buscas')

    await clicar('Confirmar retirada')

    expect(screen.getByRole('alert')).toHaveTextContent('Sua sessão terminou.')
    expect(refresh).not.toHaveBeenCalled()
  })

  it('outro erro pede para tentar de novo', async () => {
    api.mockResolvedValue(new Response('{}', { status: 503 }))
    render(<RetirarImovel imovel={IMOVEL} />)
    await clicar('Retirar das buscas')

    await clicar('Confirmar retirada')

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível retirar. Tente de novo.')
  })
})

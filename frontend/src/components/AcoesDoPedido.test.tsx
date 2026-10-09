import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

import { AcoesDoPedido } from './AcoesDoPedido'

const PENDENTE_DA_ANA = {
  id: 'h-1',
  status: 'PENDENTE' as const,
  corretor: { id: 'c-a', nome: 'Ana' },
  notificadoEm: null,
  semCorretor: false,
}
const CORRETORES = [
  { id: 'c-a', nome: 'Ana' },
  { id: 'c-b', nome: 'Bia' },
]

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

describe('AcoesDoPedido', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    refresh.mockReset()
    api = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('o corretor dono assume pelo aceite e a tela recarrega', async () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir={false} corretores={[]} />)

    await clicar('Assumir')

    expect(api).toHaveBeenCalledWith('/bff/api/v1/handoffs/h-1/aceitar', expect.objectContaining({ method: 'POST' }))
    expect(refresh).toHaveBeenCalled()
  })

  it('quem nao e o dono nao ve Assumir', () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-b" podeAtribuir={false} corretores={[]} />)
    expect(screen.queryByRole('button', { name: 'Assumir' })).toBeNull()
  })

  it('o admin atribui a outro corretor', async () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId={null} podeAtribuir corretores={CORRETORES} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Corretor' }), { target: { value: 'c-b' } })
    await clicar('Atribuir')

    expect(api).toHaveBeenCalledWith(
      '/bff/api/v1/handoffs/h-1/atribuir',
      expect.objectContaining({ method: 'POST', body: '{"corretorId":"c-b"}' }),
    )
    expect(refresh).toHaveBeenCalled()
  })

  it('o seletor comeca no corretor atual, e Atribuir so habilita ao trocar', () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId={null} podeAtribuir corretores={CORRETORES} />)

    expect(screen.getByRole('combobox', { name: 'Corretor' })).toHaveValue('c-a')
    expect(screen.getByRole('button', { name: 'Atribuir' })).toBeDisabled()

    fireEvent.change(screen.getByRole('combobox', { name: 'Corretor' }), { target: { value: 'c-b' } })

    expect(screen.getByRole('button', { name: 'Atribuir' })).toBeEnabled()
  })

  it('sem corretor, o seletor comeca em "Escolha…" e Atribuir so habilita ao escolher', () => {
    render(
      <AcoesDoPedido
        atendimento={{ ...PENDENTE_DA_ANA, corretor: null, semCorretor: true }}
        corretorId={null}
        podeAtribuir
        corretores={CORRETORES}
      />,
    )

    const seletor = screen.getByRole('combobox', { name: 'Corretor' }) as HTMLSelectElement
    expect(seletor).toHaveValue('')
    expect(seletor.selectedOptions[0].text).toBe('Escolha…')
    expect(screen.getByRole('button', { name: 'Atribuir' })).toBeDisabled()

    fireEvent.change(seletor, { target: { value: 'c-b' } })

    expect(screen.getByRole('button', { name: 'Atribuir' })).toBeEnabled()
  })

  it('o dono atual fora da lista de ativos aparece selecionado, e Atribuir fica desabilitado', () => {
    render(
      <AcoesDoPedido
        atendimento={{ ...PENDENTE_DA_ANA, corretor: { id: 'c-x', nome: 'Xavier' } }}
        corretorId={null}
        podeAtribuir
        corretores={CORRETORES}
      />,
    )

    const seletor = screen.getByRole('combobox', { name: 'Corretor' }) as HTMLSelectElement
    expect(seletor).toHaveValue('c-x')
    expect(seletor.selectedOptions[0].text).toBe('Xavier')
    expect(screen.getByRole('button', { name: 'Atribuir' })).toBeDisabled()
  })

  it('sem podeAtribuir nao ha seletor', () => {
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir={false} corretores={CORRETORES} />)
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('atendimento concluido nao se atribui', () => {
    render(
      <AcoesDoPedido
        atendimento={{ ...PENDENTE_DA_ANA, status: 'CONCLUIDO' }}
        corretorId={null}
        podeAtribuir
        corretores={CORRETORES}
      />,
    )
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Atribuir' })).toBeNull()
  })

  it('recusa mostra o motivo e nao recarrega', async () => {
    api.mockResolvedValueOnce(new Response('{"detail":"handoff ja aceito"}', { status: 409 }))
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir={false} corretores={[]} />)

    await clicar('Assumir')

    expect(screen.getByRole('alert')).toHaveTextContent('Este pedido já foi assumido.')
    expect(refresh).not.toHaveBeenCalled()
  })

  it('409 na atribuicao diz que o atendimento foi concluido', async () => {
    api.mockResolvedValueOnce(new Response('{}', { status: 409 }))
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId={null} podeAtribuir corretores={CORRETORES} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Corretor' }), { target: { value: 'c-b' } })
    await clicar('Atribuir')

    expect(screen.getByRole('alert')).toHaveTextContent('Este atendimento já foi concluído.')
    expect(refresh).not.toHaveBeenCalled()
  })

  it.each([
    [401, 'Sua sessão terminou. Recarregue a página para entrar de novo.'],
    [403, 'Você não tem permissão para esta ação.'],
    [404, 'Este pedido não existe mais.'],
    [422, 'Escolha um corretor ativo.'],
    [500, 'Não foi possível concluir. Tente de novo.'],
  ])('a atribuicao recusada com %i diz por que', async (status, texto) => {
    api.mockResolvedValueOnce(new Response('{}', { status }))
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId={null} podeAtribuir corretores={CORRETORES} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Corretor' }), { target: { value: 'c-b' } })
    await clicar('Atribuir')

    expect(screen.getByRole('alert')).toHaveTextContent(texto)
  })

  it('sem rede, diz que nao foi possivel e nao recarrega', async () => {
    api.mockRejectedValueOnce(new TypeError('failed to fetch'))
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir={false} corretores={[]} />)

    await clicar('Assumir')

    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível concluir. Tente de novo.')
    expect(refresh).not.toHaveBeenCalled()
  })

  it('os botoes ficam desabilitados enquanto envia', async () => {
    let responder: (r: Response) => void = () => {}
    api.mockImplementationOnce(() => new Promise((r) => (responder = r)))
    render(<AcoesDoPedido atendimento={PENDENTE_DA_ANA} corretorId="c-a" podeAtribuir corretores={CORRETORES} />)

    await clicar('Assumir')

    expect(screen.getByRole('button', { name: 'Assumir' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Atribuir' })).toBeDisabled()

    await act(async () => responder(new Response('{}', { status: 200 })))
  })
})

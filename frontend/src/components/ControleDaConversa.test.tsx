import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { ControleDaConversa } from './ControleDaConversa'

const refresh = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

const EU = 'corretor-paulo'
const ANA = { corretorId: 'corretor-ana', nome: 'Ana' }

function atendidoPor(assumidoPor: { corretorId: string; nome: string }) {
  return { assumidoPor, assumidoEm: '2026-09-27T10:00:00+00:00' }
}

async function clicar(nome: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: nome }))
  })
}

describe('ControleDaConversa', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    api = vi.fn(async () => new Response('{}'))
    vi.stubGlobal('fetch', api)
    refresh.mockClear()
  })
  afterEach(() => vi.unstubAllGlobals())

  describe('cenario: assumir a conversa', () => {
    it('confirmar faz o POST pelo proxy e recarrega do servidor', async () => {
      render(<ControleDaConversa leadId="l-1" atendimento={null} meuCorretorId={EU} confirmar={() => true} />)

      await clicar('Assumir conversa')

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/leads/l-1/assumir',
        expect.objectContaining({ method: 'POST' }),
      )
      expect(refresh).toHaveBeenCalledOnce()
    })

    it('cancelar a confirmacao nao faz nada', async () => {
      render(<ControleDaConversa leadId="l-1" atendimento={null} meuCorretorId={EU} confirmar={() => false} />)

      await clicar('Assumir conversa')

      expect(api).not.toHaveBeenCalled()
      expect(refresh).not.toHaveBeenCalled()
    })

    it('com a conversa minha, a faixa aparece', () => {
      render(
        <ControleDaConversa
          leadId="l-1"
          atendimento={atendidoPor({ corretorId: EU, nome: 'Paulo' })}
          meuCorretorId={EU}
        />,
      )

      expect(screen.getByText('Você está no controle — o agente está em silêncio')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Assumir conversa' })).not.toBeInTheDocument()
    })
  })

  describe('cenario: conversa ja assumida por outra pessoa', () => {
    it('o 409 com o nome vira "A conversa ja esta com Ana", e nada recarrega', async () => {
      api.mockResolvedValue(
        new Response(JSON.stringify({ detail: { motivo: 'conversa_de_outro', assumidoPor: ANA } }), {
          status: 409,
        }),
      )
      render(<ControleDaConversa leadId="l-1" atendimento={null} meuCorretorId={EU} confirmar={() => true} />)

      await clicar('Assumir conversa')

      expect(screen.getByRole('alert')).toHaveTextContent('A conversa já está com Ana.')
      expect(refresh).not.toHaveBeenCalled()
    })

    it('sem o nome, manda recarregar em vez de tentar de novo', async () => {
      api.mockResolvedValue(
        new Response(JSON.stringify({ detail: { motivo: 'conversa_de_outro', assumidoPor: null } }), {
          status: 409,
        }),
      )
      render(<ControleDaConversa leadId="l-1" atendimento={null} meuCorretorId={EU} confirmar={() => true} />)

      await clicar('Assumir conversa')

      expect(screen.getByRole('alert')).toHaveTextContent('A conversa mudou de mãos. Recarregue a página.')
    })

    it('ao abrir, a conversa de outro diz com quem esta, sem a faixa', () => {
      render(<ControleDaConversa leadId="l-1" atendimento={atendidoPor(ANA)} meuCorretorId={EU} />)

      expect(screen.getByText('A conversa está com Ana.')).toBeInTheDocument()
      expect(screen.queryByText(/Você está no controle/)).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Assumir conversa' })).not.toBeInTheDocument()
    })
  })

  describe('cenario: devolver ao agente', () => {
    it('confirmar faz o POST de devolver e recarrega; a faixa sai com os dados novos', async () => {
      const { rerender } = render(
        <ControleDaConversa
          leadId="l-1"
          atendimento={atendidoPor({ corretorId: EU, nome: 'Paulo' })}
          meuCorretorId={EU}
          confirmar={() => true}
        />,
      )

      await clicar('Devolver ao agente')
      // O servidor devolve o detalhe sem atendimento; o `refresh` traz isso.
      rerender(<ControleDaConversa leadId="l-1" atendimento={null} meuCorretorId={EU} />)

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/leads/l-1/devolver',
        expect.objectContaining({ method: 'POST' }),
      )
      expect(refresh).toHaveBeenCalledOnce()
      expect(screen.queryByText(/Você está no controle/)).not.toBeInTheDocument()
    })

    it('a conversa de outro tambem se devolve: o backend aceita de qualquer corretor', () => {
      render(<ControleDaConversa leadId="l-1" atendimento={atendidoPor(ANA)} meuCorretorId={EU} />)

      expect(screen.getByRole('button', { name: 'Devolver ao agente' })).toBeInTheDocument()
    })
  })

  it('401 diz que a sessao terminou', async () => {
    api.mockResolvedValue(new Response('{}', { status: 401 }))
    render(<ControleDaConversa leadId="l-1" atendimento={null} meuCorretorId={EU} confirmar={() => true} />)

    await clicar('Assumir conversa')

    expect(screen.getByRole('alert')).toHaveTextContent('Sua sessão terminou.')
  })
})

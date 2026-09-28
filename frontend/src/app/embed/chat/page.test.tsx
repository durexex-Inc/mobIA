import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Privacidade } from '@/lib/privacidade'

import ChatEmbutido from './page'

const buscarAparencia = vi.fn()
vi.mock('@/lib/servidor/aparencia', () => ({ buscarAparencia: (tenant: string) => buscarAparencia(tenant) }))
vi.mock('@/lib/servidor/enderecoDoChat', () => ({ enderecoDoChat: () => 'ws://localhost:8000/widget/chat' }))
vi.mock('next/headers', () => ({ headers: async () => new Headers({ 'x-nonce': 'n' }) }))
vi.mock('next/navigation', () => ({
  notFound: () => {
    throw new Error('NOT_FOUND')
  },
}))
// A conversa de verdade abre um WebSocket; aqui basta saber se ela foi desenhada.
vi.mock('@/components/Conversa', () => ({
  Conversa: ({ privacidade }: { privacidade: Privacidade }) => (
    <p data-testid="conversa">{privacidade.avisoUrl}</p>
  ),
}))
vi.mock('@/components/AvisoDePronto', () => ({ AvisoDePronto: () => null }))

const APARENCIA = {
  nomeDoAssistente: 'Lia',
  corPrimaria: '#1D4ED8',
  posicaoDoBotao: 'DIREITA',
  dominios: [],
}

async function desenhar() {
  render(await ChatEmbutido({ searchParams: Promise.resolve({ tenant: 'imobiliaria-x' }) } as never))
}

describe('/embed/chat', () => {
  beforeEach(() => {
    buscarAparencia.mockReset()
  })

  it('com aviso e encarregado configurados, desenha a conversa com eles (TEC-352, D1)', async () => {
    buscarAparencia.mockResolvedValue({
      ...APARENCIA,
      privacidade: { avisoUrl: 'https://imob.com.br/privacidade', encarregadoEmail: 'dpo@imob.com.br' },
    })

    await desenhar()

    expect(screen.getByTestId('conversa')).toHaveTextContent('https://imob.com.br/privacidade')
  })

  it('sem eles, a conversa nao abre: cabecalho e "indisponivel" (TEC-352, D2)', async () => {
    buscarAparencia.mockResolvedValue({ ...APARENCIA, privacidade: null })

    await desenhar()

    expect(screen.queryByTestId('conversa')).toBeNull()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Lia · Assistente virtual')
    expect(screen.getByRole('status')).toHaveTextContent('O chat está indisponível no momento.')
  })
})

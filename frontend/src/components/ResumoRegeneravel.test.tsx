import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { ResumoRegeneravel } from './ResumoRegeneravel'

const AGORA = new Date('2026-09-27T12:00:00.000Z')

function resumo(geradoEm: string, extra: Record<string, unknown> = {}) {
  return {
    handoffId: 'h-1',
    texto: 'Resumo antigo, sem marcadores.',
    geradoEm,
    modelo: 'claude',
    fallback: false,
    ...extra,
  }
}

const HA_DUAS_HORAS = '2026-09-27T10:00:00.000Z'

function responde(corpo: unknown, status = 200, cabecalhos: Record<string, string> = {}) {
  return new Response(JSON.stringify(corpo), { status, headers: { 'Content-Type': 'application/json', ...cabecalhos } })
}

async function clicar() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Regenerar resumo' }))
  })
}

describe('ResumoRegeneravel', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(AGORA)
    api = vi.fn()
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  describe('cenario: pedir novo resumo', () => {
    it('mostra que esta gerando e troca pelo novo quando fica pronto', async () => {
      let responder: (r: Response) => void = () => {}
      api.mockImplementationOnce(() => new Promise((r) => (responder = r)))
      render(<ResumoRegeneravel resumo={resumo(HA_DUAS_HORAS)} podeRegenerar />)

      await clicar()

      expect(api).toHaveBeenCalledExactlyOnceWith(
        '/bff/api/v1/handoffs/h-1/resumo',
        expect.objectContaining({ method: 'POST' }),
      )
      const secao = screen.getByRole('region', { name: 'Resumo' })
      expect(secao).toHaveAttribute('aria-busy', 'true')
      expect(screen.getByRole('status')).toHaveTextContent('Gerando novo resumo…')
      expect(secao).toHaveTextContent('Resumo antigo')
      expect(screen.getByRole('button', { name: 'Regenerar resumo' })).toBeDisabled()

      await act(async () =>
        responder(
          responde({ resumo: 'Resumo novo.', geradoEm: AGORA.toISOString(), modelo: 'claude', resumoFallback: true }),
        ),
      )

      expect(secao).toHaveTextContent('Resumo novo.')
      expect(secao).not.toHaveTextContent('Resumo antigo')
      expect(secao).toHaveAttribute('aria-busy', 'false')
      // O rotulo segue o resumo novo, que veio de contingencia.
      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Resumo simplificado')
      // E o `geradoEm` novo reinicia a trava.
      expect(screen.getByRole('button', { name: 'Regenerar resumo' })).toBeDisabled()
      expect(screen.getByRole('status')).toHaveTextContent('Disponível em 60 s.')
    })
  })

  describe('cenario: trava de 60 segundos', () => {
    it('pedido ha 20 s: indisponivel pelos proximos 40', async () => {
      render(<ResumoRegeneravel resumo={resumo('2026-09-27T11:59:40.000Z')} podeRegenerar />)

      expect(screen.getByRole('button', { name: 'Regenerar resumo' })).toBeDisabled()
      expect(screen.getByRole('status')).toHaveTextContent('Disponível em 40 s.')

      await act(async () => {
        vi.advanceTimersByTime(39_000)
      })
      expect(screen.getByRole('button', { name: 'Regenerar resumo' })).toBeDisabled()

      await act(async () => {
        vi.advanceTimersByTime(1_000)
      })
      expect(screen.getByRole('button', { name: 'Regenerar resumo' })).toBeEnabled()
    })

    it('o 429 do backend e dito como trava, com o Retry-After, e nao como erro', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'resumo regenerado ha menos de 60 segundos' }, 429, { 'Retry-After': '15' }))
      render(<ResumoRegeneravel resumo={resumo(HA_DUAS_HORAS)} podeRegenerar />)

      await clicar()

      expect(screen.getByRole('status')).toHaveTextContent('O resumo foi gerado há menos de um minuto. Disponível em 15 s.')
      expect(screen.getByRole('button', { name: 'Regenerar resumo' })).toBeDisabled()
      expect(screen.getByRole('region', { name: 'Resumo' })).toHaveTextContent('Resumo antigo')
    })
  })

  it('falha de rede mantem o resumo anterior e diz o que houve', async () => {
    api.mockRejectedValueOnce(new TypeError('failed'))
    render(<ResumoRegeneravel resumo={resumo(HA_DUAS_HORAS)} podeRegenerar />)

    await clicar()

    expect(screen.getByRole('status')).toHaveTextContent('Não foi possível gerar o novo resumo. Tente de novo.')
    expect(screen.getByRole('region', { name: 'Resumo' })).toHaveTextContent('Resumo antigo')
    expect(screen.getByRole('button', { name: 'Regenerar resumo' })).toBeEnabled()
  })

  it('sem permissao, nao ha botao', () => {
    render(<ResumoRegeneravel resumo={resumo(HA_DUAS_HORAS)} podeRegenerar={false} />)

    expect(screen.queryByRole('button')).toBeNull()
  })
})

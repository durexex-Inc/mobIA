import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { EXPLICACAO_DA_JANELA } from '@/lib/resposta'
import type { Fala } from '@/lib/transcricao'
import { RespostaDoCorretor } from './RespostaDoCorretor'

const AGORA = new Date('2026-09-27T12:00:00.000Z')
const ABERTA = '2026-09-28T10:00:00.000Z'
const FECHADA = '2026-09-27T11:00:00.000Z'

function responde(corpo: unknown, status = 201) {
  return new Response(JSON.stringify(corpo), { status, headers: { 'Content-Type': 'application/json' } })
}

function montar(props: Partial<Parameters<typeof RespostaDoCorretor>[0]> = {}) {
  const aoEnviar = vi.fn<(fala: Fala) => void>()
  render(
    <RespostaDoCorretor
      leadId="l-1"
      conversaMinha
      janelaFechaEm={ABERTA}
      ultimaFalaDoLeadEm={null}
      aoEnviar={aoEnviar}
      {...props}
    />,
  )
  return aoEnviar
}

function digitar(texto: string) {
  fireEvent.change(screen.getByLabelText('Responder ao lead'), { target: { value: texto } })
}

async function enviar() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  })
}

describe('RespostaDoCorretor', () => {
  let api: Mock<(url: string, init?: RequestInit) => Promise<Response>>

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    vi.setSystemTime(AGORA)
    api = vi.fn(async () => responde({ id: 'f-1', em: '2026-09-27T12:00:01+00:00' }))
    vi.stubGlobal('fetch', api)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  describe('cenario: enviar mensagem com a conversa assumida', () => {
    it('manda texto e messageId pelo proxy, e a fala entra na conversa como do corretor', async () => {
      const aoEnviar = montar()

      digitar('Oi, sou o Paulo')
      await enviar()

      const [url, init] = api.mock.calls[0]
      expect(url).toBe('/bff/api/v1/leads/l-1/mensagens')
      const corpo = JSON.parse(String(init?.body)) as { texto: string; messageId: string }
      expect(corpo.texto).toBe('Oi, sou o Paulo')
      expect(corpo.messageId).toMatch(/^[0-9a-f-]{36}$/)
      expect(aoEnviar).toHaveBeenCalledExactlyOnceWith(
        expect.objectContaining({ id: 'f-1', autor: 'CORRETOR', conteudo: 'Oi, sou o Paulo' }),
      )
      expect(screen.getByLabelText('Responder ao lead')).toHaveValue('')
    })

    it('reenviar depois de falha reusa o messageId; texto novo gera outro', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'canal_falhou' }, 502))
      montar()

      digitar('Oi')
      await enviar()
      expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível entregar a mensagem.')
      await enviar()

      const ids = api.mock.calls.map(([, init]) => (JSON.parse(String(init?.body)) as { messageId: string }).messageId)
      expect(ids[0]).toBe(ids[1])

      digitar('Outra')
      await enviar()
      const terceiro = (JSON.parse(String(api.mock.calls[2][1]?.body)) as { messageId: string }).messageId
      expect(terceiro).not.toBe(ids[0])
    })
  })

  describe('cenario: conversa nao assumida', () => {
    it('o campo esta indisponivel e diz por que', () => {
      montar({ conversaMinha: false })

      expect(screen.getByLabelText('Responder ao lead')).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Enviar' })).toBeDisabled()
      expect(screen.getByText('Assuma a conversa para responder.')).toBeInTheDocument()
    })
  })

  describe('cenario: limite de caracteres', () => {
    it('com 1.001, o envio e bloqueado e o contador indica o excesso', () => {
      montar()

      digitar('a'.repeat(1001))

      expect(screen.getByText('1001/1000 — 1 caractere a mais')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Enviar' })).toBeDisabled()
      expect(screen.getByLabelText('Responder ao lead')).toHaveAttribute('aria-invalid', 'true')
    })

    it('com 1.000 envia', () => {
      montar()

      digitar('a'.repeat(1000))

      expect(screen.getByText('1000/1000')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Enviar' })).toBeEnabled()
    })
  })

  describe('cenario: fora da janela de 24 horas do WhatsApp', () => {
    it('com a janela fechada, bloqueia e explica que so template aprovado pode ser enviado', () => {
      montar({ janelaFechaEm: FECHADA })

      expect(screen.getByLabelText('Responder ao lead')).toBeDisabled()
      expect(screen.getByText(EXPLICACAO_DA_JANELA)).toBeInTheDocument()
    })

    it('a janela que fecha com a tela aberta desabilita o campo', async () => {
      montar({ janelaFechaEm: '2026-09-27T12:00:30.000Z' })
      expect(screen.getByLabelText('Responder ao lead')).toBeEnabled()

      await act(async () => {
        vi.advanceTimersByTime(60_000)
      })

      expect(screen.getByLabelText('Responder ao lead')).toBeDisabled()
    })

    it('a fala nova do lead reabre a janela', () => {
      montar({ janelaFechaEm: FECHADA, ultimaFalaDoLeadEm: '2026-09-27T11:59:00.000Z' })

      expect(screen.getByLabelText('Responder ao lead')).toBeEnabled()
    })

    it('o 409 da janela vindo do backend tambem bloqueia e explica', async () => {
      api.mockResolvedValueOnce(responde({ detail: 'janela_fechada' }, 409))
      montar()

      digitar('Oi')
      await enviar()

      expect(screen.getByLabelText('Responder ao lead')).toBeDisabled()
      expect(screen.getByText(EXPLICACAO_DA_JANELA)).toBeInTheDocument()
    })
  })

  it('site, sem janela: nunca fecha', () => {
    montar({ janelaFechaEm: null })

    expect(screen.getByLabelText('Responder ao lead')).toBeEnabled()
  })

  it('opt-out desabilita e diz por que', async () => {
    api.mockResolvedValueOnce(responde({ detail: 'lead_em_optout' }, 409))
    montar()

    digitar('Oi')
    await enviar()

    expect(screen.getByRole('alert')).toHaveTextContent('O lead pediu para não receber mensagens.')
    expect(screen.getByLabelText('Responder ao lead')).toBeDisabled()
  })
})

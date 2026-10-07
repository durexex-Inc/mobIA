import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SimuladorWhatsApp } from './SimuladorWhatsApp'

/**
 * jsdom nao fala o protocolo de WebSocket de verdade. Este duble so expoe o
 * suficiente para o componente: `send` grava o que foi mandado, e o teste
 * dispara `onopen`/`onmessage`/`onclose` manualmente -- mesmo espirito de
 * `vi.stubGlobal('fetch', ...)` usado no resto do projeto para testar
 * sem rede de verdade.
 */
class WebSocketFalso {
  static instancias: WebSocketFalso[] = []
  static readonly OPEN = 1

  enviados: string[] = []
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((evento: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(public url: string) {
    WebSocketFalso.instancias.push(this)
  }

  send(dados: string) {
    this.enviados.push(dados)
  }

  // Helpers de teste, nao da API real.
  abrir() {
    this.onopen?.()
  }

  receber(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

function ultimoSocket(): WebSocketFalso {
  const socket = WebSocketFalso.instancias.at(-1)
  if (!socket) {
    throw new Error('nenhum WebSocketFalso foi criado')
  }
  return socket
}

describe('SimuladorWhatsApp', () => {
  beforeEach(() => {
    WebSocketFalso.instancias = []
    vi.stubGlobal('WebSocket', WebSocketFalso)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('CA-01: manda o telefone no primeiro frame e mostra a conversa depois de "sessao"', async () => {
    render(<SimuladorWhatsApp endereco="ws://backend:8000/dev/simulador-whatsapp/chat" />)

    fireEvent.change(screen.getByLabelText('Telefone (com DDD)'), {
      target: { value: '11988887777' },
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Começar a conversar' }))
    })

    const socket = ultimoSocket()
    expect(socket.url).toBe('ws://backend:8000/dev/simulador-whatsapp/chat')
    await act(async () => socket.abrir())
    expect(JSON.parse(socket.enviados[0])).toEqual({ tipo: 'ola', telefone: '11988887777' })

    await act(async () => socket.receber({ tipo: 'sessao', telefone: '11988887777' }))

    expect(screen.getByLabelText('Mensagem')).toBeInTheDocument()
  })

  it('mostra o historico recebido depois da sessao', async () => {
    render(<SimuladorWhatsApp endereco="ws://backend:8000/dev/simulador-whatsapp/chat" />)
    fireEvent.change(screen.getByLabelText('Telefone (com DDD)'), {
      target: { value: '11988887777' },
    })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Começar a conversar' })))
    const socket = ultimoSocket()
    await act(async () => socket.abrir())
    await act(async () => socket.receber({ tipo: 'sessao', telefone: '11988887777' }))

    await act(async () =>
      socket.receber({
        tipo: 'historico',
        mensagens: [
          { papel: 'lead', texto: 'oi', em: '2026-10-07T10:00:00Z' },
          { papel: 'agente', texto: 'Olá! Como posso ajudar?', em: '2026-10-07T10:00:01Z' },
        ],
      }),
    )

    expect(screen.getByText('oi')).toBeInTheDocument()
    expect(screen.getByText('Olá! Como posso ajudar?')).toBeInTheDocument()
  })

  it('CA-02: envia mensagem nova e mostra a resposta do agente', async () => {
    render(<SimuladorWhatsApp endereco="ws://backend:8000/dev/simulador-whatsapp/chat" />)
    fireEvent.change(screen.getByLabelText('Telefone (com DDD)'), {
      target: { value: '11988887777' },
    })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Começar a conversar' })))
    const socket = ultimoSocket()
    await act(async () => socket.abrir())
    await act(async () => socket.receber({ tipo: 'sessao', telefone: '11988887777' }))

    fireEvent.change(screen.getByLabelText('Mensagem'), { target: { value: 'quero um apartamento' } })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Enviar' })))

    const enviado = JSON.parse(socket.enviados.at(-1) as string)
    expect(enviado).toMatchObject({ tipo: 'mensagem', texto: 'quero um apartamento' })
    expect(screen.getByText('quero um apartamento')).toBeInTheDocument()

    await act(async () => socket.receber({ tipo: 'mensagem', texto: 'Legal! Qual região você procura?' }))

    expect(screen.getByText('Legal! Qual região você procura?')).toBeInTheDocument()
  })

  it('frame de erro aparece na conversa, sem derrubar a tela', async () => {
    render(<SimuladorWhatsApp endereco="ws://backend:8000/dev/simulador-whatsapp/chat" />)
    fireEvent.change(screen.getByLabelText('Telefone (com DDD)'), {
      target: { value: '11988887777' },
    })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Começar a conversar' })))
    const socket = ultimoSocket()
    await act(async () => socket.abrir())
    await act(async () => socket.receber({ tipo: 'sessao', telefone: '11988887777' }))

    await act(async () =>
      socket.receber({ tipo: 'erro', codigo: 'texto_vazio', mensagem: 'Sua mensagem está vazia.' }),
    )

    expect(screen.getByText(/Sua mensagem está vazia\./)).toBeInTheDocument()
  })

  it('o fechamento do socket durante a conversa mostra o erro de conexão', async () => {
    render(<SimuladorWhatsApp endereco="ws://backend:8000/dev/simulador-whatsapp/chat" />)
    fireEvent.change(screen.getByLabelText('Telefone (com DDD)'), {
      target: { value: '11988887777' },
    })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Começar a conversar' })))
    const socket = ultimoSocket()
    await act(async () => socket.abrir())
    await act(async () => socket.receber({ tipo: 'sessao', telefone: '11988887777' }))

    await act(async () => socket.onclose?.())

    expect(screen.getByRole('alert')).toHaveTextContent('Conexão encerrada.')
  })
})

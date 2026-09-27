import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Conversa } from './Conversa'

const ENDERECO = 'ws://localhost:8000/widget/chat'
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

type Ouvinte = (evento: unknown) => void

/**
 * Um WebSocket de mentira: guarda o que o componente manda e deixa o teste
 * disparar `open`, `message` e `close` quando quiser. So a parte da API que o
 * componente usa.
 */
class SocketFalso {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instancias: SocketFalso[] = []

  readonly url: string
  readyState = SocketFalso.CONNECTING
  enviados: string[] = []
  fechadoPeloCliente = false
  private ouvintes = new Map<string, Ouvinte[]>()

  constructor(url: string) {
    this.url = url
    SocketFalso.instancias.push(this)
  }

  addEventListener(tipo: string, ouvinte: Ouvinte) {
    this.ouvintes.set(tipo, [...(this.ouvintes.get(tipo) ?? []), ouvinte])
  }

  removeEventListener(tipo: string, ouvinte: Ouvinte) {
    this.ouvintes.set(
      tipo,
      (this.ouvintes.get(tipo) ?? []).filter((o) => o !== ouvinte),
    )
  }

  send(dado: string) {
    if (this.readyState !== SocketFalso.OPEN) {
      throw new Error(`send com readyState ${this.readyState}`)
    }
    this.enviados.push(dado)
  }

  close() {
    this.fechadoPeloCliente = true
    this.readyState = SocketFalso.CLOSED
  }

  // --- metodos de teste ---

  private emitir(tipo: string, evento: unknown) {
    act(() => {
      for (const ouvinte of this.ouvintes.get(tipo) ?? []) {
        ouvinte(evento)
      }
    })
  }

  abrir() {
    this.readyState = SocketFalso.OPEN
    this.emitir('open', {})
  }

  receber(frame: object) {
    this.emitir('message', { data: JSON.stringify(frame) })
  }

  fechar(code = 1006) {
    this.readyState = SocketFalso.CLOSED
    this.emitir('close', { code })
  }

  frames(): Record<string, unknown>[] {
    return this.enviados.map((bruto) => JSON.parse(bruto) as Record<string, unknown>)
  }
}

function ultimoSocket(): SocketFalso {
  const socket = SocketFalso.instancias.at(-1)
  if (!socket) {
    throw new Error('nenhum socket aberto')
  }
  return socket
}

function escrever(texto: string) {
  fireEvent.change(screen.getByRole('textbox', { name: 'Mensagem' }), { target: { value: texto } })
}

function enviar(texto: string) {
  escrever(texto)
  fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
}

function montarAberto(): SocketFalso {
  render(<Conversa endereco={ENDERECO} />)
  const socket = ultimoSocket()
  socket.abrir()
  return socket
}

function frameDeMensagem(socket: SocketFalso): { id: string; texto: string } {
  const frame = socket.frames().find((f) => f.tipo === 'mensagem')
  if (!frame) {
    throw new Error('nenhuma mensagem enviada')
  }
  return frame as unknown as { id: string; texto: string }
}

beforeEach(() => {
  SocketFalso.instancias = []
  vi.stubGlobal('WebSocket', SocketFalso)
  localStorage.clear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Conversa', () => {
  it('abre o socket no endereco recebido e manda ola com sessao nula (D4)', () => {
    const socket = montarAberto()

    expect(socket.url).toBe(ENDERECO)
    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])
  })

  it('mostra "Enviando…" ate o ack e "Recebida" depois (cenario 1)', () => {
    const socket = montarAberto()

    enviar('Vocês têm apartamento no Campeche?')

    const balao = screen.getByText('Vocês têm apartamento no Campeche?').closest('li')
    expect(balao).not.toBeNull()
    expect(within(balao as HTMLElement).getByText('Enviando…')).toBeInTheDocument()
    const frame = frameDeMensagem(socket)
    expect(frame).toEqual({ tipo: 'mensagem', id: expect.stringMatching(UUID_V4), texto: 'Vocês têm apartamento no Campeche?' })

    socket.receber({ tipo: 'ack', messageId: frame.id })

    expect(within(balao as HTMLElement).getByText('Recebida')).toBeInTheDocument()
    expect(within(balao as HTMLElement).queryByText('Enviando…')).toBeNull()
  })

  it('limpa o campo depois de enviar', () => {
    montarAberto()

    enviar('Oi')

    expect(screen.getByRole('textbox', { name: 'Mensagem' })).toHaveValue('')
  })

  it('tres frames do agente viram tres baloes, na ordem (cenario 2)', () => {
    const socket = montarAberto()

    socket.receber({ tipo: 'mensagem', texto: 'Temos, sim.', kind: 'texto' })
    socket.receber({ tipo: 'mensagem', texto: 'São três opções.', kind: 'texto' })
    socket.receber({ tipo: 'mensagem', texto: 'Quer ver a primeira?', kind: 'texto' })

    const lista = screen.getByRole('list')
    const itens = within(lista).getAllByRole('listitem')
    expect(itens.map((li) => li.textContent)).toEqual(['Temos, sim.', 'São três opções.', 'Quer ver a primeira?'])
    for (const li of itens) {
      expect(li).toHaveClass('conversa__balao--agente')
    }
  })

  it('muitas_tentativas troca o campo pela mensagem e reabre depois da espera (cenario 3)', () => {
    vi.useFakeTimers()
    const socket = montarAberto()

    socket.receber({
      tipo: 'erro',
      codigo: 'muitas_tentativas',
      mensagem: 'Muitas tentativas, aguarde 20 s.',
      aguardeSegundos: 20,
    })
    socket.fechar(1013)

    expect(screen.getByText('Muitas tentativas, aguarde 20 s.')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Mensagem' })).toBeNull()
    expect(SocketFalso.instancias).toHaveLength(1)

    act(() => {
      vi.advanceTimersByTime(19_999)
    })
    expect(SocketFalso.instancias).toHaveLength(1)

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(SocketFalso.instancias).toHaveLength(2)

    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames()).toEqual([{ tipo: 'ola', sessao: null }])
    expect(screen.getByRole('textbox', { name: 'Mensagem' })).toBeInTheDocument()
  })

  it('sem ack em 10 s marca "Não enviada", e "Reenviar" manda o MESMO id', () => {
    vi.useFakeTimers()
    const socket = montarAberto()
    enviar('Tem garagem?')
    const { id } = frameDeMensagem(socket)

    act(() => {
      vi.advanceTimersByTime(9_999)
    })
    expect(screen.getByText('Enviando…')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(screen.getByText('Não enviada')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reenviar' }))

    const mensagens = socket.frames().filter((f) => f.tipo === 'mensagem')
    expect(mensagens).toEqual([
      { tipo: 'mensagem', id, texto: 'Tem garagem?' },
      { tipo: 'mensagem', id, texto: 'Tem garagem?' },
    ])
    // Um balao so: reenviar nao duplica a mensagem na tela.
    expect(screen.getAllByText('Tem garagem?')).toHaveLength(1)
    expect(screen.getByText('Enviando…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reenviar' })).toBeNull()

    // O prazo corre de novo a partir do reenvio.
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(screen.getByText('Não enviada')).toBeInTheDocument()
  })

  it('o prazo do primeiro envio nao derruba o reenvio feito antes dele', () => {
    vi.useFakeTimers()
    const socket = montarAberto()
    enviar('Aceita pet?')
    const { id } = frameDeMensagem(socket)

    // A queda marca a mensagem como falhou antes dos 10 s.
    act(() => {
      vi.advanceTimersByTime(3_000)
    })
    socket.fechar()
    fireEvent.click(screen.getByRole('button', { name: 'Reenviar' }))
    ultimoSocket().abrir()

    // Aos 10 s do primeiro envio (7 s do reenvio), o reenvio continua valendo.
    act(() => {
      vi.advanceTimersByTime(7_000)
    })
    expect(screen.getByText('Enviando…')).toBeInTheDocument()

    ultimoSocket().receber({ tipo: 'ack', messageId: id })
    expect(screen.getByText('Recebida')).toBeInTheDocument()
  })

  it('queda com mensagem pendente marca "Não enviada"; "Reenviar" abre socket novo, manda ola e depois a mensagem', () => {
    const socket = montarAberto()
    enviar('Qual o valor do condomínio?')
    const { id } = frameDeMensagem(socket)

    socket.fechar()

    expect(screen.getByText('Não enviada')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reenviar' }))

    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    expect(novo.enviados).toEqual([])
    novo.abrir()
    expect(novo.frames()).toEqual([
      { tipo: 'ola', sessao: null },
      { tipo: 'mensagem', id, texto: 'Qual o valor do condomínio?' },
    ])
    expect(screen.getByText('Enviando…')).toBeInTheDocument()
  })

  it('reenviar duas mensagens com o socket fechado abre um socket so', () => {
    const socket = montarAberto()
    enviar('Primeira')
    enviar('Segunda')
    socket.fechar()

    for (const botao of screen.getAllByRole('button', { name: 'Reenviar' })) {
      fireEvent.click(botao)
    }

    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames().map((f) => f.tipo === 'mensagem' && f.texto)).toEqual([false, 'Primeira', 'Segunda'])
  })

  it('durante a espera de muitas_tentativas o "Reenviar" fica desabilitado', () => {
    const socket = montarAberto()
    enviar('Oi')
    socket.receber({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'Muitas tentativas, aguarde 20 s.', aguardeSegundos: 20 })
    socket.fechar(1013)

    expect(screen.getByRole('button', { name: 'Reenviar' })).toBeDisabled()
  })

  it('evento do socket antigo nao chega a tela depois da troca', () => {
    const antigo = montarAberto()
    enviar('Oi')
    antigo.fechar()
    fireEvent.click(screen.getByRole('button', { name: 'Reenviar' }))
    ultimoSocket().abrir()

    antigo.receber({ tipo: 'mensagem', texto: 'fantasma', kind: 'texto' })
    antigo.fechar()

    expect(screen.queryByText('fantasma')).toBeNull()
    expect(screen.getByText('Enviando…')).toBeInTheDocument()
  })

  it('grava a sessao em localStorage["mobia:sessao"] (D4)', () => {
    const socket = montarAberto()

    socket.receber({ tipo: 'sessao', sessao: '6f1c2c7e-6a0b-4c1f-9d0e-1a2b3c4d5e6f' })

    expect(localStorage.getItem('mobia:sessao')).toBe('6f1c2c7e-6a0b-4c1f-9d0e-1a2b3c4d5e6f')
  })

  it('storage bloqueado nao interrompe a conversa (D4)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('bloqueado', 'SecurityError')
    })
    const socket = montarAberto()

    socket.receber({ tipo: 'sessao', sessao: '6f1c2c7e-6a0b-4c1f-9d0e-1a2b3c4d5e6f' })
    socket.receber({ tipo: 'mensagem', texto: 'Olá! Como posso ajudar?', kind: 'texto' })
    enviar('Quero alugar')

    expect(screen.getByText('Olá! Como posso ajudar?')).toBeInTheDocument()
    expect(frameDeMensagem(socket).texto).toBe('Quero alugar')
  })

  it('so espacos nao manda nada (D5)', () => {
    const socket = montarAberto()

    enviar('   \n  ')

    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  })

  it('manda o texto sem os espacos das pontas', () => {
    const socket = montarAberto()

    enviar('  Oi  ')

    expect(frameDeMensagem(socket).texto).toBe('Oi')
  })

  it('o campo tem teto de 1000 caracteres e um contador (D5)', () => {
    montarAberto()
    const campo = screen.getByRole('textbox', { name: 'Mensagem' })

    expect(campo).toHaveAttribute('maxLength', '1000')
    expect(campo).toHaveAttribute('placeholder', 'Escreva sua mensagem')
    expect(screen.getByText('0/1000')).toBeInTheDocument()

    escrever('Olá')

    expect(screen.getByText('3/1000')).toBeInTheDocument()
  })

  it('a lista de mensagens e anunciada com aria-live="polite" (D5)', () => {
    montarAberto()

    expect(screen.getByRole('list')).toHaveAttribute('aria-live', 'polite')
  })

  it('o balao da visitante leva a classe dela', () => {
    montarAberto()

    enviar('Oi')

    expect(screen.getByText('Oi').closest('li')).toHaveClass('conversa__balao--visitante')
  })

  it('desmontar fecha o socket e cancela o prazo pendente', () => {
    vi.useFakeTimers()
    const { unmount } = render(<Conversa endereco={ENDERECO} />)
    const socket = ultimoSocket()
    socket.abrir()
    enviar('Oi')
    expect(vi.getTimerCount()).toBe(1)

    unmount()

    expect(socket.fechadoPeloCliente).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('desmontar durante a espera de muitas_tentativas nao reabre depois', () => {
    vi.useFakeTimers()
    const { unmount } = render(<Conversa endereco={ENDERECO} />)
    const socket = ultimoSocket()
    socket.abrir()
    socket.receber({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'Muitas tentativas, aguarde 5 s.', aguardeSegundos: 5 })
    socket.fechar(1013)

    unmount()
    act(() => {
      vi.advanceTimersByTime(5_000)
    })

    expect(SocketFalso.instancias).toHaveLength(1)
  })

  it('em StrictMode, a montagem dupla deixa um socket vivo so', () => {
    render(
      <StrictMode>
        <Conversa endereco={ENDERECO} />
      </StrictMode>,
    )

    // O StrictMode de desenvolvimento monta duas vezes; se um dia deixar de
    // montar, este teste deixa de provar o que diz.
    expect(SocketFalso.instancias).toHaveLength(2)
    const [descartado, vivo] = SocketFalso.instancias
    expect(descartado.fechadoPeloCliente).toBe(true)
    expect(vivo.fechadoPeloCliente).toBe(false)

    // O `close` atrasado do socket descartado nao chega a tela.
    descartado.fechar()
    vivo.abrir()
    enviar('Oi')
    expect(vivo.frames()).toEqual([
      { tipo: 'ola', sessao: null },
      { tipo: 'mensagem', id: expect.stringMatching(UUID_V4), texto: 'Oi' },
    ])
  })
})

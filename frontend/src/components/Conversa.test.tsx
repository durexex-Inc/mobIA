import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Conversa } from './Conversa'

const ENDERECO = 'ws://localhost:8000/widget/chat'
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

const SESSAO = '6f1c2c7e-6a0b-4c1f-9d0e-1a2b3c4d5e6f'

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
  render(<Conversa endereco={ENDERECO} nome={null} />)
  const socket = ultimoSocket()
  socket.abrir()
  return socket
}

/**
 * O jsdom nao faz layout: `scrollHeight` e `clientHeight` sao sempre 0 e
 * `scrollTop` nao guarda o que se escreve nele. Aqui a lista ganha uma
 * geometria fixa e um `scrollTop` que guarda o valor.
 */
function comGeometria(lista: HTMLElement, { alturaTotal, alturaVisivel }: { alturaTotal: number; alturaVisivel: number }) {
  let topo = 0
  Object.defineProperty(lista, 'scrollHeight', { configurable: true, get: () => alturaTotal })
  Object.defineProperty(lista, 'clientHeight', { configurable: true, get: () => alturaVisivel })
  Object.defineProperty(lista, 'scrollTop', {
    configurable: true,
    get: () => topo,
    set: (valor: number) => {
      topo = valor
    },
  })
  return lista
}

function rolarPara(lista: HTMLElement, topo: number) {
  lista.scrollTop = topo
  fireEvent.scroll(lista)
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

  it('o texto puro que a TEC-346 gravava nao e retomado: o ola vai com sessao nula e a chave some (D1)', () => {
    localStorage.setItem('mobia:sessao', SESSAO)

    const socket = montarAberto()

    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])
    expect(localStorage.getItem('mobia:sessao')).toBeNull()
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

  it('se o socket reaberto depois da espera cair antes do open, o chat nao fica preso na espera', () => {
    vi.useFakeTimers()
    const socket = montarAberto()
    enviar('Oi')
    socket.receber({
      tipo: 'erro',
      codigo: 'muitas_tentativas',
      mensagem: 'Muitas tentativas, aguarde 20 s.',
      aguardeSegundos: 20,
    })
    socket.fechar(1013)
    expect(screen.getByRole('button', { name: 'Reenviar' })).toBeDisabled()

    act(() => {
      vi.advanceTimersByTime(20_000)
    })
    ultimoSocket().fechar(1006)

    expect(screen.queryByText('Muitas tentativas, aguarde 20 s.')).toBeNull()
    expect(screen.getByRole('textbox', { name: 'Mensagem' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reenviar' })).toBeEnabled()
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

  it('queda com mensagem pendente marca "Não enviada"; "Reenviar" abre socket novo, manda ola com a sessao e depois a mensagem', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    enviar('Qual o valor do condomínio?')
    const { id } = frameDeMensagem(socket)

    socket.fechar()

    expect(screen.getByText('Não enviada')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reenviar' }))

    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    expect(novo.enviados).toEqual([])
    novo.abrir()
    // A reconexao retoma a sessao em memoria: o servidor deduplica o id
    // dentro dela, e o agente nao perde o contexto (D4).
    expect(novo.frames()).toEqual([
      { tipo: 'ola', sessao: SESSAO },
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

  it('a lista de mensagens fica dentro de um log que anuncia so os baloes novos (D5)', () => {
    montarAberto()

    const registro = screen.getByRole('log')
    expect(registro).toHaveAttribute('aria-live', 'polite')
    expect(registro).toHaveAttribute('aria-relevant', 'additions')
    // `log` nao e papel permitido num `<ol>`: a lista continua lista, dentro dele.
    const lista = within(registro).getByRole('list')
    expect(lista.tagName).toBe('OL')
    expect(lista).not.toHaveAttribute('role')
    expect(lista).not.toHaveAttribute('aria-live')
  })

  it('Enter envia, pelo mesmo caminho do botao', () => {
    const socket = montarAberto()
    escrever('Oi')

    const campo = screen.getByRole('textbox', { name: 'Mensagem' })
    const naoImpedido = fireEvent.keyDown(campo, { key: 'Enter' })

    expect(naoImpedido).toBe(false)
    expect(frameDeMensagem(socket).texto).toBe('Oi')
    expect(campo).toHaveValue('')
  })

  it('Shift+Enter nao envia e deixa a quebra de linha acontecer', () => {
    const socket = montarAberto()
    escrever('Oi')

    const campo = screen.getByRole('textbox', { name: 'Mensagem' })
    const naoImpedido = fireEvent.keyDown(campo, { key: 'Enter', shiftKey: true })

    expect(naoImpedido).toBe(true)
    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])
    expect(campo).toHaveValue('Oi')
  })

  it('Enter durante a composicao de um IME nao envia', () => {
    const socket = montarAberto()
    escrever('Oi')

    const campo = screen.getByRole('textbox', { name: 'Mensagem' })
    const naoImpedido = fireEvent.keyDown(campo, { key: 'Enter', isComposing: true })

    expect(naoImpedido).toBe(true)
    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])
    expect(campo).toHaveValue('Oi')
  })

  it('balao do agente nao puxa para o fim quem rolou para cima para reler', () => {
    const socket = montarAberto()
    const lista = comGeometria(screen.getByRole('list'), { alturaTotal: 1000, alturaVisivel: 300 })
    rolarPara(lista, 100)

    socket.receber({ tipo: 'mensagem', texto: 'Temos, sim.', kind: 'texto' })

    expect(lista.scrollTop).toBe(100)
  })

  it('balao do agente rola para o fim quando a lista ja estava perto do fim', () => {
    const socket = montarAberto()
    const lista = comGeometria(screen.getByRole('list'), { alturaTotal: 1000, alturaVisivel: 300 })
    rolarPara(lista, 670)

    socket.receber({ tipo: 'mensagem', texto: 'Temos, sim.', kind: 'texto' })

    expect(lista.scrollTop).toBe(1000)
  })

  it('a mensagem da propria visitante sempre rola para o fim', () => {
    montarAberto()
    const lista = comGeometria(screen.getByRole('list'), { alturaTotal: 1000, alturaVisivel: 300 })
    rolarPara(lista, 100)

    enviar('Oi')

    expect(lista.scrollTop).toBe(1000)
  })

  it('o balao da visitante leva a classe dela', () => {
    montarAberto()

    enviar('Oi')

    expect(screen.getByText('Oi').closest('li')).toHaveClass('conversa__balao--visitante')
  })

  it('desmontar fecha o socket e cancela o prazo pendente', () => {
    vi.useFakeTimers()
    const { unmount } = render(<Conversa endereco={ENDERECO} nome={null} />)
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
    const { unmount } = render(<Conversa endereco={ENDERECO} nome={null} />)
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
        <Conversa endereco={ENDERECO} nome={null} />
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

// --- TEC-347: retomar, encerrar e dormir ----------------------------------

const AGORA = Date.UTC(2026, 8, 27, 12, 0, 0)
const UM_DIA_MS = 24 * 60 * 60 * 1000
const TRINTA_MIN_MS = 30 * 60 * 1000
const OUTRA_SESSAO = '415b23dc-823d-4926-9442-964169fdb758'

function guardarSessao(sessao: string, criadaEm: number) {
  localStorage.setItem('mobia:sessao', JSON.stringify({ sessao, criadaEm }))
}

function sessaoNoStorage(): unknown {
  const bruto = localStorage.getItem('mobia:sessao')
  return bruto === null ? null : JSON.parse(bruto)
}

/**
 * Um aviso de visibilidade como o loader manda. No jsdom `window.parent` e a
 * propria janela; outra janela e simulada com qualquer outro objeto em
 * `source` -- definido depois de construir, porque o `MessageEvent` do jsdom
 * so aceita janela ou porta de verdade no construtor.
 */
function avisar(data: unknown, source: unknown = window.parent) {
  const evento = new MessageEvent('message', { data })
  Object.defineProperty(evento, 'source', { value: source })
  act(() => {
    window.dispatchEvent(evento)
  })
}

function doze(): { papel: 'lead' | 'agente'; texto: string; em: string }[] {
  return Array.from({ length: 12 }, (_, i) => ({
    papel: i % 2 === 0 ? ('lead' as const) : ('agente' as const),
    texto: `fala ${i + 1}`,
    em: '2026-09-27T11:00:00Z',
  }))
}

function abrirMenuEEscolherEncerrar() {
  fireEvent.click(screen.getByRole('button', { name: 'Opções da conversa' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Encerrar conversa' }))
}

const PERGUNTA = 'Encerrar esta conversa? O histórico some desta tela.'

describe('Conversa -- retomada, encerramento e sono (TEC-347)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(AGORA)
  })

  it('cenario 1: com sessao valida guardada, o primeiro ola a leva e o historico repoe as 12 falas', () => {
    guardarSessao(SESSAO, AGORA - 2 * UM_DIA_MS)

    const socket = montarAberto()

    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: SESSAO }])

    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'historico', mensagens: doze() })

    const itens = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(itens).toHaveLength(12)
    expect(itens.map((li) => li.querySelector('.conversa__texto')?.textContent ?? li.textContent)).toEqual(
      doze().map((m) => m.texto),
    )
    for (const [i, li] of itens.entries()) {
      if (i % 2 === 0) {
        expect(li).toHaveClass('conversa__balao--visitante')
        expect(within(li).getByText('Recebida')).toBeInTheDocument()
      } else {
        expect(li).toHaveClass('conversa__balao--agente')
      }
    }
    expect(screen.queryByRole('button', { name: 'Reenviar' })).toBeNull()
    // Retomar a mesma sessao nao regrava: o prazo conta desde a criacao (D1).
    expect(sessaoNoStorage()).toEqual({ sessao: SESSAO, criadaEm: AGORA - 2 * UM_DIA_MS })
  })

  it('sem sessao guardada, o ola vai com null; a sessao emitida e gravada uma vez so', () => {
    const socket = montarAberto()
    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])

    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    expect(sessaoNoStorage()).toEqual({ sessao: SESSAO, criadaEm: AGORA })

    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    expect(sessaoNoStorage()).toEqual({ sessao: SESSAO, criadaEm: AGORA })
  })

  it('cenario 3: sessao guardada ha 31 dias abre com null e a chave e apagada', () => {
    guardarSessao(SESSAO, AGORA - 31 * UM_DIA_MS)

    const socket = montarAberto()

    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])
    expect(localStorage.getItem('mobia:sessao')).toBeNull()
  })

  it('em StrictMode, a montagem descartada nao consome a sessao guardada', () => {
    guardarSessao(SESSAO, AGORA - UM_DIA_MS)

    render(
      <StrictMode>
        <Conversa endereco={ENDERECO} nome={null} />
      </StrictMode>,
    )
    const [descartado, vivo] = SocketFalso.instancias
    descartado.fechar()
    vivo.abrir()

    expect(vivo.frames()).toEqual([{ tipo: 'ola', sessao: SESSAO }])
    expect(sessaoNoStorage()).toEqual({ sessao: SESSAO, criadaEm: AGORA - UM_DIA_MS })
  })

  it('o menu abre por um botao com aria-haspopup e fecha com Escape', () => {
    montarAberto()
    const botao = screen.getByRole('button', { name: 'Opções da conversa' })
    expect(botao).toHaveAttribute('aria-haspopup', 'menu')
    expect(botao).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('menu')).toBeNull()

    fireEvent.click(botao)
    expect(botao).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.keyDown(screen.getByRole('menuitem', { name: 'Encerrar conversa' }), { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(botao).toHaveAttribute('aria-expanded', 'false')
  })

  it('cenario 2: encerrar apaga o storage, zera a tela e abre socket novo com ola null', () => {
    guardarSessao(SESSAO, AGORA - UM_DIA_MS)
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'historico', mensagens: doze() })
    enviar('Pendente')
    expect(vi.getTimerCount()).toBe(1)

    abrirMenuEEscolherEncerrar()
    expect(screen.getByText(PERGUNTA)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Encerrar' }))

    expect(localStorage.getItem('mobia:sessao')).toBeNull()
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    expect(screen.queryByText(PERGUNTA)).toBeNull()
    expect(socket.fechadoPeloCliente).toBe(true)
    // O prazo do `ack` da mensagem pendente nao sobrevive ao encerramento.
    // O avanco de 0 ms so escoa os timers de 0 ms que o `focus()` do jsdom
    // agenda ao abrir o menu e a confirmacao; o do `ack` e de 10 s.
    act(() => {
      vi.advanceTimersByTime(0)
    })
    expect(vi.getTimerCount()).toBe(0)
    expect(SocketFalso.instancias).toHaveLength(2)

    // O `close` atrasado do socket antigo nao marca nada na tela nova.
    socket.fechar()
    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames()).toEqual([{ tipo: 'ola', sessao: null }])
    expect(screen.getByRole('textbox', { name: 'Mensagem' })).toBeInTheDocument()

    // A sessao nova que o servidor emitir e gravada do zero.
    novo.receber({ tipo: 'sessao', sessao: OUTRA_SESSAO })
    expect(sessaoNoStorage()).toEqual({ sessao: OUTRA_SESSAO, criadaEm: AGORA })
  })

  it('cenario 2: "Cancelar" fecha a confirmacao sem mudar nada', () => {
    guardarSessao(SESSAO, AGORA - UM_DIA_MS)
    const socket = montarAberto()
    socket.receber({ tipo: 'historico', mensagens: doze() })

    abrirMenuEEscolherEncerrar()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))

    expect(screen.queryByText(PERGUNTA)).toBeNull()
    expect(screen.getAllByRole('listitem')).toHaveLength(12)
    expect(sessaoNoStorage()).toEqual({ sessao: SESSAO, criadaEm: AGORA - UM_DIA_MS })
    expect(socket.fechadoPeloCliente).toBe(false)
    expect(SocketFalso.instancias).toHaveLength(1)
  })

  it('cenario 4: minimizado 30 min o socket dorme sem falha; reabrir retoma a sessao e o historico', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'mensagem', texto: 'Olá! Como posso ajudar?', kind: 'texto' })

    avisar({ tipo: 'mobia:visibilidade', aberto: false })
    act(() => {
      vi.advanceTimersByTime(TRINTA_MIN_MS - 1)
    })
    expect(socket.fechadoPeloCliente).toBe(false)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(socket.fechadoPeloCliente).toBe(true)
    socket.fechar(1000)

    expect(screen.queryByText('Não enviada')).toBeNull()
    expect(screen.getByText('Olá! Como posso ajudar?')).toBeInTheDocument()
    expect(SocketFalso.instancias).toHaveLength(1)

    avisar({ tipo: 'mobia:visibilidade', aberto: true })

    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames()).toEqual([{ tipo: 'ola', sessao: SESSAO }])
    novo.receber({ tipo: 'sessao', sessao: SESSAO })
    novo.receber({
      tipo: 'historico',
      mensagens: [
        { papel: 'agente', texto: 'Olá! Como posso ajudar?', em: '2026-09-27T11:00:00Z' },
        { papel: 'agente', texto: 'Ainda está por aí?', em: '2026-09-27T11:20:00Z' },
      ],
    })
    expect(within(screen.getByRole('list')).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Olá! Como posso ajudar?',
      'Ainda está por aí?',
    ])
  })

  it('reabrir antes de dormir nao abre socket novo e cancela o sono', () => {
    montarAberto()

    avisar({ tipo: 'mobia:visibilidade', aberto: false })
    act(() => {
      vi.advanceTimersByTime(TRINTA_MIN_MS - 1)
    })
    avisar({ tipo: 'mobia:visibilidade', aberto: true })
    act(() => {
      vi.advanceTimersByTime(TRINTA_MIN_MS)
    })

    expect(SocketFalso.instancias).toHaveLength(1)
    expect(ultimoSocket().fechadoPeloCliente).toBe(false)
  })

  it('frame recebido enquanto minimizado reinicia o prazo do sono', () => {
    const socket = montarAberto()
    avisar({ tipo: 'mobia:visibilidade', aberto: false })

    act(() => {
      vi.advanceTimersByTime(29 * 60 * 1000)
    })
    socket.receber({ tipo: 'mensagem', texto: 'Ainda está por aí?', kind: 'texto' })
    act(() => {
      vi.advanceTimersByTime(29 * 60 * 1000)
    })
    expect(socket.fechadoPeloCliente).toBe(false)

    act(() => {
      vi.advanceTimersByTime(60 * 1000)
    })
    expect(socket.fechadoPeloCliente).toBe(true)
  })

  it('aviso de outra janela, ou com aberto que nao e booleano, e ignorado (Review Focus 4)', () => {
    const socket = montarAberto()

    avisar({ tipo: 'mobia:visibilidade', aberto: false }, {})
    avisar({ tipo: 'mobia:visibilidade', aberto: 'false' })
    avisar({ tipo: 'outra:coisa', aberto: false })
    avisar('mobia:visibilidade')
    avisar(null)
    act(() => {
      vi.advanceTimersByTime(2 * TRINTA_MIN_MS)
    })

    expect(socket.fechadoPeloCliente).toBe(false)
    expect(SocketFalso.instancias).toHaveLength(1)
  })

  it('encerrar durante a espera de muitas_tentativas nao abre conexao antes do fim da espera (Review Focus 5)', () => {
    guardarSessao(SESSAO, AGORA - UM_DIA_MS)
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'mensagem', texto: 'Temos, sim.', kind: 'texto' })
    socket.receber({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'Muitas tentativas, aguarde 20 s.', aguardeSegundos: 20 })
    socket.fechar(1013)
    act(() => {
      vi.advanceTimersByTime(5_000)
    })

    abrirMenuEEscolherEncerrar()
    fireEvent.click(screen.getByRole('button', { name: 'Encerrar' }))

    expect(localStorage.getItem('mobia:sessao')).toBeNull()
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    expect(screen.getByText('Muitas tentativas, aguarde 20 s.')).toBeInTheDocument()
    expect(SocketFalso.instancias).toHaveLength(1)

    // A espera nao reinicia com o encerramento: acaba nos 20 s originais.
    act(() => {
      vi.advanceTimersByTime(14_999)
    })
    expect(SocketFalso.instancias).toHaveLength(1)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames()).toEqual([{ tipo: 'ola', sessao: null }])
  })

  it('localStorage que lanca: o chat abre com null e conversa normalmente', () => {
    for (const metodo of ['getItem', 'setItem', 'removeItem'] as const) {
      vi.spyOn(Storage.prototype, metodo).mockImplementation(() => {
        throw new DOMException('bloqueado', 'SecurityError')
      })
    }

    const socket = montarAberto()
    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: null }])

    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'mensagem', texto: 'Olá! Como posso ajudar?', kind: 'texto' })
    enviar('Quero alugar')
    expect(screen.getByText('Olá! Como posso ajudar?')).toBeInTheDocument()
    expect(frameDeMensagem(socket).texto).toBe('Quero alugar')

    abrirMenuEEscolherEncerrar()
    fireEvent.click(screen.getByRole('button', { name: 'Encerrar' }))
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    ultimoSocket().abrir()
    expect(ultimoSocket().frames()).toEqual([{ tipo: 'ola', sessao: null }])
  })

  it('desmontar minimizado cancela o sono e para de ouvir os avisos', () => {
    const { unmount } = render(<Conversa endereco={ENDERECO} nome={null} />)
    ultimoSocket().abrir()
    avisar({ tipo: 'mobia:visibilidade', aberto: false })
    expect(vi.getTimerCount()).toBe(1)

    unmount()
    expect(vi.getTimerCount()).toBe(0)

    avisar({ tipo: 'mobia:visibilidade', aberto: true })
    expect(SocketFalso.instancias).toHaveLength(1)
  })
})

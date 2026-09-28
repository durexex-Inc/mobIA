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

  it('tres frames imovel viram a prosa e uma fileira de tres cards (TEC-349, cenario 1)', () => {
    const socket = montarAberto()
    const imovel = (id: string, titulo: string) => ({
      id,
      titulo,
      bairro: 'Campeche',
      precoCentavos: 51_646_430,
      condominioCentavos: 85_000,
      quartos: 3,
      vagas: 2,
      areaUtilM2: 98,
      diferencial: 'piscina',
      foto: null,
      url: null,
    })

    socket.receber({ tipo: 'imovel', kind: 'ficha_1', texto: 'Separei três opções:', imovel: imovel('a', 'Casa A') })
    socket.receber({ tipo: 'imovel', kind: 'ficha_2', texto: null, imovel: imovel('b', 'Casa B') })
    socket.receber({ tipo: 'imovel', kind: 'ficha_3', texto: null, imovel: imovel('c', 'Casa C') })

    expect(screen.getByText('Separei três opções:')).toHaveClass('conversa__balao--agente')
    const fileira = screen.getByRole('list', { name: 'Imóveis sugeridos' })
    const cards = within(fileira).getAllByRole('article')
    expect(cards.map((card) => within(card).getByRole('heading').textContent)).toEqual(['Casa A', 'Casa B', 'Casa C'])
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

    // O 1002 -- o unico fechamento que nao reconecta sozinho (TEC-348, D2) --
    // marca a mensagem como falhou antes dos 10 s.
    act(() => {
      vi.advanceTimersByTime(3_000)
    })
    socket.fechar(1002)
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

  it('fechamento 1002 com mensagem pendente marca "Não enviada"; "Reenviar" abre socket novo, manda ola com a sessao e depois a mensagem', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    enviar('Qual o valor do condomínio?')
    const { id } = frameDeMensagem(socket)

    socket.fechar(1002)

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

  it('reenviar duas mensagens depois de um 1002 abre um socket so', () => {
    const socket = montarAberto()
    enviar('Primeira')
    enviar('Segunda')
    socket.fechar(1002)

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
    antigo.fechar(1002)
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

  it('TEC-366: o servidor fechar por ociosidade e sono, e reabrir retoma a sessao', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'mensagem', texto: 'Olá! Como posso ajudar?', kind: 'texto' })
    avisar({ tipo: 'mobia:visibilidade', aberto: false })

    // O servidor chegou primeiro: 4000, e nao o sono do proprio cliente.
    socket.fechar(4000)

    expect(screen.queryByText('Não enviada')).toBeNull()
    expect(SocketFalso.instancias).toHaveLength(1)

    avisar({ tipo: 'mobia:visibilidade', aberto: true })

    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames()).toEqual([{ tipo: 'ola', sessao: SESSAO }])
  })

  it('TEC-366: uma queda comum nao vira sono, e reabrir o painel nao reconecta sozinho', () => {
    // O contraste que prova que o codigo 4000 e o que decide: depois de uma
    // queda quem reconecta e o timer da TEC-348, e nao o painel reaberto.
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    avisar({ tipo: 'mobia:visibilidade', aberto: false })

    socket.fechar(1006)
    avisar({ tipo: 'mobia:visibilidade', aberto: true })

    expect(SocketFalso.instancias).toHaveLength(1)
  })

  it('TEC-366: depois do fechamento por ociosidade com o painel aberto, a proxima mensagem reconecta', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })

    socket.fechar(4000)
    enviar('voltei')

    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames()[0]).toEqual({ tipo: 'ola', sessao: SESSAO })
    expect(novo.frames()[1]).toMatchObject({ tipo: 'mensagem', texto: 'voltei' })
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

  it('aviso de outra janela, ou com aberto que nao e booleano, nao cancela o sono (Review Focus 4)', () => {
    const socket = montarAberto()
    avisar({ tipo: 'mobia:visibilidade', aberto: false })

    // Cada um destes, se aceito, leria "aberto" e cancelaria o sono.
    avisar({ tipo: 'mobia:visibilidade', aberto: 'false' })
    avisar({ tipo: 'mobia:visibilidade', aberto: 'true' })
    avisar({ tipo: 'mobia:visibilidade', aberto: 1 })
    avisar({ tipo: 'mobia:visibilidade', aberto: true }, {})

    act(() => {
      vi.advanceTimersByTime(TRINTA_MIN_MS - 1)
    })
    expect(socket.fechadoPeloCliente).toBe(false)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(socket.fechadoPeloCliente).toBe(true)
  })

  it('aviso de outra janela, ou de outro tipo, nao faz o chat dormir (Review Focus 4)', () => {
    const socket = montarAberto()

    avisar({ tipo: 'mobia:visibilidade', aberto: false }, {})
    avisar({ tipo: 'outra:coisa', aberto: false })
    avisar('mobia:visibilidade')
    avisar(null)
    act(() => {
      vi.advanceTimersByTime(2 * TRINTA_MIN_MS)
    })

    expect(socket.fechadoPeloCliente).toBe(false)
    expect(SocketFalso.instancias).toHaveLength(1)
  })

  it('o cabecalho mostra o nome do assistente', () => {
    render(<Conversa endereco={ENDERECO} nome="Lia" />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Lia · Assistente virtual$/)
  })

  it('o menu fecha quando o foco sai dele, e nao quando passa do item ao botao', () => {
    montarAberto()
    const botao = screen.getByRole('button', { name: 'Opções da conversa' })
    fireEvent.click(botao)
    const item = screen.getByRole('menuitem', { name: 'Encerrar conversa' })

    fireEvent.blur(item, { relatedTarget: botao })
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.blur(item, { relatedTarget: screen.getByRole('textbox', { name: 'Mensagem' }) })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(botao).toHaveAttribute('aria-expanded', 'false')
  })

  it('"Cancelar" e Escape fecham a confirmacao e devolvem o foco ao botao do menu', () => {
    montarAberto()
    const botao = screen.getByRole('button', { name: 'Opções da conversa' })

    abrirMenuEEscolherEncerrar()
    expect(screen.getByRole('button', { name: 'Cancelar' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(botao).toHaveFocus()

    abrirMenuEEscolherEncerrar()
    fireEvent.keyDown(screen.getByRole('button', { name: 'Cancelar' }), { key: 'Escape' })
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(botao).toHaveFocus()
    expect(SocketFalso.instancias).toHaveLength(1)
  })

  it('"Encerrar" devolve o foco ao campo da mensagem', () => {
    montarAberto()

    abrirMenuEEscolherEncerrar()
    fireEvent.click(screen.getByRole('button', { name: 'Encerrar' }))

    expect(screen.getByRole('textbox', { name: 'Mensagem' })).toHaveFocus()
  })

  it('o historico nao puxa para o fim quem rolou para cima, mesmo com a pendente dela no fim', () => {
    const socket = montarAberto()
    const lista = comGeometria(screen.getByRole('list'), { alturaTotal: 1000, alturaVisivel: 300 })
    enviar('Pendente')
    expect(lista.scrollTop).toBe(1000)
    rolarPara(lista, 100)

    socket.receber({ tipo: 'historico', mensagens: doze() })

    expect(screen.getAllByRole('listitem')).toHaveLength(13)
    expect(lista.scrollTop).toBe(100)
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

  it('encerrar durante a espera de muitas_tentativas devolve o foco ao botao de opcoes', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'Muitas tentativas, aguarde 20 s.', aguardeSegundos: 20 })
    socket.fechar(1013)

    abrirMenuEEscolherEncerrar()
    fireEvent.click(screen.getByRole('button', { name: 'Encerrar' }))

    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Opções da conversa' }))
  })

  it('a reconexao nao remonta os baloes que ja estavam na tela: o log nao os anuncia de novo', () => {
    guardarSessao(SESSAO, AGORA - UM_DIA_MS)
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'historico', mensagens: doze() })
    enviar('Tem garagem?')
    socket.receber({ tipo: 'ack', messageId: frameDeMensagem(socket).id })
    socket.receber({ tipo: 'mensagem', texto: 'Tem, sim.', kind: 'texto' })
    const antes = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(antes).toHaveLength(14)

    // Queda; a mensagem escrita nela espera a reconexao automatica (TEC-348),
    // e o socket novo retoma e recebe o historico -- o mesmo que a tela ja
    // tinha, mais uma fala nova.
    socket.fechar()
    enviar('E piscina?')
    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    const novo = ultimoSocket()
    expect(novo).not.toBe(socket)
    novo.abrir()
    novo.receber({ tipo: 'sessao', sessao: SESSAO })
    novo.receber({
      tipo: 'historico',
      mensagens: [
        ...doze(),
        { papel: 'lead', texto: 'Tem garagem?', em: '2026-09-27T11:59:00Z' },
        { papel: 'agente', texto: 'Tem, sim.', em: '2026-09-27T11:59:05Z' },
        { papel: 'agente', texto: 'Mais alguma dúvida?', em: '2026-09-27T11:59:30Z' },
      ],
    })

    const depois = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(depois).toHaveLength(16)
    antes.forEach((li, i) => expect(depois[i]).toBe(li))
    expect(depois[14]).toHaveTextContent('Mais alguma dúvida?')
    expect(depois[15]).toHaveTextContent('E piscina?')
  })

  it('retomar nao regrava a sessao mesmo que outra aba a tenha apagado (D1)', () => {
    guardarSessao(SESSAO, AGORA - UM_DIA_MS)
    const socket = montarAberto()
    expect(socket.frames()).toEqual([{ tipo: 'ola', sessao: SESSAO }])

    // Outra aba encerrou a conversa entre o `ola` e o frame `sessao`.
    localStorage.clear()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })

    expect(localStorage.getItem('mobia:sessao')).toBeNull()
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

const AVISO_DE_INSTAVEL = 'Nosso atendimento está instável. Deixe sua mensagem que responderemos.'

describe('Conversa -- reconexao automatica e fila local (TEC-348)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(AGORA)
  })

  function avancar(ms: number) {
    act(() => {
      vi.advanceTimersByTime(ms)
    })
  }

  function mensagensDe(socket: SocketFalso) {
    return socket.frames().filter((f) => f.tipo === 'mensagem')
  }

  it('cenario 1: a mensagem enviada durante a queda sai uma vez, depois do ola, e vai a "Recebida"', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })

    socket.fechar()
    expect(screen.getByText('Reconectando…')).toBeInTheDocument()
    // O campo continua de pe durante a queda.
    enviar('Tem vaga de garagem?')
    expect(screen.getByText('Enviando…')).toBeInTheDocument()
    // Enviar na queda nao fura a espera da tentativa.
    expect(SocketFalso.instancias).toHaveLength(1)

    avancar(1_000)
    expect(SocketFalso.instancias).toHaveLength(2)
    const novo = ultimoSocket()
    novo.abrir()

    const [mensagem] = mensagensDe(novo)
    expect(novo.frames()).toEqual([
      { tipo: 'ola', sessao: SESSAO },
      { tipo: 'mensagem', id: mensagem.id, texto: 'Tem vaga de garagem?' },
    ])
    expect(mensagem.id).toMatch(UUID_V4)
    expect(screen.queryByText('Reconectando…')).toBeNull()

    novo.receber({ tipo: 'ack', messageId: mensagem.id })
    expect(screen.getByText('Recebida')).toBeInTheDocument()
    expect(screen.getAllByText('Tem vaga de garagem?')).toHaveLength(1)
  })

  it('a mensagem que saiu pelo socket que caiu sem ack sai de novo, com o mesmo id, uma vez', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    enviar('Aceita pet?')
    const { id } = frameDeMensagem(socket)

    socket.fechar()
    expect(screen.getByText('Enviando…')).toBeInTheDocument()
    avancar(1_000)
    const novo = ultimoSocket()
    novo.abrir()

    expect(mensagensDe(novo)).toEqual([{ tipo: 'mensagem', id, texto: 'Aceita pet?' }])
  })

  it('o prazo do ack nao corre durante a queda, e volta a correr quando a mensagem sai', () => {
    const socket = montarAberto()
    socket.fechar()
    enviar('Tem piscina?')

    // Tres tentativas que nao abrem: 1 + 2 + 4 s, e mais uns segundos.
    avancar(1_000)
    ultimoSocket().fechar()
    avancar(2_000)
    ultimoSocket().fechar()
    avancar(4_000)
    ultimoSocket().fechar()
    avancar(5_000)
    expect(screen.getByText('Enviando…')).toBeInTheDocument()
    expect(screen.queryByText('Não enviada')).toBeNull()

    // A quarta tentativa abre; a mensagem sai e o prazo de 10 s comeca.
    avancar(3_000)
    ultimoSocket().abrir()
    avancar(9_999)
    expect(screen.getByText('Enviando…')).toBeInTheDocument()
    avancar(1)
    expect(screen.getByText('Não enviada')).toBeInTheDocument()
  })

  it('cenario 2: as esperas antes das tentativas sao 1, 2, 4, 8, 16, 30 e 30 s', () => {
    const socket = montarAberto()
    socket.fechar()

    for (const [tentativa, espera] of [
      [1, 1],
      [2, 2],
      [3, 4],
      [4, 8],
      [5, 16],
      [6, 30],
      [7, 30],
    ]) {
      avancar(espera * 1000 - 1)
      expect(SocketFalso.instancias, `antes da tentativa ${tentativa}`).toHaveLength(tentativa)
      avancar(1)
      expect(SocketFalso.instancias, `tentativa ${tentativa}`).toHaveLength(tentativa + 1)
      ultimoSocket().fechar()
    }
  })

  it('a tentativa que abre zera a contagem: a proxima queda volta a esperar 1 s', () => {
    const socket = montarAberto()
    socket.fechar()
    avancar(1_000)
    ultimoSocket().fechar()
    avancar(2_000)
    ultimoSocket().abrir()

    ultimoSocket().fechar()
    avancar(1_000)
    expect(SocketFalso.instancias).toHaveLength(4)
  })

  it('cenario 3: cinco minutos sem conexao param as tentativas e oferecem "Tentar de novo"', () => {
    const socket = montarAberto()
    socket.fechar()

    // Cada tentativa fecha sem abrir, ate um segundo antes dos cinco minutos.
    const cincoMinutos = 5 * 60 * 1000
    let passou = 0
    while (passou < cincoMinutos - 1_000) {
      const antes = SocketFalso.instancias.length
      avancar(1_000)
      passou += 1_000
      if (SocketFalso.instancias.length > antes) {
        ultimoSocket().fechar()
      }
    }
    expect(screen.queryByRole('button', { name: 'Tentar de novo' })).toBeNull()
    avancar(cincoMinutos - passou)

    expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeInTheDocument()
    // Desde a TEC-351 quem diz "Offline" e o cabecalho.
    expect(screen.getByRole('banner')).toHaveTextContent('Offline')
    expect(screen.queryByText('Reconectando…')).toBeNull()

    const tentativas = SocketFalso.instancias.length
    avancar(10 * 60 * 1000)
    expect(SocketFalso.instancias).toHaveLength(tentativas)

    fireEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
    expect(SocketFalso.instancias).toHaveLength(tentativas + 1)
    expect(screen.queryByRole('button', { name: 'Tentar de novo' })).toBeNull()
    ultimoSocket().abrir()
    expect(screen.getByRole('banner')).toHaveTextContent('Conectado')
  })

  it('"Tentar de novo" que falha recomeca a reconexao automatica em 1 s', () => {
    const socket = montarAberto()
    socket.fechar()
    avancar(5 * 60 * 1000)
    fireEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
    const tentativas = SocketFalso.instancias.length

    ultimoSocket().fechar()
    expect(screen.getByText('Reconectando…')).toBeInTheDocument()
    avancar(1_000)
    expect(SocketFalso.instancias).toHaveLength(tentativas + 1)
  })

  it('em offline, a mensagem mantida na fila sai no socket que "Tentar de novo" abre', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.fechar()
    enviar('Ainda estão aí?')
    avancar(5 * 60 * 1000)
    expect(screen.getByText('Enviando…')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
    const novo = ultimoSocket()
    novo.abrir()
    expect(mensagensDe(novo).map((f) => f.texto)).toEqual(['Ainda estão aí?'])
  })

  it('em offline, enviar uma mensagem reconecta na hora', () => {
    const socket = montarAberto()
    socket.fechar()
    avancar(5 * 60 * 1000)
    const tentativas = SocketFalso.instancias.length

    enviar('Oi?')

    expect(SocketFalso.instancias).toHaveLength(tentativas + 1)
    ultimoSocket().abrir()
    expect(mensagensDe(ultimoSocket()).map((f) => f.texto)).toEqual(['Oi?'])
  })

  it('cenario 4: fechamento 1011 diz que o atendimento esta instavel e mantem a mensagem na fila', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.fechar(1011)

    expect(screen.getByText(AVISO_DE_INSTAVEL)).toBeInTheDocument()
    expect(screen.getByText('Reconectando…')).toBeInTheDocument()

    enviar('Tem vaga de garagem?')
    expect(screen.getByText('Enviando…')).toBeInTheDocument()

    // A tentativa seguinte tambem nao abre: a frase continua, e a mensagem tambem.
    avancar(1_000)
    ultimoSocket().fechar()
    expect(screen.getByText(AVISO_DE_INSTAVEL)).toBeInTheDocument()
    expect(screen.getByText('Enviando…')).toBeInTheDocument()

    avancar(2_000)
    const novo = ultimoSocket()
    novo.abrir()
    expect(mensagensDe(novo).map((f) => f.texto)).toEqual(['Tem vaga de garagem?'])
    expect(screen.queryByText(AVISO_DE_INSTAVEL)).toBeNull()
  })

  it('fechamento 1002 nao reconecta sozinho', () => {
    const socket = montarAberto()
    socket.fechar(1002)
    avancar(60_000)
    expect(SocketFalso.instancias).toHaveLength(1)
    expect(screen.queryByText('Reconectando…')).toBeNull()
  })

  it('a mensagem que o servidor gravou antes da queda nao aparece duas vezes quando o historico a traz', () => {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    enviar('Tem vaga de garagem?')
    const { id } = frameDeMensagem(socket)

    // O servidor gravou; o `ack` se perdeu na queda.
    socket.fechar()
    avancar(1_000)
    const novo = ultimoSocket()
    novo.abrir()
    novo.receber({ tipo: 'sessao', sessao: SESSAO })
    novo.receber({ tipo: 'historico', mensagens: [{ papel: 'lead', texto: 'Tem vaga de garagem?' }] })
    novo.receber({ tipo: 'ack', messageId: id })

    expect(screen.getAllByText('Tem vaga de garagem?')).toHaveLength(1)
    expect(screen.getByText('Recebida')).toBeInTheDocument()
  })

  it('encerrar durante a queda abre a conversa nova na hora, sem esperar a tentativa', () => {
    const socket = montarAberto()
    socket.fechar()
    abrirMenuEEscolherEncerrar()
    fireEvent.click(screen.getByRole('button', { name: 'Encerrar' }))

    expect(SocketFalso.instancias).toHaveLength(2)
    expect(screen.queryByText('Reconectando…')).toBeNull()
    // A tentativa que estava marcada morreu com a queda.
    avancar(60_000)
    expect(SocketFalso.instancias).toHaveLength(2)
  })
})

describe('Conversa -- reacao rapida ao imovel (TEC-350)', () => {
  function imovel(id: string, titulo: string, bairro = 'Campeche') {
    return {
      id,
      titulo,
      bairro,
      precoCentavos: 51_646_430,
      condominioCentavos: null,
      quartos: 3,
      vagas: 2,
      areaUtilM2: 98,
      diferencial: null,
      foto: null,
      url: null,
    }
  }

  function comDoisCards(): SocketFalso {
    const socket = montarAberto()
    socket.receber({ tipo: 'sessao', sessao: SESSAO })
    socket.receber({ tipo: 'imovel', kind: 'ficha_1', texto: 'Separei duas opções:', imovel: imovel('a', 'Casa 3 quartos') })
    socket.receber({ tipo: 'imovel', kind: 'ficha_2', texto: null, imovel: imovel('b', 'Apartamento 2 quartos', 'Trindade') })
    return socket
  }

  function grupoDe(titulo: string) {
    return within(screen.getByRole('group', { name: `Reagir a ${titulo}` }))
  }

  it('cenario 1: "Gostei" manda a fala da visitante com o imovel, e ela aparece na conversa', () => {
    const socket = comDoisCards()

    fireEvent.click(grupoDe('Casa 3 quartos').getByRole('button', { name: 'Gostei' }))

    const texto = 'Gostei do imóvel "Casa 3 quartos" (Campeche).'
    const { id } = frameDeMensagem(socket)
    expect(socket.frames().at(-1)).toEqual({ tipo: 'mensagem', id, texto })
    expect(id).toMatch(UUID_V4)
    expect(screen.getByText(texto).closest('li')).toHaveClass('conversa__balao--visitante')
    expect(screen.getByText('Enviando…')).toBeInTheDocument()

    socket.receber({ tipo: 'ack', messageId: id })
    expect(screen.getByText('Recebida')).toBeInTheDocument()
  })

  it('cenario 2: "Não é pra mim" manda a fala descartando aquele imovel', () => {
    const socket = comDoisCards()

    fireEvent.click(grupoDe('Apartamento 2 quartos').getByRole('button', { name: 'Não é pra mim' }))

    const texto = 'O imóvel "Apartamento 2 quartos" (Trindade) não é pra mim.'
    expect(frameDeMensagem(socket).texto).toBe(texto)
    expect(screen.getByText(texto).closest('li')).toHaveClass('conversa__balao--visitante')
  })

  it('o card tocado fica com os dois botoes desabilitados e o outro card continua livre', () => {
    const socket = comDoisCards()

    fireEvent.click(grupoDe('Casa 3 quartos').getByRole('button', { name: 'Gostei' }))

    expect(grupoDe('Casa 3 quartos').getByRole('button', { name: 'Gostei' })).toHaveAttribute('aria-pressed', 'true')
    expect(grupoDe('Casa 3 quartos').getByRole('button', { name: 'Não é pra mim' })).toBeDisabled()
    expect(grupoDe('Apartamento 2 quartos').getByRole('button', { name: 'Gostei' })).toBeEnabled()
    // Um toque, uma mensagem.
    expect(socket.frames().filter((f) => f.tipo === 'mensagem')).toHaveLength(1)
  })

  it('com a conexao caida o toque fica na fila e sai na reconexao (TEC-348)', () => {
    vi.useFakeTimers()
    const socket = comDoisCards()
    socket.fechar()

    fireEvent.click(grupoDe('Casa 3 quartos').getByRole('button', { name: 'Gostei' }))
    expect(screen.getByText('Enviando…')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    const novo = ultimoSocket()
    novo.abrir()
    expect(novo.frames().filter((f) => f.tipo === 'mensagem').map((f) => f.texto)).toEqual([
      'Gostei do imóvel "Casa 3 quartos" (Campeche).',
    ])
  })

  it('durante a espera de muitas_tentativas os botoes ficam desabilitados', () => {
    const socket = comDoisCards()
    socket.receber({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'Muitas tentativas, aguarde 20 s.', aguardeSegundos: 20 })
    socket.fechar(1013)

    expect(grupoDe('Casa 3 quartos').getByRole('button', { name: 'Gostei' })).toBeDisabled()
    expect(grupoDe('Casa 3 quartos').getByRole('button', { name: 'Gostei' })).toHaveAttribute('aria-pressed', 'false')
  })
})

describe('Conversa -- digitando e estado da conexao (TEC-351)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(AGORA)
  })

  function avancar(ms: number) {
    act(() => {
      vi.advanceTimersByTime(ms)
    })
  }

  function daquiA(ms: number): string {
    return new Date(Date.now() + ms).toISOString()
  }

  function montarAbertoCom(nome: string | null): SocketFalso {
    render(<Conversa endereco={ENDERECO} nome={nome} />)
    const socket = ultimoSocket()
    socket.abrir()
    return socket
  }

  function cabecalho() {
    return screen.getByRole('banner')
  }

  it('o frame digitando mostra "{nome} está digitando…", e a resposta o apaga', () => {
    const socket = montarAbertoCom('Lia')
    enviar('Tem garagem?')

    socket.receber({ tipo: 'digitando', ate: daquiA(25_000) })
    expect(screen.getByText('Lia está digitando…')).toBeInTheDocument()
    // Fora do log: o indicador nao e mensagem da conversa.
    expect(within(screen.getByRole('log')).queryByText('Lia está digitando…')).toBeNull()

    socket.receber({ tipo: 'mensagem', texto: 'Tem, sim.', kind: 'reply' })
    expect(screen.queryByText('Lia está digitando…')).toBeNull()
  })

  it('sem nome configurado, "O assistente está digitando…"', () => {
    const socket = montarAbertoCom(null)
    socket.receber({ tipo: 'digitando', ate: daquiA(25_000) })
    expect(screen.getByText('O assistente está digitando…')).toBeInTheDocument()
  })

  it('o card de imovel tambem apaga o indicador', () => {
    const socket = montarAbertoCom('Lia')
    socket.receber({ tipo: 'digitando', ate: daquiA(25_000) })
    socket.receber({ tipo: 'imovel', kind: 'ficha_1', texto: 'Separei esta:', imovel: null })
    expect(screen.queryByText('Lia está digitando…')).toBeNull()
  })

  it('o indicador obedece o ate do servidor: 25 s', () => {
    const socket = montarAbertoCom('Lia')
    socket.receber({ tipo: 'digitando', ate: daquiA(25_000) })

    avancar(24_999)
    expect(screen.getByText('Lia está digitando…')).toBeInTheDocument()
    avancar(1)
    expect(screen.queryByText('Lia está digitando…')).toBeNull()
  })

  it('cenario 2: sem nova fala do agente, o indicador some em no maximo 30 s, mesmo com ate mais longe', () => {
    const socket = montarAbertoCom('Lia')
    socket.receber({ tipo: 'digitando', ate: daquiA(60_000) })

    avancar(29_999)
    expect(screen.getByText('Lia está digitando…')).toBeInTheDocument()
    avancar(1)
    expect(screen.queryByText('Lia está digitando…')).toBeNull()
  })

  it('ate ja passado ou ilegivel (relogio do aparelho diferente) vale 30 s, e nao esconde o indicador', () => {
    const socket = montarAbertoCom('Lia')
    socket.receber({ tipo: 'digitando', ate: daquiA(-5_000) })
    expect(screen.getByText('Lia está digitando…')).toBeInTheDocument()
    avancar(30_000)
    expect(screen.queryByText('Lia está digitando…')).toBeNull()

    socket.receber({ tipo: 'digitando', ate: 'logo' })
    avancar(29_999)
    expect(screen.getByText('Lia está digitando…')).toBeInTheDocument()
    avancar(1)
    expect(screen.queryByText('Lia está digitando…')).toBeNull()
  })

  it('um digitando novo renova o prazo', () => {
    const socket = montarAbertoCom('Lia')
    socket.receber({ tipo: 'digitando', ate: daquiA(25_000) })
    avancar(20_000)
    socket.receber({ tipo: 'digitando', ate: daquiA(25_000) })

    avancar(10_000)
    expect(screen.getByText('Lia está digitando…')).toBeInTheDocument()
    avancar(15_000)
    expect(screen.queryByText('Lia está digitando…')).toBeNull()
  })

  it('o socket que cai apaga o indicador', () => {
    const socket = montarAbertoCom('Lia')
    socket.receber({ tipo: 'digitando', ate: daquiA(25_000) })
    socket.fechar()
    expect(screen.queryByText('Lia está digitando…')).toBeNull()
  })

  it('cenario 3: o cabecalho mostra Conectado, Reconectando… e Offline', () => {
    render(<Conversa endereco={ENDERECO} nome="Lia" />)
    expect(cabecalho()).toHaveTextContent('Conectando…')

    const socket = ultimoSocket()
    socket.abrir()
    expect(cabecalho()).toHaveTextContent('Conectado')

    socket.fechar()
    expect(cabecalho()).toHaveTextContent('Reconectando…')
    // O cabecalho diz; a linha acima do campo nao repete.
    expect(screen.getAllByText('Reconectando…')).toHaveLength(1)

    avancar(5 * 60 * 1000)
    expect(cabecalho()).toHaveTextContent('Offline')
    expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeInTheDocument()
  })

  it('a espera de muitas_tentativas e Offline no cabecalho', () => {
    const socket = montarAbertoCom('Lia')
    socket.receber({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'Muitas tentativas, aguarde 20 s.', aguardeSegundos: 20 })
    socket.fechar(1013)
    expect(cabecalho()).toHaveTextContent('Offline')
  })
})

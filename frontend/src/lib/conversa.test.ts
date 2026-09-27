import { afterEach, describe, expect, it, vi } from 'vitest'

import { INICIAL, novoMessageId, reduzir, type Conversa, type Mensagem } from './conversa'

const REGEX_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function frame(bruto: object): string {
  return JSON.stringify(bruto)
}

// Estado com uma mensagem da visitante ja em 'enviando', para os testes que
// precisam de uma mensagem pendente antes do evento sob teste.
function comVisitanteEnviando(messageId: string, texto = 'oi'): Conversa {
  return reduzir(INICIAL, { tipo: 'enviou', messageId, texto })
}

describe('reduzir', () => {
  it('abriu leva a conexao para aberta', () => {
    const depois = reduzir(INICIAL, { tipo: 'abriu' })
    expect(depois.conexao).toEqual({ tipo: 'aberta' })
  })

  it('enviou acrescenta mensagem da visitante em enviando', () => {
    const depois = reduzir(INICIAL, { tipo: 'enviou', messageId: 'm1', texto: 'ola' })
    expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'ola', estado: 'enviando' }])
  })

  it('frame com json invalido mantem o estado, mesma referencia', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'frame', bruto: '{nao e json' })
    expect(depois).toBe(antes)
  })

  it('frame com tipo desconhecido mantem o estado, mesma referencia', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'algo_que_nao_existe' }) })
    expect(depois).toBe(antes)
  })

  it('sessao grava o uuid do frame', () => {
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'sessao', sessao: '11111111-1111-4111-8111-111111111111' }),
    })
    expect(depois.sessao).toBe('11111111-1111-4111-8111-111111111111')
  })

  it('mensagem do agente acrescenta um balao com chave unica', () => {
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'mensagem', texto: 'Oi, tudo bem?', kind: 'reply' }),
    })
    expect(depois.mensagens).toEqual([{ autor: 'agente', chave: 'agente-0', texto: 'Oi, tudo bem?' }])
  })

  it('tres frames de mensagem viram tres baloes na ordem de chegada, com chaves distintas', () => {
    let estado = INICIAL
    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'primeira', kind: 'reply' }) })
    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'segunda', kind: 'reply' }) })
    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'terceira', kind: 'reply' }) })

    expect(estado.mensagens).toEqual([
      { autor: 'agente', chave: 'agente-0', texto: 'primeira' },
      { autor: 'agente', chave: 'agente-1', texto: 'segunda' },
      { autor: 'agente', chave: 'agente-2', texto: 'terceira' },
    ])
    const chaves = new Set((estado.mensagens as Extract<Mensagem, { autor: 'agente' }>[]).map((m) => m.chave))
    expect(chaves.size).toBe(3)
  })

  it('imovel com texto vira balao do agente com esse texto', () => {
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'imovel', imovel: { id: 'i1' }, texto: 'Apto 2 quartos', kind: 'reply' }),
    })
    expect(depois.mensagens).toEqual([{ autor: 'agente', chave: 'agente-0', texto: 'Apto 2 quartos' }])
  })

  it('imovel sem texto mantem o estado, mesma referencia', () => {
    const antes = INICIAL
    const depois = reduzir(antes, {
      tipo: 'frame',
      bruto: frame({ tipo: 'imovel', imovel: { id: 'i1' }, texto: null, kind: 'reply' }),
    })
    expect(depois).toBe(antes)
  })

  it('ack de mensagem enviando marca recebida', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })
    expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'recebida' }])
  })

  it('ack de mensagem falhou (chegou depois do prazo) marca recebida', () => {
    // Review Focus 2: o ack pode chegar depois de o prazo do ack ja ter
    // marcado a mensagem como falhou -- o servidor aceitou mesmo assim.
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, { tipo: 'prazoDoAck', messageId: 'm1' })
    expect(estado.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'falhou' }])

    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })
    expect(estado.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'recebida' }])
  })

  it('ack de mensagem ja recebida mantem o estado, mesma referencia', () => {
    // Review Focus 1: duas abas ou o mesmo messageId reenviado podem produzir
    // um segundo ack para a mesma mensagem.
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })
    const antes = estado
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })
    expect(depois).toBe(antes)
  })

  it('ack de id desconhecido mantem o estado, mesma referencia', () => {
    // Review Focus 1: ack de um id que esta tela nunca viu e ignorado.
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'outro-id' }) })
    expect(depois).toBe(antes)
  })

  it('erro com messageId de mensagem enviando marca falhou', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, {
      tipo: 'frame',
      bruto: frame({ tipo: 'erro', codigo: 'texto_vazio', mensagem: 'Mensagem vazia', messageId: 'm1' }),
    })
    expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'falhou' }])
  })

  it('erro com codigo muitas_tentativas guarda a mensagem e a espera', () => {
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({
        tipo: 'erro',
        codigo: 'muitas_tentativas',
        mensagem: 'Muitas tentativas, aguarde 20 s.',
        aguardeSegundos: 20,
      }),
    })
    expect(depois.conexao).toEqual({ tipo: 'aguardando', mensagem: 'Muitas tentativas, aguarde 20 s.', segundos: 20 })
  })

  it('erro com codigo muitas_tentativas e segundos invalido usa 60', () => {
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({
        tipo: 'erro',
        codigo: 'muitas_tentativas',
        mensagem: 'Muitas tentativas, aguarde N s.',
        aguardeSegundos: 0,
      }),
    })
    expect(depois.conexao).toEqual({ tipo: 'aguardando', mensagem: 'Muitas tentativas, aguarde N s.', segundos: 60 })
  })

  it('digitando mantem o estado, mesma referencia', () => {
    const antes = INICIAL
    const depois = reduzir(antes, {
      tipo: 'frame',
      bruto: frame({ tipo: 'digitando', ate: '2026-09-27T12:00:00Z' }),
    })
    expect(depois).toBe(antes)
  })

  it('imagem mantem o estado, mesma referencia', () => {
    const antes = INICIAL
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'imagem', url: 'https://x/y.png' }) })
    expect(depois).toBe(antes)
  })

  it('historico mantem o estado, mesma referencia', () => {
    const antes = INICIAL
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'historico', mensagens: [] }) })
    expect(depois).toBe(antes)
  })

  it('consentimento_registrado mantem o estado, mesma referencia', () => {
    const antes = INICIAL
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'consentimento_registrado' }) })
    expect(depois).toBe(antes)
  })

  it('fechou marca toda mensagem enviando como falhou e fecha a conexao', () => {
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, { tipo: 'enviou', messageId: 'm2', texto: 'outra' })
    estado = reduzir(estado, { tipo: 'abriu' })

    const depois = reduzir(estado, { tipo: 'fechou' })

    expect(depois.conexao).toEqual({ tipo: 'fechada' })
    expect(depois.mensagens).toEqual([
      { autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'falhou' },
      { autor: 'visitante', messageId: 'm2', texto: 'outra', estado: 'falhou' },
    ])
  })

  it('fechou com a conexao ja aguardando continua aguardando', () => {
    const aguardando = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'espera', aguardeSegundos: 5 }),
    })
    const depois = reduzir(aguardando, { tipo: 'fechou' })
    expect(depois.conexao).toEqual({ tipo: 'aguardando', mensagem: 'espera', segundos: 5 })
  })

  it('prazoDoAck de mensagem enviando marca falhou', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'prazoDoAck', messageId: 'm1' })
    expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'falhou' }])
  })

  it('prazoDoAck de mensagem que ja foi recebida mantem o estado, mesma referencia', () => {
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })
    const antes = estado
    const depois = reduzir(antes, { tipo: 'prazoDoAck', messageId: 'm1' })
    expect(depois).toBe(antes)
  })

  it('reenviou de mensagem falhou volta para enviando, sem mudar a posicao', () => {
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, { tipo: 'enviou', messageId: 'm2', texto: 'segunda' })
    estado = reduzir(estado, { tipo: 'prazoDoAck', messageId: 'm2' })
    expect((estado.mensagens[1] as Extract<Mensagem, { autor: 'visitante' }>).estado).toBe('falhou')

    const depois = reduzir(estado, { tipo: 'reenviou', messageId: 'm2' })

    expect(depois.mensagens).toEqual([
      { autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'enviando' },
      { autor: 'visitante', messageId: 'm2', texto: 'segunda', estado: 'enviando' },
    ])
  })
})

describe('novoMessageId', () => {
  it('gera um uuid v4 por crypto.randomUUID', () => {
    expect(novoMessageId()).toMatch(REGEX_V4)
  })

  it('gera um uuid v4 pelo gerador de reserva quando randomUUID nao existe', () => {
    const original = globalThis.crypto
    vi.stubGlobal('crypto', { getRandomValues: original.getRandomValues.bind(original) })

    expect(novoMessageId()).toMatch(REGEX_V4)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })
})

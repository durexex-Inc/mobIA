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

  it('mensagem sem texto string mantem o estado, mesma referencia', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 42, kind: 'reply' }) })
    expect(depois).toBe(antes)
  })

  it('ack sem messageId mantem o estado, mesma referencia', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'ack' }) })
    expect(depois).toBe(antes)
  })

  it('erro com codigo muitas_tentativas e segundos nao numerico usa 60', () => {
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({
        tipo: 'erro',
        codigo: 'muitas_tentativas',
        mensagem: 'Muitas tentativas, aguarde N s.',
        aguardeSegundos: '20',
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

  it('historico com mensagens que nao e lista mantem o estado, mesma referencia', () => {
    // Review Focus 3: frame de historico inteiro invalido nao muda nada.
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, {
      tipo: 'frame',
      bruto: frame({ tipo: 'historico', mensagens: 'nao e uma lista' }),
    })
    expect(depois).toBe(antes)
  })

  it('historico monta lead como visitante recebida e agente como balao, na ordem', () => {
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({
        tipo: 'historico',
        mensagens: [
          { papel: 'lead', texto: 'Oi, quero um apartamento', em: '2026-09-01T10:00:00Z' },
          { papel: 'agente', texto: 'Claro, me conta mais', em: '2026-09-01T10:00:05Z' },
        ],
      }),
    })
    expect(depois.mensagens).toEqual([
      { autor: 'visitante', messageId: 'historico-0', texto: 'Oi, quero um apartamento', estado: 'recebida' },
      { autor: 'agente', chave: 'agente-1', texto: 'Claro, me conta mais' },
    ])
  })

  it('historico pula item invalido (papel desconhecido, sem texto, texto vazio) e mantem os validos', () => {
    // Review Focus 3: itens invalidos sao pulados, o resto do frame vale.
    const depois = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({
        tipo: 'historico',
        mensagens: [
          { papel: 'lead', texto: 'primeira' },
          { papel: 'corretor', texto: 'papel desconhecido' },
          { papel: 'agente' },
          { papel: 'lead', texto: '' },
          { papel: 'agente', texto: 'ultima valida' },
        ],
      }),
    })
    expect(depois.mensagens).toEqual([
      { autor: 'visitante', messageId: 'historico-0', texto: 'primeira', estado: 'recebida' },
      { autor: 'agente', chave: 'agente-1', texto: 'ultima valida' },
    ])
  })

  it('historico substitui as confirmadas e preserva a pendente da visitante no fim, uma vez so', () => {
    // Review Focus 2: mensagem local em 'enviando' sobrevive ao historico, no
    // fim, sem duplicar -- e o balao do agente em memoria sai (o historico o
    // contem).
    let estado = reduzir(INICIAL, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'ola', kind: 'reply' }) })
    estado = reduzir(estado, { tipo: 'enviou', messageId: 'm1', texto: 'ainda enviando' })

    const depois = reduzir(estado, {
      tipo: 'frame',
      bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'agente', texto: 'do historico' }] }),
    })

    expect(depois.mensagens).toEqual([
      { autor: 'agente', chave: 'agente-0', texto: 'do historico' },
      { autor: 'visitante', messageId: 'm1', texto: 'ainda enviando', estado: 'enviando' },
    ])
  })

  it('ack da pendente depois do historico marca recebida sem duplicar', () => {
    // Continuacao do Review Focus 2: o ack da mensagem que sobreviveu ao
    // historico so muda o estado dela, nao acrescenta outra.
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, {
      tipo: 'frame',
      bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'agente', texto: 'do historico' }] }),
    })

    const depois = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })

    expect(depois.mensagens).toEqual([
      { autor: 'agente', chave: 'agente-0', texto: 'do historico' },
      { autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'recebida' },
    ])
  })

  it('a chave do agente continua unica depois de um historico seguido de nova fala', () => {
    let estado = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({
        tipo: 'historico',
        mensagens: [
          { papel: 'agente', texto: 'primeira do historico' },
          { papel: 'agente', texto: 'segunda do historico' },
        ],
      }),
    })
    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'nova fala', kind: 'reply' }) })

    const chaves = (estado.mensagens as Extract<Mensagem, { autor: 'agente' }>[]).map((m) => m.chave)
    expect(chaves).toEqual(['agente-0', 'agente-1', 'agente-2'])
    expect(new Set(chaves).size).toBe(3)
  })

  it('ack de messageId historico-* mantem o estado, mesma referencia', () => {
    // A mensagem do historico ja chega 'recebida' -- na pratica o servidor
    // nao manda ack para ela, mas se mandasse nao haveria o que mudar.
    const antes = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'lead', texto: 'oi' }] }),
    })
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'historico-0' }) })
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

  it('reabrindo encerra a espera: conectando, e uma queda depois vira fechada', () => {
    const aguardando = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'espera', aguardeSegundos: 5 }),
    })
    const reabrindo = reduzir(aguardando, { tipo: 'reabrindo' })
    expect(reabrindo.conexao).toEqual({ tipo: 'conectando' })

    const depois = reduzir(reabrindo, { tipo: 'fechou' })
    expect(depois.conexao).toEqual({ tipo: 'fechada' })
  })

  it('reabrindo com a conexao ja conectando devolve a mesma referencia', () => {
    expect(reduzir(INICIAL, { tipo: 'reabrindo' })).toBe(INICIAL)
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

  it('encerrou volta ao inicial e abre com conectando', () => {
    let estado = reduzir(INICIAL, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'oi', kind: 'reply' }) })
    estado = reduzir(estado, { tipo: 'abriu' })
    estado = reduzir(estado, {
      tipo: 'frame',
      bruto: frame({ tipo: 'sessao', sessao: '11111111-1111-4111-8111-111111111111' }),
    })

    const depois = reduzir(estado, { tipo: 'encerrou' })

    expect(depois).toEqual({ mensagens: [], conexao: { tipo: 'conectando' }, sessao: null })
  })

  it('encerrou durante a espera de muitas_tentativas mantem a espera (Review Focus 5)', () => {
    // A tela zera, mas a nova conexao nao pode furar a fila: a espera
    // continua valendo ate o proprio timer da vencer.
    const aguardando = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'espera', aguardeSegundos: 5 }),
    })

    const depois = reduzir(aguardando, { tipo: 'encerrou' })

    expect(depois).toEqual({
      mensagens: [],
      conexao: { tipo: 'aguardando', mensagem: 'espera', segundos: 5 },
      sessao: null,
    })
  })

  it('adormeceu muda a conexao para adormecida sem tocar nas mensagens', () => {
    const antes = comVisitanteEnviando('m1')
    const depois = reduzir(antes, { tipo: 'adormeceu' })
    expect(depois.conexao).toEqual({ tipo: 'adormecida' })
    expect(depois.mensagens).toBe(antes.mensagens)
  })

  it('adormeceu com a conexao ja adormecida devolve a mesma referencia', () => {
    const adormecida = reduzir(INICIAL, { tipo: 'adormeceu' })
    expect(reduzir(adormecida, { tipo: 'adormeceu' })).toBe(adormecida)
  })

  it('fechou com a conexao adormecida continua adormecida e marca enviando como falhou', () => {
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, { tipo: 'adormeceu' })

    const depois = reduzir(estado, { tipo: 'fechou' })

    expect(depois.conexao).toEqual({ tipo: 'adormecida' })
    expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'falhou' }])
  })

  it('fechou com a conexao adormecida e nada pendente mantem a mesma referencia', () => {
    const antes = reduzir(INICIAL, { tipo: 'adormeceu' })
    const depois = reduzir(antes, { tipo: 'fechou' })
    expect(depois).toBe(antes)
  })

  it('abriu a partir de adormecida vai para aberta', () => {
    const adormecida = reduzir(INICIAL, { tipo: 'adormeceu' })
    const depois = reduzir(adormecida, { tipo: 'abriu' })
    expect(depois.conexao).toEqual({ tipo: 'aberta' })
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

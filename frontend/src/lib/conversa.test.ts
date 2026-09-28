import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  esperaDaTentativa,
  INICIAL,
  MAXIMO_DE_CARDS,
  novoMessageId,
  reduzir,
  type Conversa,
  type Mensagem,
} from './conversa'

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

  it('imovel incompleto sem texto mantem o estado, mesma referencia', () => {
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

  describe('digitando (TEC-351, D2)', () => {
    function digitando(ate: unknown = '2026-09-27T12:00:25Z'): Conversa {
      return reduzir(INICIAL, { tipo: 'frame', bruto: frame({ tipo: 'digitando', ate }) })
    }

    it('liga o indicador com o instante do frame', () => {
      expect(digitando().digitando).toEqual({ ate: Date.UTC(2026, 8, 27, 12, 0, 25) })
    })

    it('ate ilegivel ou ausente liga o indicador sem instante', () => {
      expect(digitando('amanha').digitando).toEqual({ ate: null })
      expect(digitando(42).digitando).toEqual({ ate: null })
    })

    it('cada frame e um indicador novo, que renova o prazo', () => {
      const primeiro = digitando()
      const segundo = reduzir(primeiro, { tipo: 'frame', bruto: frame({ tipo: 'digitando', ate: '2026-09-27T12:00:30Z' }) })
      expect(segundo.digitando).not.toBe(primeiro.digitando)
    })

    it.each([
      ['mensagem', { tipo: 'mensagem', texto: 'Tem sim.', kind: 'reply' }],
      ['imovel', { tipo: 'imovel', kind: 'ficha_1', texto: 'Separei:', imovel: null }],
      ['imagem', { tipo: 'imagem', url: 'https://x/y.png' }],
    ])('a fala do agente (%s) apaga o indicador', (_nome, dado) => {
      expect(reduzir(digitando(), { tipo: 'frame', bruto: frame(dado) }).digitando).toBeNull()
    })

    it('o socket que fecha apaga o indicador', () => {
      const estado = reduzir(digitando(), { tipo: 'abriu' })
      expect(reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 0 }).digitando).toBeNull()
    })

    it('encerrar apaga o indicador', () => {
      expect(reduzir(digitando(), { tipo: 'encerrou' }).digitando).toBeNull()
    })

    it('o prazo vencido apaga so o indicador daquele frame', () => {
      const primeiro = digitando()
      const segundo = reduzir(primeiro, { tipo: 'frame', bruto: frame({ tipo: 'digitando', ate: '2026-09-27T12:00:30Z' }) })

      // O prazo do primeiro vence depois de o segundo chegar: nada muda.
      expect(reduzir(segundo, { tipo: 'digitacaoVenceu', indicador: primeiro.digitando! })).toBe(segundo)
      expect(reduzir(segundo, { tipo: 'digitacaoVenceu', indicador: segundo.digitando! }).digitando).toBeNull()
    })

    it('a fala do agente sem indicador ligado nao muda a referencia por causa dele', () => {
      const antes = INICIAL
      expect(reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'imagem', url: 'https://x/y.png' }) })).toBe(antes)
    })
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
    // fim, sem duplicar -- e o balao do agente em memoria que o historico nao
    // contem sai. A fala nova nao herda a chave `agente-0` de quem saiu: com
    // ela, o React reaproveitaria o `<li>` e o `log` nao a anunciaria.
    let estado = reduzir(INICIAL, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'ola', kind: 'reply' }) })
    estado = reduzir(estado, { tipo: 'enviou', messageId: 'm1', texto: 'ainda enviando' })

    const depois = reduzir(estado, {
      tipo: 'frame',
      bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'agente', texto: 'do historico' }] }),
    })

    expect(depois.mensagens).toEqual([
      { autor: 'agente', chave: 'agente-1', texto: 'do historico' },
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

  describe('historico reaproveita a identidade do que ja esta na tela (chaves estaveis)', () => {
    // Uma chave nova remonta o `<li>`, e o `log` com `additions` anuncia de
    // novo o balao remontado: a reconexao nao pode trocar a chave de quem
    // ja estava na tela.
    function telaComTresFalas(): Conversa {
      let estado = comVisitanteEnviando('m1', 'Quero um apartamento')
      estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })
      estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'Claro!', kind: 'reply' }) })
      estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'Qual bairro?', kind: 'reply' }) })
      return estado
    }

    const HISTORICO_DAS_TRES = [
      { papel: 'lead', texto: 'Quero um apartamento' },
      { papel: 'agente', texto: 'Claro!' },
      { papel: 'agente', texto: 'Qual bairro?' },
    ]

    function chaveDe(mensagem: Mensagem): string {
      return mensagem.autor === 'visitante' ? mensagem.messageId : mensagem.chave
    }

    it('historico igual a tela, sem pendente, devolve a mesma referencia', () => {
      const antes = telaComTresFalas()
      const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'historico', mensagens: HISTORICO_DAS_TRES }) })
      expect(depois).toBe(antes)
    })

    it('historico vazio com a tela vazia devolve a mesma referencia', () => {
      const depois = reduzir(INICIAL, { tipo: 'frame', bruto: frame({ tipo: 'historico', mensagens: [] }) })
      expect(depois).toBe(INICIAL)
    })

    it('historico igual a tela com uma pendente no fim mantem os mesmos objetos', () => {
      const antes = reduzir(telaComTresFalas(), { tipo: 'enviou', messageId: 'm2', texto: 'no Campeche' })
      const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'historico', mensagens: HISTORICO_DAS_TRES }) })
      expect(depois.mensagens).toHaveLength(4)
      depois.mensagens.forEach((mensagem, i) => expect(mensagem).toBe(antes.mensagens[i]))
    })

    it('uma fala nova do agente no fim do historico: so ela ganha chave nova', () => {
      const antes = telaComTresFalas()
      const depois = reduzir(antes, {
        tipo: 'frame',
        bruto: frame({ tipo: 'historico', mensagens: [...HISTORICO_DAS_TRES, { papel: 'agente', texto: 'Ainda está por aí?' }] }),
      })
      expect(depois.mensagens.slice(0, 3).map(chaveDe)).toEqual(antes.mensagens.map(chaveDe))
      const nova = depois.mensagens[3]
      expect(nova).toMatchObject({ autor: 'agente', texto: 'Ainda está por aí?' })
      expect(antes.mensagens.map(chaveDe)).not.toContain(chaveDe(nova))
    })

    it('uma fala que falta no historico (moderacao): as outras mantem a chave', () => {
      const antes = telaComTresFalas()
      const depois = reduzir(antes, {
        tipo: 'frame',
        bruto: frame({ tipo: 'historico', mensagens: [HISTORICO_DAS_TRES[0], HISTORICO_DAS_TRES[2]] }),
      })
      expect(depois.mensagens.map(chaveDe)).toEqual([chaveDe(antes.mensagens[0]), chaveDe(antes.mensagens[2])])
      expect(depois.mensagens[0]).toBe(antes.mensagens[0])
      expect(depois.mensagens[1]).toBe(antes.mensagens[2])
    })

    it('a fala seguinte a uma remocao nao repete a chave de quem ficou', () => {
      let estado = telaComTresFalas()
      estado = reduzir(estado, {
        tipo: 'frame',
        bruto: frame({ tipo: 'historico', mensagens: [HISTORICO_DAS_TRES[1], HISTORICO_DAS_TRES[2]] }),
      })
      // Sobram 2 baloes com as chaves de quando eram 3: uma chave derivada do
      // comprimento da lista repetiria a do ultimo.
      estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'Tem vaga?', kind: 'reply' }) })
      const chaves = estado.mensagens.map(chaveDe)
      expect(chaves).toHaveLength(3)
      expect(new Set(chaves).size).toBe(3)
    })
  })

  it('consentimento_registrado mantem o estado, mesma referencia', () => {
    const antes = INICIAL
    const depois = reduzir(antes, { tipo: 'frame', bruto: frame({ tipo: 'consentimento_registrado' }) })
    expect(depois).toBe(antes)
  })

  it('fechou com 1002 marca toda mensagem enviando como falhou e fecha a conexao, sem reconectar', () => {
    let estado = comVisitanteEnviando('m1')
    estado = reduzir(estado, { tipo: 'enviou', messageId: 'm2', texto: 'outra' })
    estado = reduzir(estado, { tipo: 'abriu' })

    const depois = reduzir(estado, { tipo: 'fechou', codigo: 1002, agora: 0 })

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
    const depois = reduzir(aguardando, { tipo: 'fechou', codigo: 1013, agora: 0 })
    expect(depois.conexao).toEqual({ tipo: 'aguardando', mensagem: 'espera', segundos: 5 })
  })

  it('reabrindo encerra a espera: conectando, e uma queda depois reconecta', () => {
    const aguardando = reduzir(INICIAL, {
      tipo: 'frame',
      bruto: frame({ tipo: 'erro', codigo: 'muitas_tentativas', mensagem: 'espera', aguardeSegundos: 5 }),
    })
    const reabrindo = reduzir(aguardando, { tipo: 'reabrindo' })
    expect(reabrindo.conexao).toEqual({ tipo: 'conectando' })

    const depois = reduzir(reabrindo, { tipo: 'fechou', codigo: 1006, agora: 50 })
    expect(depois.conexao).toEqual({ tipo: 'reconectando', tentativa: 1, desde: 50, instavel: false })
  })

  it('reabrindo acorda do sono: conectando, e uma queda depois reconecta (D4)', () => {
    const adormecida = reduzir(INICIAL, { tipo: 'adormeceu' })
    const reabrindo = reduzir(adormecida, { tipo: 'reabrindo' })
    expect(reabrindo.conexao).toEqual({ tipo: 'conectando' })

    const depois = reduzir(reabrindo, { tipo: 'fechou', codigo: 1006, agora: 50 })
    expect(depois.conexao).toEqual({ tipo: 'reconectando', tentativa: 1, desde: 50, instavel: false })
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

    expect(depois).toEqual({ mensagens: [], conexao: { tipo: 'conectando' }, sessao: null, digitando: null })
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
      digitando: null,
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

    const depois = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 0 })

    expect(depois.conexao).toEqual({ tipo: 'adormecida' })
    expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'falhou' }])
  })

  it('fechou com a conexao adormecida e nada pendente mantem a mesma referencia', () => {
    const antes = reduzir(INICIAL, { tipo: 'adormeceu' })
    const depois = reduzir(antes, { tipo: 'fechou', codigo: 1006, agora: 0 })
    expect(depois).toBe(antes)
  })

  it('abriu a partir de adormecida vai para aberta', () => {
    const adormecida = reduzir(INICIAL, { tipo: 'adormeceu' })
    const depois = reduzir(adormecida, { tipo: 'abriu' })
    expect(depois.conexao).toEqual({ tipo: 'aberta' })
  })
})

describe('esperaDaTentativa (TEC-348, D1)', () => {
  it.each([
    [1, 1],
    [2, 2],
    [3, 4],
    [4, 8],
    [5, 16],
    [6, 30],
    [7, 30],
    [20, 30],
  ])('a tentativa %i espera %i s', (tentativa, espera) => {
    expect(esperaDaTentativa(tentativa)).toBe(espera)
  })
})

describe('reconexao (TEC-348)', () => {
  function aberta(): Conversa {
    return reduzir(comVisitanteEnviando('m1'), { tipo: 'abriu' })
  }

  it('queda com a conexao aberta reconecta e mantem a pendente enviando', () => {
    const depois = reduzir(aberta(), { tipo: 'fechou', codigo: 1006, agora: 1000 })
    expect(depois.conexao).toEqual({ tipo: 'reconectando', tentativa: 1, desde: 1000, instavel: false })
    expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'enviando' }])
  })

  it('a tentativa que nao abre soma uma e mantem o instante da primeira queda', () => {
    let estado = reduzir(aberta(), { tipo: 'fechou', codigo: 1006, agora: 1000 })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 2000 })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 4000 })
    expect(estado.conexao).toEqual({ tipo: 'reconectando', tentativa: 3, desde: 1000, instavel: false })
  })

  it('1011 marca a queda como instavel, e ela continua instavel nas tentativas seguintes', () => {
    let estado = reduzir(aberta(), { tipo: 'fechou', codigo: 1011, agora: 1000 })
    expect(estado.conexao).toEqual({ tipo: 'reconectando', tentativa: 1, desde: 1000, instavel: true })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 2000 })
    expect(estado.conexao).toEqual({ tipo: 'reconectando', tentativa: 2, desde: 1000, instavel: true })
  })

  it('1011 numa tentativa que nao abre torna a queda instavel dali em diante', () => {
    let estado = reduzir(aberta(), { tipo: 'fechou', codigo: 1006, agora: 1000 })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1011, agora: 2000 })
    expect(estado.conexao).toEqual({ tipo: 'reconectando', tentativa: 2, desde: 1000, instavel: true })
  })

  it('abriu durante a reconexao zera a contagem: a proxima queda e tentativa 1 de novo', () => {
    let estado = reduzir(aberta(), { tipo: 'fechou', codigo: 1006, agora: 1000 })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 2000 })
    estado = reduzir(estado, { tipo: 'abriu' })
    expect(estado.conexao).toEqual({ tipo: 'aberta' })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 9000 })
    expect(estado.conexao).toEqual({ tipo: 'reconectando', tentativa: 1, desde: 9000, instavel: false })
  })

  it('desistiu leva a reconexao a offline, levando o instavel, e mantem a pendente', () => {
    let estado = reduzir(aberta(), { tipo: 'fechou', codigo: 1011, agora: 1000 })
    estado = reduzir(estado, { tipo: 'desistiu' })
    expect(estado.conexao).toEqual({ tipo: 'offline', instavel: true })
    expect(estado.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'oi', estado: 'enviando' }])
  })

  it('desistiu fora de uma reconexao devolve a mesma referencia', () => {
    const antes = aberta()
    expect(reduzir(antes, { tipo: 'desistiu' })).toBe(antes)
  })

  it('queda em offline -- a ultima tentativa -- devolve a mesma referencia', () => {
    let estado = reduzir(aberta(), { tipo: 'fechou', codigo: 1006, agora: 1000 })
    estado = reduzir(estado, { tipo: 'desistiu' })
    expect(reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 400_000 })).toBe(estado)
  })

  it('reabrindo a partir de offline ("Tentar de novo") volta a conectando, e a queda seguinte recomeca a contagem', () => {
    let estado = reduzir(aberta(), { tipo: 'fechou', codigo: 1006, agora: 1000 })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 2000 })
    estado = reduzir(estado, { tipo: 'desistiu' })
    estado = reduzir(estado, { tipo: 'reabrindo' })
    expect(estado.conexao).toEqual({ tipo: 'conectando' })
    estado = reduzir(estado, { tipo: 'fechou', codigo: 1006, agora: 500_000 })
    expect(estado.conexao).toEqual({ tipo: 'reconectando', tentativa: 1, desde: 500_000, instavel: false })
  })

  it('a primeira conexao que nao abre tambem reconecta', () => {
    const depois = reduzir(INICIAL, { tipo: 'fechou', codigo: 1006, agora: 1000 })
    expect(depois.conexao).toEqual({ tipo: 'reconectando', tentativa: 1, desde: 1000, instavel: false })
  })

  describe('historico confirma a pendente que o servidor ja gravou (D5)', () => {
    it('a pendente vai para a posicao do historico, recebida, com o mesmo messageId', () => {
      let estado = reduzir(INICIAL, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'Olá!' }) })
      estado = reduzir(estado, { tipo: 'enviou', messageId: 'm1', texto: 'Tem vaga de garagem?' })

      const depois = reduzir(estado, {
        tipo: 'frame',
        bruto: frame({
          tipo: 'historico',
          mensagens: [
            { papel: 'agente', texto: 'Olá!' },
            { papel: 'lead', texto: 'Tem vaga de garagem?' },
            { papel: 'agente', texto: 'Tem sim, uma vaga.' },
          ],
        }),
      })

      expect(depois.mensagens).toEqual([
        { autor: 'agente', chave: 'agente-0', texto: 'Olá!' },
        { autor: 'visitante', messageId: 'm1', texto: 'Tem vaga de garagem?', estado: 'recebida' },
        { autor: 'agente', chave: 'agente-1', texto: 'Tem sim, uma vaga.' },
      ])
    })

    it('a pendente que falhou tambem e confirmada', () => {
      let estado = comVisitanteEnviando('m1', 'Aceita pet?')
      estado = reduzir(estado, { tipo: 'prazoDoAck', messageId: 'm1' })

      const depois = reduzir(estado, {
        tipo: 'frame',
        bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'lead', texto: 'Aceita pet?' }] }),
      })

      expect(depois.mensagens).toEqual([{ autor: 'visitante', messageId: 'm1', texto: 'Aceita pet?', estado: 'recebida' }])
    })

    it('texto repetido casa pela ordem: a primeira fala nova confirma a primeira pendente igual', () => {
      let estado = comVisitanteEnviando('m1', 'sim')
      estado = reduzir(estado, { tipo: 'enviou', messageId: 'm2', texto: 'sim' })

      const depois = reduzir(estado, {
        tipo: 'frame',
        bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'lead', texto: 'sim' }] }),
      })

      expect(depois.mensagens).toEqual([
        { autor: 'visitante', messageId: 'm1', texto: 'sim', estado: 'recebida' },
        { autor: 'visitante', messageId: 'm2', texto: 'sim', estado: 'enviando' },
      ])
    })

    it('fala da visitante que ja estava confirmada na tela nao consome a pendente de mesmo texto', () => {
      let estado = comVisitanteEnviando('m1', 'ok')
      estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'ack', messageId: 'm1' }) })
      estado = reduzir(estado, { tipo: 'enviou', messageId: 'm2', texto: 'ok' })

      const depois = reduzir(estado, {
        tipo: 'frame',
        bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'lead', texto: 'ok' }] }),
      })

      expect(depois).toBe(estado)
    })
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

// --- TEC-349: a fileira de cards de imovel ---

function imovel(id: string) {
  return {
    id,
    titulo: `Apto ${id}`,
    bairro: 'Campeche',
    precoCentavos: 51_646_430,
    condominioCentavos: null,
    quartos: 2,
    vagas: 1,
    areaUtilM2: 70,
    diferencial: null,
    foto: null,
    url: null,
  }
}

function comFicha(estado: Conversa, id: string, kind: string, texto: string | null = null): Conversa {
  return reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'imovel', kind, texto, imovel: imovel(id) }) })
}

function fileiras(estado: Conversa): string[][] {
  return estado.mensagens
    .filter((m): m is Extract<Mensagem, { autor: 'imoveis' }> => m.autor === 'imoveis')
    .map((m) => m.imoveis.map((i) => i.id))
}

describe('reduzir -- cards de imovel (TEC-349)', () => {
  it('os tres frames do turno viram uma fileira, com a prosa antes', () => {
    let estado = comFicha(INICIAL, 'a', 'ficha_1', 'Separei tres opcoes')
    estado = comFicha(estado, 'b', 'ficha_2')
    estado = comFicha(estado, 'c', 'ficha_3')

    expect(estado.mensagens.map((m) => m.autor)).toEqual(['agente', 'imoveis'])
    expect(fileiras(estado)).toEqual([['a', 'b', 'c']])
  })

  it('ficha_1 abre fileira nova mesmo logo depois de outra', () => {
    // Dois turnos seguidos, o segundo sem prosa: sem o kind, os cards dos dois
    // se juntariam numa fileira so.
    let estado = comFicha(INICIAL, 'a', 'ficha_1')
    estado = comFicha(estado, 'b', 'ficha_1')

    expect(fileiras(estado)).toEqual([['a'], ['b']])
  })

  it('a fileira nao passa do teto', () => {
    let estado = comFicha(INICIAL, 'a', 'ficha_1')
    for (const id of ['b', 'c', 'd']) {
      estado = comFicha(estado, id, 'ficha_2')
    }

    expect(MAXIMO_DE_CARDS).toBe(3)
    expect(fileiras(estado)).toEqual([['a', 'b', 'c'], ['d']])
  })

  it('a fileira ganha chave propria, que nao repete a de ninguem', () => {
    let estado = reduzir(INICIAL, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'oi' }) })
    estado = comFicha(estado, 'a', 'ficha_1', 'veja')

    const chaves = estado.mensagens.map((m) => (m.autor === 'visitante' ? m.messageId : m.chave))
    expect(chaves).toEqual(['agente-0', 'agente-1', 'imoveis-2'])
  })

  it('frame que nao e ficha_1 depois de um balao abre fileira nova', () => {
    let estado = comFicha(INICIAL, 'a', 'ficha_1')
    estado = reduzir(estado, { tipo: 'frame', bruto: frame({ tipo: 'mensagem', texto: 'mais uma coisa' }) })
    estado = comFicha(estado, 'b', 'ficha_2')

    expect(fileiras(estado)).toEqual([['a'], ['b']])
  })

  it('o historico da reconexao troca a fileira pelos baloes que ele traz', () => {
    // L2 da TEC-364: o historico guarda a legenda, nao o card.
    const estado = comFicha(INICIAL, 'a', 'ficha_1')
    const depois = reduzir(estado, {
      tipo: 'frame',
      bruto: frame({ tipo: 'historico', mensagens: [{ papel: 'agente', texto: 'Apto a em Campeche' }] }),
    })

    expect(depois.mensagens).toEqual([{ autor: 'agente', chave: 'agente-1', texto: 'Apto a em Campeche' }])
  })
})

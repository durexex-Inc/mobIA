import { describe, expect, it } from 'vitest'

import {
  type Configuracao,
  diffDe,
  estaSujo,
  formatarValorDoHistorico,
  type Formulario,
  formularioDe,
  formularioValido,
  type Limites,
  pedidoDeEdicao,
  recusaDe,
  rotuloDeCampo,
  validarFormulario,
} from './configuracao'

const CONFIGURACAO: Configuracao = {
  nomeDoAssistente: 'Ana',
  tom: 'CORDIAL',
  tetoDePerguntas: 8,
  pesoCompletude: 20,
  pesoUrgencia: 25,
  pesoCatalogo: 20,
  pesoEngajamento: 15,
  pesoCapacidade: 15,
  cadencia: { QUENTE: [2, 24, 72, 168], MORNO: [24, 96, 240], FRIO: [72, 336] },
  orcamentoMensalUsd: '100.00',
  corPrimaria: '#1D4ED8',
  posicaoDoBotao: 'DIREITA',
  dominiosDoChat: [],
}

const LIMITES: Limites = {
  nomeDoAssistente: { maximoDeCaracteres: 30, nulavel: true },
  tom: { valores: ['CORDIAL', 'FORMAL', 'DESCONTRAIDO'] },
  tetoDePerguntas: { minimo: 1, maximo: 20 },
  pesos: { minimo: 0, maximo: 50, somaMaxima: 100 },
  cadencia: {
    tentativasPorTemperatura: { QUENTE: 4, MORNO: 3, FRIO: 2 },
    horaMinima: 1,
    horaMaxima: 2160,
  },
  orcamentoMensalUsd: { minimo: '0.01', maximo: '100000', nulavel: true },
  corPrimaria: {},
  posicaoDoBotao: {},
  dominiosDoChat: {},
}

describe('formularioDe', () => {
  it('traz os sete campos desta tela, cadencia em texto', () => {
    expect(formularioDe(CONFIGURACAO)).toEqual({
      nomeDoAssistente: 'Ana',
      tom: 'CORDIAL',
      tetoDePerguntas: '8',
      pesoCompletude: '20',
      pesoUrgencia: '25',
      pesoCatalogo: '20',
      pesoEngajamento: '15',
      pesoCapacidade: '15',
      cadencia: { QUENTE: ['2', '24', '72', '168'], MORNO: ['24', '96', '240'], FRIO: ['72', '336'] },
      orcamentoMensalUsd: '100.00',
    })
  })

  it('nome ausente e orcamento ausente viram string vazia', () => {
    const formulario = formularioDe({ ...CONFIGURACAO, nomeDoAssistente: null, orcamentoMensalUsd: null })
    expect(formulario.nomeDoAssistente).toBe('')
    expect(formulario.orcamentoMensalUsd).toBe('')
  })

  it('nao expoe corPrimaria/posicaoDoBotao/dominiosDoChat', () => {
    const formulario = formularioDe(CONFIGURACAO) as Record<string, unknown>
    expect(formulario).not.toHaveProperty('corPrimaria')
    expect(formulario).not.toHaveProperty('posicaoDoBotao')
    expect(formulario).not.toHaveProperty('dominiosDoChat')
  })
})

describe('validarFormulario / formularioValido (D2 -- faixas vem de limites)', () => {
  const valido = formularioDe(CONFIGURACAO)

  it('formulario completo e valido', () => {
    expect(formularioValido(valido, LIMITES)).toBe(true)
  })

  it('nome acima do maximo de limites recusa', () => {
    const recusa = validarFormulario({ ...valido, nomeDoAssistente: 'a'.repeat(31) }, LIMITES)
    expect(recusa.porCampo.nomeDoAssistente).toBeDefined()
  })

  it('tom vazio recusa', () => {
    expect(validarFormulario({ ...valido, tom: '' }, LIMITES).porCampo.tom).toBeDefined()
  })

  it('teto de perguntas fora da faixa de limites recusa', () => {
    expect(validarFormulario({ ...valido, tetoDePerguntas: '0' }, LIMITES).porCampo.tetoDePerguntas).toBeDefined()
    expect(validarFormulario({ ...valido, tetoDePerguntas: '21' }, LIMITES).porCampo.tetoDePerguntas).toBeDefined()
    expect(validarFormulario({ ...valido, tetoDePerguntas: '20' }, LIMITES).porCampo.tetoDePerguntas).toBeUndefined()
  })

  it('peso negativo (cenario 2 do Gherkin: recusar valor fora da faixa) recusa pelo limite, nao por numero fixo', () => {
    const recusa = validarFormulario({ ...valido, pesoUrgencia: '-1' }, LIMITES)
    expect(recusa.porCampo.pesoUrgencia).toBeDefined()

    // O mesmo -1 passaria com um teto de peso maior -- a mensagem/decisao
    // depende de `limites`, nao de um numero escrito neste modulo.
    const limitesFrouxos: Limites = {
      ...LIMITES,
      pesos: { minimo: -10, maximo: 50, somaMaxima: 100 },
    }
    expect(validarFormulario({ ...valido, pesoUrgencia: '-1' }, limitesFrouxos).porCampo.pesoUrgencia).toBeUndefined()
  })

  it('peso acima do maximo de limites recusa', () => {
    expect(validarFormulario({ ...valido, pesoCatalogo: '51' }, LIMITES).porCampo.pesoCatalogo).toBeDefined()
  })

  it('cadencia com campo vazio recusa -- so "campo vazio", sem faixa nem crescente (D3)', () => {
    const recusa = validarFormulario(
      { ...valido, cadencia: { ...valido.cadencia, QUENTE: ['2', '', '72', '168'] } },
      LIMITES,
    )
    expect(recusa.porCampo.cadencia).toBeDefined()
  })

  it('cadencia fora de faixa (ex: 99999) NAO recusa no cliente -- e do backend (D3)', () => {
    const recusa = validarFormulario(
      { ...valido, cadencia: { ...valido.cadencia, QUENTE: ['2', '24', '72', '99999'] } },
      LIMITES,
    )
    expect(recusa.porCampo.cadencia).toBeUndefined()
  })

  it('orcamento vazio e permitido (nulavel)', () => {
    expect(validarFormulario({ ...valido, orcamentoMensalUsd: '' }, LIMITES).porCampo.orcamentoMensalUsd).toBeUndefined()
  })

  it('orcamento fora da faixa de limites recusa', () => {
    expect(
      validarFormulario({ ...valido, orcamentoMensalUsd: '0' }, LIMITES).porCampo.orcamentoMensalUsd,
    ).toBeDefined()
    expect(
      validarFormulario({ ...valido, orcamentoMensalUsd: '200000' }, LIMITES).porCampo.orcamentoMensalUsd,
    ).toBeDefined()
  })
})

describe('diffDe (D4)', () => {
  const inicial = formularioDe(CONFIGURACAO)

  it('sem mudanca, diff vazio e nao esta sujo', () => {
    expect(diffDe(inicial, inicial)).toEqual([])
    expect(estaSujo(inicial, inicial)).toBe(false)
  })

  it('mudar o tom aparece com o rotulo e o texto do formulario', () => {
    const atual: Formulario = { ...inicial, tom: 'FORMAL' }
    expect(diffDe(inicial, atual)).toEqual([{ campo: 'tom', rotulo: 'Tom', de: 'CORDIAL', para: 'FORMAL' }])
  })

  it('mudar um peso mostra "de -> para" com o rotulo do peso', () => {
    const atual: Formulario = { ...inicial, pesoUrgencia: '30' }
    expect(diffDe(inicial, atual)).toEqual([
      { campo: 'pesoUrgencia', rotulo: 'Peso de urgência', de: '25', para: '30' },
    ])
  })

  it('mudar a cadencia de uma temperatura entra como "Cadência (TEMPERATURA)"', () => {
    const atual: Formulario = {
      ...inicial,
      cadencia: { ...inicial.cadencia, MORNO: ['24', '100', '240'] },
    }
    expect(diffDe(inicial, atual)).toEqual([
      { campo: 'cadencia', rotulo: 'Cadência (MORNO)', de: '24, 96, 240', para: '24, 100, 240' },
    ])
  })
})

describe('pedidoDeEdicao / estaSujo', () => {
  const inicial = formularioDe(CONFIGURACAO)

  it('so o que mudou vai', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, tom: 'FORMAL' })).toEqual({ tom: 'FORMAL' })
  })

  it('sem mudanca, corpo vazio', () => {
    expect(pedidoDeEdicao(inicial, inicial)).toEqual({})
  })

  it('nome vazio manda null (limpa o nome)', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, nomeDoAssistente: '' })).toEqual({
      nomeDoAssistente: null,
    })
  })

  it('orcamento vazio manda null (limpa o orcamento)', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, orcamentoMensalUsd: '' })).toEqual({
      orcamentoMensalUsd: null,
    })
  })

  it('pesos e teto viram Number', () => {
    expect(pedidoDeEdicao(inicial, { ...inicial, tetoDePerguntas: '10', pesoCapacidade: '10' })).toEqual({
      tetoDePerguntas: 10,
      pesoCapacidade: 10,
    })
  })

  it('mudar so uma temperatura manda a cadencia INTEIRA -- o backend substitui o dict todo', () => {
    const atual: Formulario = {
      ...inicial,
      cadencia: { ...inicial.cadencia, QUENTE: ['2', '24', '72', '200'] },
    }
    expect(pedidoDeEdicao(inicial, atual)).toEqual({
      cadencia: { QUENTE: [2, 24, 72, 200], MORNO: [24, 96, 240], FRIO: [72, 336] },
    })
  })

  it('nunca inclui seVersao -- e o chamador quem acrescenta', () => {
    const corpo = pedidoDeEdicao(inicial, { ...inicial, tom: 'FORMAL' })
    expect(corpo).not.toHaveProperty('seVersao')
  })
})

describe('recusaDe (D1/D5 -- 409 de conflito de versao)', () => {
  it('409 com string do backend marca conflitoDeVersao', () => {
    const recusa = recusaDe(409, 'a configuracao foi alterada por outra pessoa; recarregue')
    expect(recusa.geral).toBe('a configuracao foi alterada por outra pessoa; recarregue')
    expect(recusa.conflitoDeVersao).toBe(true)
  })

  it('422 com string do backend vai inteira para o aviso geral, sem conflitoDeVersao', () => {
    const recusa = recusaDe(422, 'peso de urgencia -1 fora da faixa 0..50')
    expect(recusa.geral).toBe('peso de urgencia -1 fora da faixa 0..50')
    expect(recusa.conflitoDeVersao).toBeUndefined()
  })

  it('401, 403 e generico', () => {
    expect(recusaDe(401, null).geral).toMatch(/sessão terminou/)
    expect(recusaDe(403, null).geral).toMatch(/permissão/)
    expect(recusaDe(500, null).geral).toBe('Não foi possível salvar. Tente de novo.')
  })
})

describe('rotuloDeCampo / formatarValorDoHistorico', () => {
  it('rotuloDeCampo cobre os campos conhecidos e devolve o nome cru como fallback', () => {
    expect(rotuloDeCampo('pesoUrgencia')).toBe('Peso de urgência')
    expect(rotuloDeCampo('cadencia')).toBe('Cadência')
    expect(rotuloDeCampo('campoDesconhecido')).toBe('campoDesconhecido')
  })

  it('formatarValorDoHistorico: null vira travessao, numero e string ficam como sao', () => {
    expect(formatarValorDoHistorico(null)).toBe('—')
    expect(formatarValorDoHistorico(25)).toBe('25')
    expect(formatarValorDoHistorico('CORDIAL')).toBe('CORDIAL')
  })

  it('formatarValorDoHistorico: cadencia (objeto) vira uma linha por temperatura', () => {
    expect(formatarValorDoHistorico({ QUENTE: [2, 24, 72, 168], MORNO: [24, 96, 240] })).toBe(
      'QUENTE: 2, 24, 72, 168; MORNO: 24, 96, 240',
    )
  })
})

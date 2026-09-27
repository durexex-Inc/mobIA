import { describe, expect, it } from 'vitest'

import { estaSujo, formularioDe, pedidoDaEdicao, recusaDe } from './qualificacao'

const FICHA = {
  intencao: 'COMPRA',
  regiao: 'centro',
  tipoImovel: 'APARTAMENTO',
  quartos: 2,
  vagas: null,
  faixaPrecoMinCentavos: 40_000_000,
  faixaPrecoMaxCentavos: 50_000_050,
  urgencia: 'ATE_3_MESES',
  formaPagamento: null,
  temImovelParaVender: false,
}

describe('formularioDe', () => {
  it('traz a ficha para texto, com a faixa em reais', () => {
    expect(formularioDe(FICHA)).toEqual({
      regiao: 'centro',
      tipoImovel: 'APARTAMENTO',
      quartos: '2',
      vagas: '',
      precoMinReais: '400000',
      precoMaxReais: '500001',
      urgencia: 'ATE_3_MESES',
      formaPagamento: '',
      temImovelParaVender: 'false',
    })
  })

  it('sem ficha, tudo vazio', () => {
    expect(Object.values(formularioDe(null)).every((v) => v === '')).toBe(true)
  })
})

describe('pedidoDaEdicao', () => {
  const inicial = formularioDe(FICHA)

  it('so o que mudou vai -- o arredondamento de reais nao vira edicao', () => {
    expect(pedidoDaEdicao(inicial, { ...inicial, regiao: 'Campeche' })).toEqual({ regiao: 'Campeche' })
  })

  it('reais viram centavos, e numero de texto vira numero', () => {
    expect(
      pedidoDaEdicao(inicial, { ...inicial, precoMaxReais: '800000', quartos: '3' }),
    ).toEqual({ faixaPrecoMaxCentavos: 80_000_000, quartos: 3 })
  })

  it('esvaziar vai como `null`, que e "limpa"', () => {
    expect(pedidoDaEdicao(inicial, { ...inicial, tipoImovel: '', regiao: '  ' })).toEqual({
      tipoImovel: null,
      regiao: null,
    })
  })

  it('o booleano vai como booleano', () => {
    expect(pedidoDaEdicao(inicial, { ...inicial, temImovelParaVender: 'true' })).toEqual({
      temImovelParaVender: true,
    })
  })

  it('espaco a mais nao e mudanca', () => {
    expect(estaSujo(inicial, { ...inicial, regiao: ' centro ' })).toBe(false)
    expect(estaSujo(inicial, { ...inicial, regiao: 'sul' })).toBe(true)
  })
})

describe('recusaDe', () => {
  it('o 422 do pydantic vai para o campo do `loc`, traduzido', () => {
    const recusa = recusaDe(422, [
      { type: 'less_than_equal', loc: ['body', 'quartos'], msg: 'Input should be <= 50', ctx: { le: 50 } },
      { type: 'greater_than_equal', loc: ['body', 'faixaPrecoMaxCentavos'], msg: 'x', ctx: { ge: 0 } },
    ])

    expect(recusa).toEqual({
      porCampo: { quartos: 'Deve ser no máximo 50.', precoMaxReais: 'Deve ser no mínimo 0.' },
      geral: null,
    })
  })

  it('tipo sem traducao mostra o `msg` do backend', () => {
    expect(recusaDe(422, [{ type: 'outro', loc: ['body', 'regiao'], msg: 'nope' }]).porCampo).toEqual({
      regiao: 'nope',
    })
  })

  it('erro sem campo reconhecido vai para o topo', () => {
    expect(recusaDe(422, [{ type: 'extra_forbidden', loc: ['body', 'intencao'], msg: 'Extra' }])).toEqual({
      porCampo: {},
      geral: 'Extra',
    })
  })

  it('`faixa_invertida` vai para a faixa de preco', () => {
    expect(recusaDe(422, 'faixa_invertida').porCampo.precoMinReais).toBe(
      'O valor mínimo não pode passar do máximo.',
    )
  })

  it('409 de conversa encerrada, e os status de sempre', () => {
    expect(recusaDe(409, 'conversa_encerrada').geral).toBe(
      'A conversa foi encerrada: a qualificação não pode mais ser editada.',
    )
    expect(recusaDe(401, null).geral).toMatch(/sessão terminou/)
    expect(recusaDe(403, null).geral).toMatch(/permissão/)
    expect(recusaDe(500, null).geral).toBe('Não foi possível salvar. Tente de novo.')
  })
})

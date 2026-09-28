import { describe, expect, it } from 'vitest'

import { lerPrivacidade } from './privacidade'

const CONFIGURADA = {
  avisoDePrivacidadeUrl: 'https://imobiliaria.com.br/privacidade',
  encarregadoEmail: 'encarregado@imobiliaria.com.br',
}

describe('lerPrivacidade (TEC-352)', () => {
  it('le o aviso e o encarregado', () => {
    expect(lerPrivacidade(CONFIGURADA)).toEqual({
      avisoUrl: 'https://imobiliaria.com.br/privacidade',
      encarregadoEmail: 'encarregado@imobiliaria.com.br',
    })
  })

  it.each([
    ['sem aviso', { ...CONFIGURADA, avisoDePrivacidadeUrl: null }],
    ['sem encarregado', { ...CONFIGURADA, encarregadoEmail: null }],
    ['aviso com esquema perigoso', { ...CONFIGURADA, avisoDePrivacidadeUrl: 'javascript:alert(1)' }],
    ['encarregado que nao e e-mail', { ...CONFIGURADA, encarregadoEmail: 'encarregado' }],
    ['corpo antigo, sem os campos', { tenant: 'x' }],
  ])('%s: null, e o chat nao abre (D2)', (_caso, corpo) => {
    expect(lerPrivacidade(corpo)).toBeNull()
  })
})

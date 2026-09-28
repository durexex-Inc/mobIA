import { describe, expect, it } from 'vitest'

import { contagem, imovelDe, reais, textoAlternativo, textoDaReacao, urlSegura } from './imovel'

const COMPLETO = {
  id: 'i1',
  titulo: 'Casa 3 quartos',
  bairro: 'Lagoa da Conceição',
  precoCentavos: 51_646_430,
  condominioCentavos: 85_000,
  quartos: 3,
  vagas: 2,
  areaUtilM2: 98,
  diferencial: 'piscina',
  foto: 'https://cdn.exemplo.com/f.jpg',
  url: null,
}

const OBRIGATORIOS = {
  id: 'i1',
  titulo: 'Casa 3 quartos',
  bairro: 'Lagoa da Conceição',
  precoCentavos: 51_646_430,
  quartos: 3,
  vagas: 2,
  areaUtilM2: 98,
}

describe('imovelDe', () => {
  it('le o card inteiro no formato da TEC-364', () => {
    expect(imovelDe(COMPLETO)).toEqual(COMPLETO)
  })

  it('os quatro campos opcionais podem faltar', () => {
    expect(imovelDe(OBRIGATORIOS)).toEqual({
      ...OBRIGATORIOS,
      condominioCentavos: null,
      diferencial: null,
      foto: null,
      url: null,
    })
  })

  it.each(['titulo', 'bairro', 'precoCentavos', 'quartos', 'vagas', 'areaUtilM2', 'id'])(
    'sem %s nao ha card',
    (campo) => {
      expect(imovelDe({ ...COMPLETO, [campo]: undefined })).toBeNull()
    },
  )

  it('numero com o tipo errado nao vira card', () => {
    expect(imovelDe({ ...COMPLETO, precoCentavos: '516464' })).toBeNull()
    expect(imovelDe({ ...COMPLETO, quartos: 2.5 })).toBeNull()
  })

  it('nao objeto nao e card', () => {
    expect(imovelDe(null)).toBeNull()
    expect(imovelDe([COMPLETO])).toBeNull()
  })
})

describe('urlSegura', () => {
  it('so http e https passam', () => {
    expect(urlSegura('https://site.com/imovel/1')).toBe('https://site.com/imovel/1')
    expect(urlSegura('javascript:alert(1)')).toBeNull()
    expect(urlSegura('data:text/html,oi')).toBeNull()
    expect(urlSegura('nao e url')).toBeNull()
  })

  it('foto e url perigosas somem do card, e o card fica', () => {
    const card = imovelDe({ ...COMPLETO, foto: 'javascript:1', url: 'javascript:2' })
    expect(card?.foto).toBeNull()
    expect(card?.url).toBeNull()
  })
})

describe('formatacao', () => {
  it('trunca os centavos, como `reais_de` no servidor', () => {
    expect(reais(51_646_499)).toBe('R$ 516.464')
    expect(reais(85_000)).toBe('R$ 850')
  })

  it('singular e plural', () => {
    expect(contagem(1, 'quarto', 'quartos')).toBe('1 quarto')
    expect(contagem(3, 'quarto', 'quartos')).toBe('3 quartos')
  })

  it('o texto alternativo e o da card', () => {
    expect(textoAlternativo(COMPLETO)).toBe('Foto de Casa 3 quartos em Lagoa da Conceição')
  })

  it('o texto da reacao leva titulo e bairro, que e o que o servidor le de cada imovel (TEC-350, D1)', () => {
    expect(textoDaReacao('gostei', COMPLETO)).toBe('Gostei do imóvel "Casa 3 quartos" (Lagoa da Conceição).')
    expect(textoDaReacao('nao_e_pra_mim', COMPLETO)).toBe(
      'O imóvel "Casa 3 quartos" (Lagoa da Conceição) não é pra mim.',
    )
  })
})

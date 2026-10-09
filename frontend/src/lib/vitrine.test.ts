import { describe, expect, it } from 'vitest'

import { itemDaVitrineDe, paginasVisiveis, precoCurto, totalDePaginas } from './vitrine'

const BRUTO = {
  id: 'i-1',
  codigo: 'IT-9821',
  titulo: 'Apartamento em Itacorubi',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  bairro: 'Itacorubi',
  cidade: 'Florianópolis',
  uf: 'SC',
  areaUtilM2: 163,
  quartos: 3,
  suites: 2,
  banheiros: 3,
  vagas: 1,
  preco: 177976100,
  condominio: 225900,
  iptuMensal: null,
  caracteristicas: ['varanda'],
  foto: '/portal/imoveis/i-1/fotos/f-1',
  latitude: -27.584,
  longitude: -48.505,
}

describe('itemDaVitrineDe', () => {
  it('aceita o corpo completo', () => {
    expect(itemDaVitrineDe(BRUTO)).toEqual(BRUTO)
  })

  it('campo obrigatorio ausente descarta o item', () => {
    expect(itemDaVitrineDe({ ...BRUTO, codigo: undefined })).toBeNull()
    expect(itemDaVitrineDe({ ...BRUTO, preco: null })).toBeNull()
  })

  it('meia coordenada zera o par, e foto vazia vira null', () => {
    const item = itemDaVitrineDe({ ...BRUTO, longitude: null, foto: '' })
    expect(item?.latitude).toBeNull()
    expect(item?.longitude).toBeNull()
    expect(item?.foto).toBeNull()
  })
})

describe('precoCurto', () => {
  it('milhoes com duas casas, milhares sem casa, e o meio-termo com uma', () => {
    expect(precoCurto(177976100)).toBe('R$ 1,77 mi')
    expect(precoCurto(485000000)).toBe('R$ 4,85 mi')
    expect(precoCurto(65030000)).toBe('R$ 650 mil')
    expect(precoCurto(650300)).toBe('R$ 6,5 mil')
    expect(precoCurto(90000)).toBe('R$ 900')
  })
})

describe('paginacao', () => {
  it('total de paginas nunca e zero', () => {
    expect(totalDePaginas(0, 12)).toBe(1)
    expect(totalDePaginas(25, 12)).toBe(3)
  })

  it('mostra a primeira, a ultima e as vizinhas da atual, com salto marcado', () => {
    expect(paginasVisiveis(1, 1)).toEqual([1])
    expect(paginasVisiveis(1, 30)).toEqual([1, 2, null, 30])
    expect(paginasVisiveis(15, 30)).toEqual([1, null, 14, 15, 16, null, 30])
    expect(paginasVisiveis(3, 4)).toEqual([1, 2, 3, 4])
  })
})

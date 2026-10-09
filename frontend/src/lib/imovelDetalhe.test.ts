import { describe, expect, it } from 'vitest'

import { imovelDetalheDe } from './imovelDetalhe'

const BRUTO = {
  id: 'i-1',
  codigo: 'IT-9821',
  titulo: 'Apartamento com vista',
  descricao: 'Sala ampla com varanda.',
  tipo: 'APARTAMENTO',
  operacao: 'VENDA',
  bairro: 'Centro',
  cidade: 'Florianópolis',
  uf: 'SC',
  areaUtilM2: 74,
  quartos: 2,
  suites: 1,
  banheiros: 2,
  vagas: 1,
  precoVenda: 58000000,
  precoAluguel: null,
  condominio: 65000,
  iptuMensal: null,
  caracteristicas: ['varanda', 'vista para o mar'],
  fotos: ['/portal/imoveis/i-1/fotos/f-1'],
  latitude: -27.584,
  longitude: -48.505,
}

describe('imovelDetalheDe', () => {
  it('aceita o corpo completo', () => {
    expect(imovelDetalheDe(BRUTO)).toEqual(BRUTO)
  })

  it('campo obrigatorio ausente descarta o detalhe inteiro', () => {
    expect(imovelDetalheDe({ ...BRUTO, descricao: undefined })).toBeNull()
  })

  it('nao e objeto vira null', () => {
    expect(imovelDetalheDe('x')).toBeNull()
    expect(imovelDetalheDe(null)).toBeNull()
    expect(imovelDetalheDe([])).toBeNull()
  })

  it('precos/condominio/iptu ausentes ou de tipo errado viram null, sem descartar o detalhe', () => {
    expect(imovelDetalheDe({ ...BRUTO, precoVenda: 'nao-e-numero' })?.precoVenda).toBeNull()
  })

  it('caracteristicas e fotos ausentes viram lista vazia', () => {
    const detalhe = imovelDetalheDe({ ...BRUTO, caracteristicas: undefined, fotos: undefined })
    expect(detalhe?.caracteristicas).toEqual([])
    expect(detalhe?.fotos).toEqual([])
  })

  it('sem codigo o detalhe e descartado, como qualquer campo obrigatorio', () => {
    expect(imovelDetalheDe({ ...BRUTO, codigo: '' })).toBeNull()
  })

  it('coordenada ausente, fora da faixa ou pela metade zera o par', () => {
    for (const parcial of [
      { latitude: null },
      { longitude: undefined },
      { latitude: 91 },
      { longitude: '-48.5' },
    ]) {
      const detalhe = imovelDetalheDe({ ...BRUTO, ...parcial })
      expect(detalhe?.latitude).toBeNull()
      expect(detalhe?.longitude).toBeNull()
    }
  })
})

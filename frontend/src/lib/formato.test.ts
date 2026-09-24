import { describe, expect, it } from 'vitest'

import { percentual, quantidadeLegivel } from './formato'

describe('percentual', () => {
  it('formata em pt-BR com uma casa', () => {
    expect(percentual(0.8375)).toBe('83,8%')
  })

  it('devolve travessao para nulo', () => {
    expect(percentual(null)).toBe('—')
  })

  it('formata zero como zero, e nao como travessao', () => {
    expect(percentual(0)).toBe('0,0%')
  })
})

describe('quantidadeLegivel', () => {
  it('diz que nao ha fonte quando a etapa e indisponivel', () => {
    expect(
      quantidadeLegivel({
        nome: 'Agendado',
        quantidade: null,
        disponivel: false,
        conversaoDaAnterior: null,
      }),
    ).toBe('sem fonte de dados')
  })

  it('mostra zero como zero quando a etapa e disponivel', () => {
    expect(
      quantidadeLegivel({
        nome: 'Novo',
        quantidade: 0,
        disponivel: true,
        conversaoDaAnterior: null,
      }),
    ).toBe('0')
  })
})

import { describe, expect, it } from 'vitest'

import { coorteIncompleta, percentual, quantidadeLegivel } from './formato'

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
    ).toBe('Ainda não medido')
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

describe('coorteIncompleta', () => {
  it('nulo nao e coorte incompleta', () => {
    expect(coorteIncompleta(null)).toBe(false)
  })

  it('100% exato nao e coorte incompleta', () => {
    expect(coorteIncompleta(1.0)).toBe(false)
  })

  it('um pouco acima de 100% ja e', () => {
    expect(coorteIncompleta(1.0001)).toBe(true)
  })

  it('4000% (o exemplo da card) e', () => {
    expect(coorteIncompleta(40.0)).toBe(true)
  })
})

import { describe, expect, it } from 'vitest'

import { digitosDe, mascarar, telefoneParaEnvio } from './telefone'

describe('telefone do chat (TEC-353, D2)', () => {
  it('digitosDe tira tudo o que nao e digito e corta em 11', () => {
    expect(digitosDe('(48) 99999-0021')).toBe('48999990021')
    expect(digitosDe('+55 48 99999-0021')).toBe('55489999900')
  })

  it.each([
    ['', ''],
    ['4', '(4'],
    ['48', '(48'],
    ['489', '(48) 9'],
    ['489999', '(48) 9999'],
    ['4899999', '(48) 9-9999'],
    ['4833330021', '(48) 3333-0021'],
    ['48999990021', '(48) 99999-0021'],
  ])('mascarar(%s) = %s', (digitos, mascara) => {
    expect(mascarar(digitos)).toBe(mascara)
  })

  it('cenario 1: "(48) 99999-0021" sai como "+55 48 99999-0021"', () => {
    expect(telefoneParaEnvio(digitosDe('(48) 99999-0021'))).toBe('+55 48 99999-0021')
  })

  it('fixo sai como "+55 48 3333-0021"', () => {
    expect(telefoneParaEnvio('4833330021')).toBe('+55 48 3333-0021')
  })

  it.each([
    ['cenario 2: incompleto', '9999002'],
    ['DDD fora de uso', '20999990021'],
    ['celular sem o 9', '48899990021'],
    ['fixo comecando por 6', '4863330021'],
    ['vazio', ''],
  ])('%s nao sai', (_caso, digitos) => {
    expect(telefoneParaEnvio(digitos)).toBeNull()
  })
})

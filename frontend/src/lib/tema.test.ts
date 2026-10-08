import { describe, expect, it } from 'vitest'

import { COOKIE_DO_TEMA, proximoTema, temaDoCookie } from './tema'

describe('temaDoCookie', () => {
  it('aceita so claro e escuro', () => {
    expect(temaDoCookie('claro')).toBe('claro')
    expect(temaDoCookie('escuro')).toBe('escuro')
  })

  it('valor desconhecido ou ausente e "siga o sistema"', () => {
    expect(temaDoCookie('roxo')).toBeUndefined()
    expect(temaDoCookie(undefined)).toBeUndefined()
  })
})

describe('proximoTema', () => {
  it('alterna o tema escolhido', () => {
    expect(proximoTema('escuro', false)).toBe('claro')
    expect(proximoTema('claro', true)).toBe('escuro')
  })

  it('sem escolha, parte do tema do sistema', () => {
    expect(proximoTema(undefined, true)).toBe('claro')
    expect(proximoTema(undefined, false)).toBe('escuro')
  })
})

it('o cookie tem nome proprio, separado da sessao', () => {
  expect(COOKIE_DO_TEMA).toBe('mobia_tema')
})

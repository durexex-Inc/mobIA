import { describe, expect, it } from 'vitest'

import { type Aparencia, lerAparencia, nomeExibido } from './aparencia'

const VALIDA: Aparencia = { nomeDoAssistente: 'Lia', corPrimaria: '#0A7F5A', posicaoDoBotao: 'ESQUERDA' }

describe('lerAparencia', () => {
  it('aceita a forma que a API devolve', () => {
    expect(lerAparencia(VALIDA)).toEqual(VALIDA)
    expect(lerAparencia({ ...VALIDA, nomeDoAssistente: null })?.nomeDoAssistente).toBeNull()
  })

  it.each([
    ['nulo', null],
    ['texto', 'x'],
    ['cor com alfa', { ...VALIDA, corPrimaria: '#0A7F5AFF' }],
    ['cor sem #', { ...VALIDA, corPrimaria: '0A7F5A' }],
    ['posicao desconhecida', { ...VALIDA, posicaoDoBotao: 'CIMA' }],
    ['posicao herdada', { ...VALIDA, posicaoDoBotao: 'constructor' }],
    ['nome que nao e texto', { ...VALIDA, nomeDoAssistente: 7 }],
  ])('recusa %s', (_, corpo) => {
    expect(lerAparencia(corpo)).toBeNull()
  })
})

describe('nomeExibido', () => {
  it('usa o nome configurado, ou "Assistente virtual" sem nome', () => {
    expect(nomeExibido(VALIDA)).toBe('Lia')
    expect(nomeExibido({ ...VALIDA, nomeDoAssistente: null })).toBe('Assistente virtual')
  })
})

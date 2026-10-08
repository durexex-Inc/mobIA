import { describe, expect, it } from 'vitest'

import { agenteDaRota, marcadoresNoTexto, nomeDoAgenteNaApi, rotaDoAgente } from '@/lib/prompts'

describe('marcadoresNoTexto', () => {
  it('lista cada marcador uma vez, na ordem em que aparece', () => {
    expect(marcadoresNoTexto('Voce e {assistente}. Tom {tom}. De novo {assistente}.')).toEqual([
      '{assistente}',
      '{tom}',
    ])
  })

  it('sem marcador, lista vazia; chave com espaco nao e marcador', () => {
    expect(marcadoresNoTexto('texto { solto } sem nada')).toEqual([])
  })
})

describe('agenteDaRota', () => {
  it('aceita os dois segmentos validos', () => {
    expect(agenteDaRota('agente')).toBe('agente')
    expect(agenteDaRota('investidor')).toBe('investidor')
  })

  it('recusa qualquer outro segmento (D2 do desenho)', () => {
    expect(agenteDaRota('AGENTE')).toBeNull()
    expect(agenteDaRota('qualificador')).toBeNull()
    expect(agenteDaRota('')).toBeNull()
  })
})

describe('nomeDoAgenteNaApi', () => {
  it('e o valor maiusculo que AgenteDoPrompt espera', () => {
    expect(nomeDoAgenteNaApi('agente')).toBe('AGENTE')
    expect(nomeDoAgenteNaApi('investidor')).toBe('INVESTIDOR')
  })
})

describe('rotaDoAgente', () => {
  it('e o inverso de nomeDoAgenteNaApi', () => {
    expect(rotaDoAgente('AGENTE')).toBe('agente')
    expect(rotaDoAgente('INVESTIDOR')).toBe('investidor')
  })
})

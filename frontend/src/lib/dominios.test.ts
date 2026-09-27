import { describe, expect, it } from 'vitest'

import { hostDoOrigin, lerDominios } from './dominios'

describe('lerDominios', () => {
  it('aceita host e host:porta', () => {
    expect(lerDominios(['imobiliariasol.com.br', 'localhost:5500'])).toEqual([
      'imobiliariasol.com.br',
      'localhost:5500',
    ])
  })

  it('descarta o que abriria uma diretiva nova na CSP, e o resto que nao e host', () => {
    expect(
      lerDominios([
        'imob.com.br; script-src *',
        'imob.com.br x.com',
        'https://imob.com.br',
        '*.imob.com.br',
        '*',
        "'self'",
        'Imob.com.br',
        5,
        null,
        'ok.com.br',
      ]),
    ).toEqual(['ok.com.br'])
  })

  it('devolve null quando o campo nao e lista', () => {
    expect(lerDominios(undefined)).toBeNull()
    expect(lerDominios('imob.com.br')).toBeNull()
  })
})

describe('hostDoOrigin', () => {
  it('devolve o host na forma dos dominios cadastrados', () => {
    expect(hostDoOrigin('https://Imobiliariasol.com.br')).toBe('imobiliariasol.com.br')
    expect(hostDoOrigin('https://imob.com.br:443')).toBe('imob.com.br')
    expect(hostDoOrigin('http://localhost:5500')).toBe('localhost:5500')
  })

  it('recusa o que nao e origem web', () => {
    expect(hostDoOrigin(null)).toBeNull()
    expect(hostDoOrigin('')).toBeNull()
    expect(hostDoOrigin('null')).toBeNull()
    expect(hostDoOrigin('file:///c:/x.html')).toBeNull()
  })
})

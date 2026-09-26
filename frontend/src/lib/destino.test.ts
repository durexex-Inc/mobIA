import { describe, expect, it } from 'vitest'

import { destinoSeguro, urlDoLogin } from './destino'

describe('destinoSeguro', () => {
  it('devolve o caminho interno com a busca', () => {
    expect(destinoSeguro('/leads?q=ana')).toBe('/leads?q=ana')
  })

  it('cai na pagina inicial sem destino', () => {
    expect(destinoSeguro(null)).toBe('/')
    expect(destinoSeguro('')).toBe('/')
  })

  // Cenario 3 do Gherkin: "Recusar destino externo apos o login". Uma forma de
  // ataque por caso, porque cada uma passa por uma checagem diferente -- e e
  // assim que se ve qual delas deixou de existir.
  it.each([
    ['URL absoluta', 'https://site-externo.com'],
    ['URL sem esquema', '//site-externo.com'],
    ['barra invertida que o navegador normaliza', '/\\site-externo.com'],
    ['barra invertida no meio', '/leads\\..\\..\\site-externo.com'],
    ['esquema javascript', 'javascript:alert(1)'],
    ['quebra de linha para injetar cabecalho', '/leads\r\nSet-Cookie: x=1'],
    ['caminho relativo', 'leads'],
  ])('recusa %s', (_nome, bruto) => {
    expect(destinoSeguro(bruto)).toBe('/')
  })

  it.each(['/login', '/login?etapa=mfa', '/login/entrar', '/bff/api/v1/metricas/funil'])(
    'recusa %s, que levaria a um laco ou a um JSON',
    (bruto) => {
      expect(destinoSeguro(bruto)).toBe('/')
    },
  )

  it('nao confunde prefixo com rota: `/loginx` e outra pagina', () => {
    expect(destinoSeguro('/loginx')).toBe('/loginx')
  })

  it('remonta o caminho normalizado, e nao copia a entrada', () => {
    expect(destinoSeguro('/a/../leads')).toBe('/leads')
  })
})

describe('urlDoLogin', () => {
  it('sem nada, e so a tela de login', () => {
    expect(urlDoLogin()).toBe('/login')
  })

  it('preserva o destino e o motivo', () => {
    expect(urlDoLogin({ returnTo: '/leads', erro: 'credencial' })).toBe(
      '/login?returnTo=%2Fleads&erro=credencial',
    )
  })

  it('filtra o destino antes de o carregar adiante', () => {
    expect(urlDoLogin({ returnTo: 'https://site-externo.com', etapa: 'mfa' })).toBe(
      '/login?etapa=mfa',
    )
  })
})

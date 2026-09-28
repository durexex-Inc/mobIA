import { describe, expect, it } from 'vitest'

import {
  filtrosDaUrl,
  fimDoDia,
  inicioDoDia,
  posicaoDaProxima,
  posicaoDaUrl,
  PRIMEIRA_PAGINA,
  urlDaLista,
} from './auditoria'

describe('filtrosDaUrl / urlDaLista', () => {
  it('ida e volta pela URL', () => {
    const filtros = { ator: 'u-1', acao: 'ACESSO_NEGADO', de: '2026-09-01', ate: '2026-09-30' }
    const url = urlDaLista({ filtros })
    const params = Object.fromEntries(new URL(url, 'http://x').searchParams)
    expect(filtrosDaUrl(params)).toEqual(filtros)
  })

  it('sem filtro nenhum, o endereco e so /admin/auditoria', () => {
    expect(urlDaLista({})).toBe('/admin/auditoria')
  })

  it('tipo desconhecido cai em "sem filtro"', () => {
    expect(filtrosDaUrl({ acao: 'APAGOU_TUDO' })).toEqual({
      ator: undefined,
      acao: undefined,
      de: undefined,
      ate: undefined,
    })
  })

  it('sem posicao explicita, o endereco nao leva cursor -- e assim que mudar um filtro volta a primeira pagina', () => {
    const url = urlDaLista({ filtros: { ator: 'u-1' } })
    expect(url).not.toContain('cursor')
  })
})

describe('posicaoDaUrl / posicaoDaProxima', () => {
  it('sem cursor, e a primeira pagina', () => {
    expect(posicaoDaUrl({})).toEqual(PRIMEIRA_PAGINA)
  })

  it('acumula sem pular: o cursor atual entra em anteriores', () => {
    const p1 = posicaoDaProxima(PRIMEIRA_PAGINA, 'c1')
    expect(p1).toEqual({ cursor: 'c1', anteriores: [] })
    const p2 = posicaoDaProxima(p1, 'c2')
    expect(p2).toEqual({ cursor: 'c2', anteriores: ['c1'] })
  })

  it('a URL preserva anteriores e cursor, na ordem', () => {
    const posicao = posicaoDaProxima(posicaoDaProxima(PRIMEIRA_PAGINA, 'c1'), 'c2')
    const url = urlDaLista({ posicao })
    const params = new URL(url, 'http://x').searchParams
    expect(params.get('cursor')).toBe('c2')
    expect(params.getAll('anterior')).toEqual(['c1'])
    expect(posicaoDaUrl(Object.fromEntries(params))).toEqual({ cursor: 'c2', anteriores: ['c1'] })
  })
})

describe('inicioDoDia / fimDoDia', () => {
  it('inicio do dia e meia-noite no fuso fixo', () => {
    expect(inicioDoDia('2026-09-01')).toBe('2026-09-01T00:00:00-03:00')
  })

  it('fim do dia e o inicio do dia SEGUINTE (limite exclusivo)', () => {
    expect(fimDoDia('2026-09-30')).toBe('2026-10-01T00:00:00-03:00')
  })

  it('vira o ano corretamente', () => {
    expect(fimDoDia('2026-12-31')).toBe('2027-01-01T00:00:00-03:00')
  })
})

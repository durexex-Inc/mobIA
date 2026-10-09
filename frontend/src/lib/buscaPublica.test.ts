import { describe, expect, it } from 'vitest'

import { filtrosDaUrl, OPERACAO_PADRAO, urlDaBusca } from './buscaPublica'

describe('filtrosDaUrl / urlDaBusca', () => {
  it('ida e volta pela URL', () => {
    const filtros = {
      operacao: 'ALUGUEL' as const,
      precoMinCentavos: 100000,
      precoMaxCentavos: 500000,
      tipo: 'APARTAMENTO' as const,
      quartosMin: 2,
      vagasMin: 1,
      regioes: ['Centro', 'Trindade'],
    }
    const url = urlDaBusca(filtros)
    const params = Object.fromEntries(new URL(url, 'http://x').searchParams)
    expect(filtrosDaUrl(params)).toEqual(filtros)
  })

  it('sem nenhum parametro, a operacao cai no padrao e o resto fica ausente (CA-01)', () => {
    expect(filtrosDaUrl({})).toEqual({
      operacao: OPERACAO_PADRAO,
      precoMinCentavos: undefined,
      precoMaxCentavos: undefined,
      tipo: undefined,
      quartosMin: undefined,
      vagasMin: undefined,
      regioes: [],
    })
  })

  it('operacao AMBOS (ou qualquer valor desconhecido) cai no padrao -- o portal nunca manda AMBOS', () => {
    expect(filtrosDaUrl({ operacao: 'AMBOS' }).operacao).toBe(OPERACAO_PADRAO)
    expect(filtrosDaUrl({ operacao: 'o-que-for' }).operacao).toBe(OPERACAO_PADRAO)
  })

  it('tipo desconhecido cai em "sem filtro"', () => {
    expect(filtrosDaUrl({ tipo: 'NAO-EXISTE' }).tipo).toBeUndefined()
  })

  it('preco em reais (o que o input manda) vira centavos', () => {
    expect(filtrosDaUrl({ precoMin: '1500.50' }).precoMinCentavos).toBe(150050)
  })

  it('regioes separadas por virgula, sem vazio', () => {
    expect(filtrosDaUrl({ regioes: 'Centro,  , Trindade ' }).regioes).toEqual(['Centro', 'Trindade'])
  })

  it('sem regiao nenhuma, a URL nao leva o parametro', () => {
    const url = urlDaBusca({ operacao: 'VENDA' })
    expect(url).not.toContain('regioes')
  })

  it('ordem e pagina vao e voltam pela URL', () => {
    const url = urlDaBusca({ operacao: 'VENDA', ordem: 'menor_preco', pagina: 3 })
    const filtros = filtrosDaUrl(Object.fromEntries(new URL(url, 'http://x').searchParams))
    expect(filtros.ordem).toBe('menor_preco')
    expect(filtros.pagina).toBe(3)
  })

  it('ordem padrao, ordem desconhecida e pagina 1 nao entram na URL', () => {
    expect(urlDaBusca({ operacao: 'VENDA', ordem: 'recentes', pagina: 1 })).toBe('/busca?operacao=VENDA')
    expect(filtrosDaUrl({ ordem: 'qualquer', pagina: '0' })).toMatchObject({ ordem: undefined, pagina: undefined })
  })
})

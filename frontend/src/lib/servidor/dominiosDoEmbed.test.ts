import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { dominiosDoEmbed, esquecerDominiosDoEmbed } from './dominiosDoEmbed'

const CORPO = {
  tenant: 'imobiliaria-x',
  nomeDoAssistente: null,
  corPrimaria: '#1D4ED8',
  posicaoDoBotao: 'DIREITA',
  dominios: ['imobiliariasol.com.br'],
}

function apiRespondendo(status: number, corpo: unknown = CORPO) {
  const api = vi.fn(async () => new Response(JSON.stringify(corpo), { status }))
  vi.stubGlobal('fetch', api)
  return api
}

describe('dominiosDoEmbed (TEC-345, D4)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    esquecerDominiosDoEmbed()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('pede a aparencia publica e devolve os dominios', async () => {
    const api = apiRespondendo(200)

    expect(await dominiosDoEmbed()).toEqual(['imobiliariasol.com.br'])
    expect(String((api.mock.calls[0] as unknown[])[0])).toBe('http://backend:8000/widget/aparencia')
  })

  it('guarda por 60 s, e depois pede de novo', async () => {
    const api = apiRespondendo(200)

    await dominiosDoEmbed()
    vi.advanceTimersByTime(59_000)
    await dominiosDoEmbed()
    expect(api).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(2_000)
    await dominiosDoEmbed()
    expect(api).toHaveBeenCalledTimes(2)
  })

  it('requisicoes simultaneas fazem uma chamada so', async () => {
    const api = apiRespondendo(200)

    await Promise.all([dominiosDoEmbed(), dominiosDoEmbed(), dominiosDoEmbed()])

    expect(api).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['status diferente de 200', () => apiRespondendo(503)],
    ['corpo sem dominios', () => apiRespondendo(200, { ...CORPO, dominios: undefined })],
    [
      'rede fora',
      () =>
        vi.stubGlobal(
          'fetch',
          vi.fn(async () => {
            throw new TypeError('fetch failed')
          }),
        ),
    ],
  ])('%s vira lista vazia, com o erro no log', async (_, preparar) => {
    const erro = vi.spyOn(console, 'error').mockImplementation(() => {})
    preparar()

    expect(await dominiosDoEmbed()).toEqual([])
    expect(erro).toHaveBeenCalledTimes(1)
  })

  it('a falha e lembrada por 5 s, e nao por 60', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const falha = apiRespondendo(503)

    await dominiosDoEmbed()
    await dominiosDoEmbed()
    expect(falha).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(6_000)
    const sucesso = apiRespondendo(200)
    expect(await dominiosDoEmbed()).toEqual(['imobiliariasol.com.br'])
    expect(sucesso).toHaveBeenCalledTimes(1)
  })
})

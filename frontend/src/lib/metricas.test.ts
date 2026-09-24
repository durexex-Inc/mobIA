import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buscarFunil, ErroDeMetricas } from './metricas'

const RESPOSTA = {
  etapas: [{ nome: 'Novo', quantidade: 320, disponivel: true, conversaoDaAnterior: null }],
  indicadores: { leadsNovos: 320 },
  indisponiveis: [],
}

function respostaOk() {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(RESPOSTA), { status: 200 }))
}

describe('buscarFunil', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ADMIN_TOKEN = 'segredo'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('manda o token no header e devolve o corpo', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    const funil = await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })

    expect(funil.etapas[0].quantidade).toBe(320)
    const [url, init] = fetchFalso.mock.calls[0]
    expect(String(url)).toContain('/api/v1/metricas/funil')
    expect(String(url)).toContain('de=2026-08-01')
    expect(init.headers['X-Admin-Token']).toBe('segredo')
    expect(init.next).toEqual({ revalidate: 60 })
  })

  it('omite da query o filtro que nao foi informado', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })

    expect(String(fetchFalso.mock.calls[0][0])).not.toContain('canal=')
  })

  it('manda o filtro informado, com o nome que o backend espera', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    await buscarFunil({
      de: '2026-08-01',
      ate: '2026-08-22',
      temperatura: 'QUENTE',
      corretorId: 'abc',
    })

    const url = String(fetchFalso.mock.calls[0][0])
    expect(url).toContain('temperatura=QUENTE')
    expect(url).toContain('corretorId=abc')
  })

  it('levanta ErroDeMetricas com o status quando o backend recusa', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 403 })))

    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })).rejects.toBeInstanceOf(
      ErroDeMetricas,
    )
    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })).rejects.toMatchObject({
      status: 403,
    })
  })

  it('no 422 carrega o detalhe do backend, que nomeia o filtro recusado', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "temperatura='MORNA' nao e um valor conhecido" }), {
          status: 422,
        }),
      ),
    )

    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })).rejects.toMatchObject({
      status: 422,
      message: expect.stringContaining('MORNA'),
    })
  })
})

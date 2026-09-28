import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buscarCusto } from './custo'
import { ErroDeMetricas } from './metricas'

const RESPOSTA = {
  custoTotalUsd: 0.84,
  custoPorConversaUsd: 0.084,
  custoPorLeadQualificadoUsd: 0.42,
  tokensPorModelo: {},
  conversas: 10,
  leadsQualificados: 2,
  mensagensSemPreco: 0,
  alvoPorLeadQualificadoUsd: 0.12,
  acimaDoAlvo: true,
  orcamento: null,
}

function respostaOk() {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(RESPOSTA), { status: 200 }))
}

describe('buscarCusto', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('manda o access token da sessao e devolve o corpo', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    const custo = await buscarCusto({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')

    expect(custo.custoTotalUsd).toBe(0.84)
    const [url, init] = fetchFalso.mock.calls[0]
    expect(String(url)).toContain('/api/v1/metricas/custo-ia')
    expect(String(url)).toContain('de=2026-08-01')
    expect(init.headers.Authorization).toBe('Bearer jwt')
  })

  it('sem cache -- nao manda `revalidate` nenhum', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    await buscarCusto({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')

    const [, init] = fetchFalso.mock.calls[0]
    expect(init.next).toBeUndefined()
    expect(init.cache).toBe('no-store')
  })

  it('omite da query o filtro que nao foi informado', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    await buscarCusto({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')

    expect(String(fetchFalso.mock.calls[0][0])).not.toContain('canal=')
  })

  it('manda o filtro informado', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    await buscarCusto(
      { de: '2026-08-01', ate: '2026-08-22', canal: 'web', temperatura: 'QUENTE' },
      'jwt',
    )

    const url = String(fetchFalso.mock.calls[0][0])
    expect(url).toContain('canal=web')
    expect(url).toContain('temperatura=QUENTE')
  })

  it('levanta ErroDeMetricas com o status quando o backend recusa', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 403 })))

    await expect(
      buscarCusto({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt'),
    ).rejects.toBeInstanceOf(ErroDeMetricas)
  })

  it('no 422, carrega o detalhe do backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "temperatura='MORNA' nao e um valor conhecido" }), {
          status: 422,
        }),
      ),
    )

    await expect(
      buscarCusto({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt'),
    ).rejects.toMatchObject({
      status: 422,
      message: expect.stringContaining('MORNA'),
    })
  })
})

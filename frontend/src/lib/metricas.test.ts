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

  it('NAO leva `X-Request-Id`, porque header entra na chave do Data Cache', async () => {
    // Acrescentado pela TEC-302. Um id por requisicao aqui daria uma entrada de
    // cache por acesso: taxa de acerto zero, e cada navegador com o painel
    // aberto voltando a ser uma chamada ao FastAPI por carregamento -- que e a
    // propriedade que a D9 da TEC-190 usou para justificar que o limite de 100
    // requisicoes por minuto por IP nao derruba o painel. Nada ficaria
    // vermelho sem esta asserção.
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })

    const [, init] = fetchFalso.mock.calls[0]
    expect(init.headers['X-Request-Id']).toBeUndefined()
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

  it('no 422 de validacao do FastAPI, `detail` e LISTA e ainda assim nomeia o campo', async () => {
    // O 422 que `montar_recorte` levanta tem `detail` string; o que o proprio
    // FastAPI levanta (UUID malformado no `corretorId`, data invalida no `de`)
    // tem `detail` como lista de objetos com `loc`. Sem tratar os dois, a tela
    // anuncia que ha um filtro errado e se recusa a dizer qual.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              { type: 'uuid_parsing', loc: ['query', 'corretorId'], msg: 'invalid UUID' },
            ],
          }),
          { status: 422 },
        ),
      ),
    )

    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' })).rejects.toMatchObject({
      status: 422,
      message: expect.stringContaining('corretorId'),
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

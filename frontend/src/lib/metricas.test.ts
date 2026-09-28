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
  })
  afterEach(() => vi.unstubAllGlobals())

  it('manda o access token da sessao e devolve o corpo', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    const funil = await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')

    expect(funil.etapas[0].quantidade).toBe(320)
    const [url, init] = fetchFalso.mock.calls[0]
    expect(String(url)).toContain('/api/v1/metricas/funil')
    expect(String(url)).toContain('de=2026-08-01')
    expect(init.headers.Authorization).toBe('Bearer jwt')
    expect(init.next).toEqual({ revalidate: 30 })
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

    await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')

    const [, init] = fetchFalso.mock.calls[0]
    expect(init.headers['X-Request-Id']).toBeUndefined()
    expect(init.next).toEqual({ revalidate: 30 })
  })

  it('omite da query o filtro que nao foi informado', async () => {
    const fetchFalso = respostaOk()
    vi.stubGlobal('fetch', fetchFalso)

    await buscarFunil({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')

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
    }, 'jwt')

    const url = String(fetchFalso.mock.calls[0][0])
    expect(url).toContain('temperatura=QUENTE')
    expect(url).toContain('corretorId=abc')
  })

  it('levanta ErroDeMetricas com o status quando o backend recusa', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 403 })))

    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')).rejects.toBeInstanceOf(
      ErroDeMetricas,
    )
    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')).rejects.toMatchObject({
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

    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')).rejects.toMatchObject({
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

    await expect(buscarFunil({ de: '2026-08-01', ate: '2026-08-22' }, 'jwt')).rejects.toMatchObject({
      status: 422,
      message: expect.stringContaining('MORNA'),
    })
  })
})

describe('o erro carrega o que a tela precisa (TEC-313)', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('guarda o X-Request-Id que veio na RESPOSTA', async () => {
    // O id nao e mandado por nos -- o caminho do funil e cacheado e um id por
    // requisicao zeraria a taxa de acerto. Este e o que o FastAPI GERA e
    // devolve (TEC-368), e e ele que identifica a linha do log. Ver a D3.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('{"detail":"quebrou"}', {
          status: 500,
          headers: { 'X-Request-Id': '7f3c-91ab' },
        }),
      ),
    )

    await expect(buscarFunil({ de: '2026-09-01', ate: '2026-09-30' }, 'jwt')).rejects.toMatchObject({
      status: 500,
      requestId: '7f3c-91ab',
    })
  })

  it('resposta sem o header deixa o id NULO, e nao inventa um', async () => {
    // Um 502 de proxy nunca chegou ao FastAPI. A tela omite o campo; um id
    // falso mandaria alguem procurar no log uma linha que nao existe.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('nao e json', { status: 502 })),
    )

    await expect(buscarFunil({ de: '2026-09-01', ate: '2026-09-30' }, 'jwt')).rejects.toMatchObject({
      requestId: null,
    })
  })

  it('extrai os campos do 422 de validacao do FastAPI', async () => {
    // A forma em LISTA, que o proprio FastAPI produz para UUID malformado ou
    // data invalida. E o `campos` que permite por a mensagem ao lado do campo.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: [{ loc: ['query', 'corretorId'], msg: 'uuid inválido' }] }),
          { status: 422 },
        ),
      ),
    )

    await expect(buscarFunil({ de: '2026-09-01', ate: '2026-09-30' }, 'jwt')).rejects.toMatchObject({
      status: 422,
      campos: ['corretorId'],
    })
  })

  it('422 com detail em prosa nao inventa campo', async () => {
    // Os 422 que `montar_recorte` levanta trazem `detail` como string ja
    // escrita para quem le -- nao ha campo a apontar, e o aviso fica acima do
    // formulario.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('{"detail":"o periodo nao pode passar de 90 dias"}', { status: 422 }),
      ),
    )

    await expect(buscarFunil({ de: '2026-09-01', ate: '2026-09-30' }, 'jwt')).rejects.toMatchObject({
      campos: [],
      message: 'o periodo nao pode passar de 90 dias',
    })
  })
})

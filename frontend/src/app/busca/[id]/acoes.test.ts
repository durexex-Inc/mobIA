import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { solicitarInteresseAction } from './acoes'

function responde(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status })
}

function formulario(campos: Record<string, string>) {
  const dados = new FormData()
  for (const [chave, valor] of Object.entries(campos)) {
    dados.set(chave, valor)
  }
  return dados
}

describe('solicitarInteresseAction', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('CA-01: manda telefone, nome e email, e devolve sucesso', async () => {
    const api = vi.fn().mockResolvedValue(responde({ recebido: true }, 201))
    vi.stubGlobal('fetch', api)

    const resultado = await solicitarInteresseAction(
      'i-1',
      { status: 'inicial' },
      formulario({ telefone: '11988887777', nome: 'Maria', email: 'maria@ex.com' }),
    )

    expect(resultado).toEqual({ status: 'sucesso' })
    const [url, opcoes] = api.mock.calls[0]
    expect(String(url)).toBe('http://backend:8000/portal/imoveis/i-1/interesse')
    expect(opcoes.method).toBe('POST')
    expect(JSON.parse(opcoes.body)).toEqual({
      telefone: '11988887777',
      nome: 'Maria',
      email: 'maria@ex.com',
    })
  })

  it('nome e email em branco nao entram no corpo', async () => {
    const api = vi.fn().mockResolvedValue(responde({ recebido: true }, 201))
    vi.stubGlobal('fetch', api)

    await solicitarInteresseAction('i-1', { status: 'inicial' }, formulario({ telefone: '11988887777' }))

    const [, opcoes] = api.mock.calls[0]
    expect(JSON.parse(opcoes.body)).toEqual({ telefone: '11988887777' })
  })

  it('id do imovel vai escapado na URL', async () => {
    const api = vi.fn().mockResolvedValue(responde({ recebido: true }, 201))
    vi.stubGlobal('fetch', api)

    await solicitarInteresseAction('a/b', { status: 'inicial' }, formulario({ telefone: '11988887777' }))

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/portal/imoveis/a%2Fb/interesse')
  })

  it('CA-02: telefone invalido devolve a mensagem do backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responde({ detail: 'telefone invalido' }, 422)),
    )

    const resultado = await solicitarInteresseAction(
      'i-1',
      { status: 'inicial' },
      formulario({ telefone: 'abc' }),
    )

    expect(resultado).toEqual({ status: 'erro', mensagem: 'telefone invalido' })
  })

  it('CA-03: imovel indisponivel devolve a mensagem do 404', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(responde({ detail: 'imovel nao disponivel' }, 404)),
    )

    const resultado = await solicitarInteresseAction(
      'i-1',
      { status: 'inicial' },
      formulario({ telefone: '11988887777' }),
    )

    expect(resultado).toEqual({ status: 'erro', mensagem: 'imovel nao disponivel' })
  })

  it('429 (rate limit) devolve a mensagem do backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        responde({ detail: 'muitos pedidos em pouco tempo -- tente de novo em instantes' }, 429),
      ),
    )

    const resultado = await solicitarInteresseAction(
      'i-1',
      { status: 'inicial' },
      formulario({ telefone: '11988887777' }),
    )

    expect(resultado.status).toBe('erro')
  })
})

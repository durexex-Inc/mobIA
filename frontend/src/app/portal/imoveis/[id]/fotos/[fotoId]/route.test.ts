import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GET } from './route'

const IMOVEL = '375dbdc1-0267-4d12-bc6f-b01eb04e57e6'
const FOTO = 'c8c48620-4bc8-4fe8-998c-d3b1c1b09e9b'
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

function contexto(id: string, fotoId: string) {
  return { params: Promise.resolve({ id, fotoId }) }
}

function requisicao() {
  return new Request(`https://painel.exemplo.com/portal/imoveis/${IMOVEL}/fotos/${FOTO}`)
}

let api: ReturnType<typeof vi.fn>

beforeEach(() => {
  process.env.MOBIA_API_BASE = 'http://backend:8000'
  api = vi.fn(async () => new Response(PNG, { status: 200, headers: { 'Content-Type': 'image/png' } }))
  vi.stubGlobal('fetch', api)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('GET /portal/imoveis/{id}/fotos/{fotoId} (TEC-403)', () => {
  it('repassa os bytes e o Content-Type da foto que o FastAPI serve', async () => {
    const resposta = await GET(requisicao(), contexto(IMOVEL, FOTO))

    expect(resposta.status).toBe(200)
    expect(resposta.headers.get('content-type')).toBe('image/png')
    expect(new Uint8Array(await resposta.arrayBuffer())).toEqual(PNG)
  })

  it('pede a rota publica do FastAPI, sem credencial nenhuma', async () => {
    await GET(requisicao(), contexto(IMOVEL, FOTO))

    const [url, opcoes] = api.mock.calls[0] as [URL, RequestInit]
    expect(String(url)).toBe(`http://backend:8000/portal/imoveis/${IMOVEL}/fotos/${FOTO}`)
    expect(opcoes.headers).not.toHaveProperty('Authorization')
  })

  it('404 do FastAPI (foto inexistente ou imovel indisponivel) continua 404', async () => {
    api.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'foto nao existe' }), { status: 404 }))

    const resposta = await GET(requisicao(), contexto(IMOVEL, FOTO))

    expect(resposta.status).toBe(404)
  })

  it.each([
    ['..', FOTO],
    [IMOVEL, '..'],
    ['nao-e-uuid', FOTO],
    [IMOVEL, `${FOTO}/../x`],
  ])('id fora da forma de UUID (%s, %s) e 404 sem chamar o FastAPI', async (id, fotoId) => {
    const resposta = await GET(requisicao(), contexto(id, fotoId))

    expect(resposta.status).toBe(404)
    expect(api).not.toHaveBeenCalled()
  })

  it('FastAPI fora do ar e 502, e nao uma excecao sem resposta', async () => {
    api.mockRejectedValueOnce(new TypeError('fetch failed'))
    vi.spyOn(console, 'error').mockImplementation(() => {})

    const resposta = await GET(requisicao(), contexto(IMOVEL, FOTO))

    expect(resposta.status).toBe(502)
  })
})

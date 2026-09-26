import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { conteudoDoArmazem, limparArmazem } from '../../../../test/armazem-em-memoria'
import { guardarDesafio, lerDesafio } from '@/lib/servidor/sessao'
import { POST } from './route'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const PAINEL = 'https://painel.exemplo.com'

function envio(
  campos: Record<string, string>,
  { desafio, origem = PAINEL }: { desafio?: string; origem?: string } = {},
) {
  const cabecalhos = new Headers({
    'content-type': 'application/x-www-form-urlencoded',
    origin: origem,
  })
  if (desafio) {
    cabecalhos.set('cookie', `mobia_mfa=${desafio}`)
  }
  return new NextRequest(new URL('/login/mfa', PAINEL), {
    method: 'POST',
    headers: cabecalhos,
    body: new URLSearchParams(campos).toString(),
  })
}

function apiRespondendo(corpo: unknown, status = 200) {
  const api = vi.fn().mockResolvedValue(new Response(JSON.stringify(corpo), { status }))
  vi.stubGlobal('fetch', api)
  return api
}

describe('POST /login/mfa', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ORIGEM_DO_PAINEL = PAINEL
    limparArmazem()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.MOBIA_ORIGEM_DO_PAINEL
  })

  it('codigo certo troca o desafio guardado pela sessao, e vai ao destino', async () => {
    const id = await guardarDesafio('jwt-do-desafio')
    const api = apiRespondendo({ access: 'jwt-de-acesso', refresh: 'refresh-opaco' })

    const resposta = await POST(envio({ codigo: ' 123456 ', returnTo: '/leads' }, { desafio: id }))

    expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({
      desafio: 'jwt-do-desafio',
      codigo: '123456',
    })
    expect(resposta.status).toBe(303)
    expect(resposta.headers.get('location')).toBe(`${PAINEL}/leads`)

    const cookies = resposta.headers.getSetCookie()
    expect(cookies.find((c) => c.startsWith('mobia_sessao='))).toContain('HttpOnly')
    // O cookie do desafio e apagado, e o desafio sai do Redis.
    expect(cookies.find((c) => c.startsWith('mobia_mfa='))).toContain('Max-Age=0')
    expect(await lerDesafio(id)).toBeNull()
    expect(JSON.stringify(cookies)).not.toContain('jwt-de-acesso')
  })

  it('codigo errado volta a etapa do codigo e NAO consome o desafio', async () => {
    const id = await guardarDesafio('jwt-do-desafio')
    apiRespondendo({ detail: 'credencial_invalida' }, 401)

    const resposta = await POST(envio({ codigo: '000000', returnTo: '/leads' }, { desafio: id }))

    expect(resposta.headers.get('location')).toBe(
      `${PAINEL}/login?returnTo=%2Fleads&etapa=mfa&erro=codigo`,
    )
    expect(await lerDesafio(id)).toBe('jwt-do-desafio')
    expect(resposta.headers.getSetCookie()).toEqual([])
  })

  it('sem desafio guardado, volta a senha com `erro=expirado`', async () => {
    const api = apiRespondendo({})

    const resposta = await POST(envio({ codigo: '123456' }, { desafio: 'b'.repeat(43) }))

    expect(api).not.toHaveBeenCalled()
    expect(resposta.headers.get('location')).toBe(`${PAINEL}/login?erro=expirado`)
  })

  it('sem o cookie do desafio, tambem', async () => {
    const resposta = await POST(envio({ codigo: '123456' }))

    expect(resposta.headers.get('location')).toBe(`${PAINEL}/login?erro=expirado`)
  })

  it('POST de outra origem nao chega ao FastAPI', async () => {
    const id = await guardarDesafio('jwt-do-desafio')
    const api = apiRespondendo({ access: 'jwt', refresh: 'r' })

    await POST(envio({ codigo: '123456' }, { desafio: id, origem: 'https://site-externo.com' }))

    expect(api).not.toHaveBeenCalled()
    expect(conteudoDoArmazem()).toHaveLength(1)
  })

  it('destino externo manda a pagina inicial', async () => {
    const id = await guardarDesafio('jwt-do-desafio')
    apiRespondendo({ access: 'jwt', refresh: 'r' })

    const resposta = await POST(
      envio({ codigo: '123456', returnTo: '//site-externo.com' }, { desafio: id }),
    )

    expect(resposta.headers.get('location')).toBe(`${PAINEL}/`)
  })
})

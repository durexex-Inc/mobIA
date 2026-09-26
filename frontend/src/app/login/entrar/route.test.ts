import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { conteudoDoArmazem, limparArmazem } from '../../../../test/armazem-em-memoria'
import { POST } from './route'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const PAINEL = 'https://painel.exemplo.com'

function envio(
  campos: Record<string, string>,
  { origem = PAINEL }: { origem?: string | null } = {},
) {
  const cabecalhos = new Headers({ 'content-type': 'application/x-www-form-urlencoded' })
  if (origem) {
    cabecalhos.set('origin', origem)
  }
  return new NextRequest(new URL('/login/entrar', PAINEL), {
    method: 'POST',
    headers: cabecalhos,
    body: new URLSearchParams(campos).toString(),
  })
}

function apiRespondendo(corpo: unknown, status = 200) {
  const api = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(corpo), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', api)
  return api
}

const CREDENCIAIS = { email: 'anelise@x.com', senha: 'senha-certa', returnTo: '/leads?q=ana' }

describe('POST /login/entrar', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    process.env.MOBIA_ORIGEM_DO_PAINEL = PAINEL
    limparArmazem()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.MOBIA_ORIGEM_DO_PAINEL
  })

  describe('cenario: voltar a pagina pretendida apos autenticar', () => {
    it('senha certa sem MFA vai ao destino com 303', async () => {
      apiRespondendo({ access: 'jwt-de-acesso', refresh: 'refresh-opaco' })

      const resposta = await POST(envio(CREDENCIAIS))

      expect(resposta.status).toBe(303)
      expect(resposta.headers.get('location')).toBe(`${PAINEL}/leads?q=ana`)
    })

    it('repassa e-mail e senha ao FastAPI, sem credencial de servidor', async () => {
      const api = apiRespondendo({ access: 'jwt', refresh: 'r' })

      await POST(envio(CREDENCIAIS))

      const [url, init] = api.mock.calls[0]
      expect(String(url)).toBe('http://backend:8000/api/v1/auth/login')
      expect(init.method).toBe('POST')
      expect(JSON.parse(init.body)).toEqual({ email: 'anelise@x.com', senha: 'senha-certa' })
      expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    })
  })

  describe('cenario: nenhum token de API chega ao navegador', () => {
    it('o unico cookie e o id opaco, HttpOnly, Secure e SameSite=Lax', async () => {
      apiRespondendo({ access: 'jwt-de-acesso', refresh: 'refresh-opaco' })

      const resposta = await POST(envio(CREDENCIAIS))

      const cookies = resposta.headers.getSetCookie()
      expect(cookies).toHaveLength(1)
      const [cookie] = cookies
      expect(cookie).toMatch(/^mobia_sessao=[A-Za-z0-9_-]{43};/)
      expect(cookie).toContain('HttpOnly')
      expect(cookie).toContain('Secure')
      expect(cookie.toLowerCase()).toContain('samesite=lax')
      expect(cookie).toContain('Max-Age=604800')
    })

    it('nem o access nem o refresh aparecem em cabecalho ou corpo da resposta', async () => {
      apiRespondendo({ access: 'jwt-de-acesso', refresh: 'refresh-opaco' })

      const resposta = await POST(envio(CREDENCIAIS))

      const tudo = JSON.stringify([...resposta.headers]) + (await resposta.text())
      expect(tudo).not.toContain('jwt-de-acesso')
      expect(tudo).not.toContain('refresh-opaco')
    })

    it('os tokens ficam no Redis', async () => {
      apiRespondendo({ access: 'jwt-de-acesso', refresh: 'refresh-opaco' })

      await POST(envio(CREDENCIAIS))

      const [gravado] = conteudoDoArmazem()
      expect(JSON.parse(gravado.valor)).toMatchObject({
        acesso: 'jwt-de-acesso',
        refresh: 'refresh-opaco',
      })
    })
  })

  describe('cenario: recusar destino externo apos o login', () => {
    it('manda a pagina inicial, e nao ao endereco externo', async () => {
      apiRespondendo({ access: 'jwt', refresh: 'r' })

      const resposta = await POST(envio({ ...CREDENCIAIS, returnTo: 'https://site-externo.com' }))

      expect(resposta.headers.get('location')).toBe(`${PAINEL}/`)
    })
  })

  describe('cenario: bloquear administrador sem segundo fator', () => {
    it('o 403 do FastAPI volta ao login com o motivo, e sem sessao', async () => {
      apiRespondendo({ detail: 'administradores precisam de MFA habilitado' }, 403)

      const resposta = await POST(envio(CREDENCIAIS))

      expect(resposta.headers.get('location')).toBe(
        `${PAINEL}/login?returnTo=%2Fleads%3Fq%3Dana&erro=mfa_obrigatorio`,
      )
      expect(resposta.headers.getSetCookie()).toEqual([])
      expect(conteudoDoArmazem()).toEqual([])
    })
  })

  describe('ADMIN com MFA', () => {
    it('o desafio fica no servidor e o navegador vai a etapa do codigo', async () => {
      apiRespondendo({ mfa_requerido: true, desafio: 'jwt-do-desafio' })

      const resposta = await POST(envio(CREDENCIAIS))

      expect(resposta.headers.get('location')).toBe(
        `${PAINEL}/login?returnTo=%2Fleads%3Fq%3Dana&etapa=mfa`,
      )
      const [cookie] = resposta.headers.getSetCookie()
      expect(cookie).toMatch(/^mobia_mfa=[A-Za-z0-9_-]{43};/)
      expect(cookie).toContain('Path=/login')
      expect(cookie).toContain('HttpOnly')
      expect(cookie).not.toContain('jwt-do-desafio')
      expect(conteudoDoArmazem()[0].valor).toBe('jwt-do-desafio')
    })
  })

  describe('recusas', () => {
    it.each([
      [401, 'credencial'],
      [422, 'credencial'],
      [429, 'muitas_tentativas'],
      [500, 'indisponivel'],
    ])('status %i do FastAPI vira `erro=%s`', async (status, motivo) => {
      apiRespondendo({ detail: 'x' }, status)

      const resposta = await POST(envio(CREDENCIAIS))

      expect(resposta.headers.get('location')).toContain(`erro=${motivo}`)
      expect(resposta.headers.getSetCookie()).toEqual([])
    })

    it('API fora do ar vira `erro=indisponivel`, sem detalhe da excecao', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED 10.0.0.5')))

      const resposta = await POST(envio(CREDENCIAIS))

      expect(resposta.headers.get('location')).toContain('erro=indisponivel')
      expect(resposta.headers.get('location')).not.toContain('10.0.0.5')
    })

    it('resposta 200 sem os tokens vira `erro=indisponivel`, e nao sessao vazia', async () => {
      apiRespondendo({ outra: 'coisa' })

      const resposta = await POST(envio(CREDENCIAIS))

      expect(resposta.headers.get('location')).toContain('erro=indisponivel')
      expect(conteudoDoArmazem()).toEqual([])
    })
  })

  describe('CSRF de login', () => {
    it.each([
      ['de outra origem', 'https://site-externo.com'],
      ['sem Origin', null],
    ])('POST %s nao chega ao FastAPI', async (_nome, origem) => {
      const api = apiRespondendo({ access: 'jwt', refresh: 'r' })

      const resposta = await POST(envio(CREDENCIAIS, { origem }))

      expect(api).not.toHaveBeenCalled()
      expect(resposta.status).toBe(303)
      expect(resposta.headers.get('location')).toBe(
        `${PAINEL}/login?returnTo=%2Fleads%3Fq%3Dana`,
      )
      expect(resposta.headers.getSetCookie()).toEqual([])
    })
  })
})

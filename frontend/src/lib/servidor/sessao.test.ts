import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  armazemEmMemoria,
  conteudoDoArmazem,
  limparArmazem,
} from '../../../test/armazem-em-memoria'
import { tokenQueExpiraEm } from '../../../test/token'
import {
  apagarDesafio,
  apagarSessao,
  criarSessao,
  expiracaoDoAcesso,
  obterSessaoValida,
  RenovacaoIndisponivel,
  guardarDesafio,
  lerDesafio,
  lerSessao,
  opcoesDoCookie,
  SEGUNDOS_DA_SESSAO,
  SEGUNDOS_DO_DESAFIO,
} from './sessao'

vi.mock('@/lib/servidor/armazem', async () =>
  (await import('../../../test/armazem-em-memoria')).moduloDeArmazem,
)

const TOKENS = { acesso: 'jwt-de-acesso', refresh: 'refresh-opaco' }

describe('sessao', () => {
  beforeEach(() => limparArmazem())

  it('guarda os tokens e os devolve pelo id', async () => {
    const id = await criarSessao(TOKENS)

    expect(await lerSessao(id)).toMatchObject(TOKENS)
  })

  it('o id e opaco e NAO e a chave do Redis', async () => {
    // A chave e o digest do id: um dump do Redis nao entrega sessao a ninguem.
    const id = await criarSessao(TOKENS)
    const [gravado] = conteudoDoArmazem()

    expect(id).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(gravado.chave).not.toContain(id)
    expect(gravado.chave).toMatch(/^mobia:painel:sessao:[0-9a-f]{64}$/)
  })

  it('vive o mesmo que o refresh token, sete dias', async () => {
    await criarSessao(TOKENS)

    expect(conteudoDoArmazem()[0].segundos).toBe(SEGUNDOS_DA_SESSAO)
    expect(SEGUNDOS_DA_SESSAO).toBe(604800)
  })

  it('duas sessoes nunca recebem o mesmo id', async () => {
    expect(await criarSessao(TOKENS)).not.toBe(await criarSessao(TOKENS))
  })

  it.each([
    ['ausente', undefined],
    ['vazio', ''],
    ['com forma errada', 'curto'],
    ['bem formado mas desconhecido', 'a'.repeat(43)],
  ])('id %s nao tem sessao', async (_nome, id) => {
    expect(await lerSessao(id)).toBeNull()
  })

  it('registro malformado vale como ausente, e nao como erro', async () => {
    const id = await criarSessao(TOKENS)
    const [{ chave }] = conteudoDoArmazem()
    const { armazemEmMemoria } = await import('../../../test/armazem-em-memoria')
    await armazemEmMemoria.gravar(chave, '{nao e json', 60)

    expect(await lerSessao(id)).toBeNull()
  })

  it('apagar a sessao a torna ilegivel', async () => {
    const id = await criarSessao(TOKENS)
    await apagarSessao(id)

    expect(await lerSessao(id)).toBeNull()
  })
})

describe('desafio de MFA', () => {
  beforeEach(() => limparArmazem())

  it('fica no servidor por cinco minutos, sob um id proprio', async () => {
    const id = await guardarDesafio('jwt-do-desafio')

    expect(await lerDesafio(id)).toBe('jwt-do-desafio')
    expect(conteudoDoArmazem()[0].segundos).toBe(SEGUNDOS_DO_DESAFIO)
    expect(conteudoDoArmazem()[0].chave).toMatch(/^mobia:painel:desafio:/)
  })

  it('ler nao consome: quem errou o codigo tenta de novo', async () => {
    const id = await guardarDesafio('jwt-do-desafio')
    await lerDesafio(id)

    expect(await lerDesafio(id)).toBe('jwt-do-desafio')
  })

  it('apagado, some', async () => {
    const id = await guardarDesafio('jwt-do-desafio')
    await apagarDesafio(id)

    expect(await lerDesafio(id)).toBeNull()
  })

  it('o id de sessao nao le desafio, e vice-versa', async () => {
    const idDaSessao = await criarSessao(TOKENS)
    const idDoDesafio = await guardarDesafio('jwt-do-desafio')

    expect(await lerDesafio(idDaSessao)).toBeNull()
    expect(await lerSessao(idDoDesafio)).toBeNull()
  })
})

describe('opcoesDoCookie', () => {
  it('e o que a card pede: HttpOnly, Secure e SameSite=Lax', () => {
    expect(opcoesDoCookie(60)).toEqual({
      httpOnly: true,
      secure: true,
      sameSite: 'lax',
      path: '/',
      maxAge: 60,
    })
  })
})

/**
 * A renovacao da TEC-310. `fetch` dublado responde pelo `/auth/refresh`; cada
 * teste escolhe quanto falta para o access vencer.
 */
describe('obterSessaoValida (TEC-310)', () => {
  const NOVO = { access: tokenQueExpiraEm(3600, 'novo'), refresh: 'refresh-novo' }

  function refreshRespondendo(corpo: unknown, status = 200) {
    const api = vi.fn<(url: URL | string, init: RequestInit) => Promise<Response>>(
      async () => new Response(JSON.stringify(corpo), { status }),
    )
    vi.stubGlobal('fetch', api)
    return api
  }

  function chaveDaSessao(): string {
    return conteudoDoArmazem().find((item) => item.chave.startsWith('mobia:painel:sessao:'))!.chave
  }

  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
    limparArmazem()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('le a claim `exp` do access, e devolve `null` quando nao ha', () => {
    const token = tokenQueExpiraEm(60)
    expect(expiracaoDoAcesso(token)).toBeGreaterThan(Date.now())
    expect(expiracaoDoAcesso('nao-e-jwt')).toBeNull()
  })

  it('access com mais de 5 minutos pela frente: nada e renovado', async () => {
    const api = refreshRespondendo(NOVO)
    const id = await criarSessao({ acesso: tokenQueExpiraEm(600), refresh: 'r1' })

    const sessao = await obterSessaoValida(id)

    expect(sessao?.refresh).toBe('r1')
    expect(api).not.toHaveBeenCalled()
  })

  describe('cenario: renovar o acesso expirado sem pedir login', () => {
    it.each([
      ['a menos de 5 minutos do fim', 240],
      ['ja vencido', -60],
    ])('access %s: troca o refresh pelo par novo e grava', async (_nome, segundos) => {
      const api = refreshRespondendo(NOVO)
      const id = await criarSessao({ acesso: tokenQueExpiraEm(segundos), refresh: 'r1' })

      const sessao = await obterSessaoValida(id)

      expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/api/v1/auth/refresh')
      expect(JSON.parse(String(api.mock.calls[0][1].body))).toEqual({ refresh: 'r1' })
      expect(sessao).toMatchObject({ acesso: NOVO.access, refresh: 'refresh-novo' })
      expect(await lerSessao(id)).toMatchObject({ acesso: NOVO.access, refresh: 'refresh-novo' })
    })

    it('a renovacao conserva a validade desde o login, e nao estende (D4)', async () => {
      refreshRespondendo(NOVO)
      const id = await criarSessao({ acesso: tokenQueExpiraEm(60), refresh: 'r1' })
      // Simula uma sessao criada ha 6 dias: sobra 1 dia.
      const registro = JSON.parse(
        conteudoDoArmazem().find((i) => i.chave === chaveDaSessao())!.valor,
      )
      registro.criadaEm = new Date(Date.now() - 6 * 86400_000).toISOString()
      await armazemEmMemoria.gravar(chaveDaSessao(), JSON.stringify(registro), 86400)

      await obterSessaoValida(id)

      const segundos = conteudoDoArmazem().find((i) => i.chave === chaveDaSessao())!.segundos
      expect(segundos).toBeGreaterThan(86400 - 5)
      expect(segundos).toBeLessThanOrEqual(86400)
    })

    it('solta o lock depois de renovar', async () => {
      refreshRespondendo(NOVO)
      const id = await criarSessao({ acesso: tokenQueExpiraEm(60), refresh: 'r1' })

      await obterSessaoValida(id)

      expect(conteudoDoArmazem().some((i) => i.chave.startsWith('mobia:painel:renovando:'))).toBe(
        false,
      )
    })

    it('com o lock tomado por outra requisicao, espera o par novo e NAO renova de novo', async () => {
      // O motivo do lock (D2): mandar o mesmo refresh duas vezes seria lido
      // como roubo pelo FastAPI, e derrubaria a sessao inteira.
      const api = refreshRespondendo(NOVO)
      const id = await criarSessao({ acesso: tokenQueExpiraEm(60), refresh: 'r1' })
      const chave = chaveDaSessao()
      await armazemEmMemoria.gravar(chave.replace(':sessao:', ':renovando:'), '1', 10)
      setTimeout(() => {
        const atual = JSON.parse(conteudoDoArmazem().find((i) => i.chave === chave)!.valor)
        void armazemEmMemoria.gravar(
          chave,
          JSON.stringify({ ...atual, acesso: NOVO.access, refresh: 'refresh-novo' }),
          60,
        )
      }, 200)

      const sessao = await obterSessaoValida(id)

      expect(api).not.toHaveBeenCalled()
      expect(sessao?.refresh).toBe('refresh-novo')
    })
  })

  describe('cenario: encerrar a sessao quando a renovacao falha', () => {
    it('401 do refresh apaga a sessao e devolve `null`', async () => {
      refreshRespondendo({ detail: 'credencial_invalida' }, 401)
      const id = await criarSessao({ acesso: tokenQueExpiraEm(60), refresh: 'revogado' })

      expect(await obterSessaoValida(id)).toBeNull()
      expect(await lerSessao(id)).toBeNull()
    })
  })

  describe('FastAPI fora do ar nao e sessao invalida (D3)', () => {
    it('com o access ainda valendo, segue com ele e nao apaga nada', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')))
      const acesso = tokenQueExpiraEm(120)
      const id = await criarSessao({ acesso, refresh: 'r1' })

      expect((await obterSessaoValida(id))?.acesso).toBe(acesso)
      expect(await lerSessao(id)).not.toBeNull()
    })

    it('com o access ja vencido, `RenovacaoIndisponivel` -- e a sessao continua la', async () => {
      refreshRespondendo({ detail: 'erro' }, 503)
      const id = await criarSessao({ acesso: tokenQueExpiraEm(-10), refresh: 'r1' })

      await expect(obterSessaoValida(id)).rejects.toBeInstanceOf(RenovacaoIndisponivel)
      expect(await lerSessao(id)).not.toBeNull()
    })
  })
})

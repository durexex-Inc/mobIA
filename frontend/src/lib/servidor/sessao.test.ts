import { beforeEach, describe, expect, it, vi } from 'vitest'

import { conteudoDoArmazem, limparArmazem } from '../../../test/armazem-em-memoria'
import {
  apagarDesafio,
  apagarSessao,
  criarSessao,
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

import 'server-only'

import { createHash, randomBytes } from 'node:crypto'

import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

import { urlDoLogin } from '@/lib/destino'
import { armazem } from '@/lib/servidor/armazem'

/**
 * A sessao do painel (TEC-309, D2 e D3).
 *
 * O navegador recebe um id opaco num cookie `HttpOnly`; os tokens que o
 * FastAPI emitiu ficam no Redis, sob o SHA-256 desse id. E isso que faz valer
 * o cenario 2 do Gherkin da card: nenhum access token, refresh token ou
 * desafio de MFA chega ao navegador, nem em cookie legivel nem em cookie
 * nenhum.
 */

export const COOKIE_DA_SESSAO = 'mobia_sessao'
export const COOKIE_DO_DESAFIO = 'mobia_mfa'

/** A vida do refresh token (RNF-11). Renovar o access com ele e a TEC-310. */
export const SEGUNDOS_DA_SESSAO = 7 * 24 * 60 * 60

/** A vida do desafio de MFA no backend (`MINUTOS_DO_DESAFIO`, em `auth.py`). */
export const SEGUNDOS_DO_DESAFIO = 5 * 60

/** O que a sessao guarda. So os tokens: papel e permissoes saem de `/auth/me`. */
export type Sessao = {
  acesso: string
  refresh: string
  criadaEm: string
}

// 32 bytes em base64url sem preenchimento sao exatamente 43 caracteres.
const FORMA_DO_ID = /^[A-Za-z0-9_-]{43}$/

function novoId(): string {
  return randomBytes(32).toString('base64url')
}

/**
 * A chave no Redis e o digest do id, e nao o id.
 *
 * Um dump do Redis entao nao entrega sessao a ninguem -- e o mesmo argumento
 * de `SessaoDeRefresh.digest` no backend. SHA-256 simples, e nao um hash lento:
 * o id ja tem 256 bits de entropia, e nao ha dicionario que o ataque.
 */
function chave(tipo: 'sessao' | 'desafio', id: string): string {
  return `mobia:painel:${tipo}:${createHash('sha256').update(id).digest('hex')}`
}

/**
 * O id, se tiver a forma de um id que nos emitimos.
 *
 * Um cookie e entrada do navegador. Conferir a forma antes de ir ao Redis
 * poupa a ida quando o valor e lixo -- e impede que um valor gigante vire
 * trabalho de hash e uma chave estranha no log de quem inspeciona o Redis.
 */
function idValido(id: string | null | undefined): id is string {
  return typeof id === 'string' && FORMA_DO_ID.test(id)
}

export async function criarSessao(tokens: { acesso: string; refresh: string }): Promise<string> {
  const id = novoId()
  const sessao: Sessao = { ...tokens, criadaEm: new Date().toISOString() }
  await (await armazem()).gravar(chave('sessao', id), JSON.stringify(sessao), SEGUNDOS_DA_SESSAO)
  return id
}

/**
 * A sessao deste id, ou `null`.
 *
 * **Registro malformado vale como ausente**, e nao como erro: o desfecho de
 * "nao consegui ler a sessao" tem de ser "entre de novo", nunca uma tela de
 * erro que a pessoa nao tem como resolver.
 */
export async function lerSessao(id: string | null | undefined): Promise<Sessao | null> {
  if (!idValido(id)) {
    return null
  }
  const bruto = await (await armazem()).obter(chave('sessao', id))
  if (!bruto) {
    return null
  }
  try {
    const sessao = JSON.parse(bruto) as Partial<Sessao>
    if (typeof sessao.acesso === 'string' && typeof sessao.refresh === 'string') {
      return { acesso: sessao.acesso, refresh: sessao.refresh, criadaEm: String(sessao.criadaEm) }
    }
  } catch {
    // cai no `null` abaixo
  }
  return null
}

export async function apagarSessao(id: string | null | undefined): Promise<void> {
  if (idValido(id)) {
    await (await armazem()).apagar(chave('sessao', id))
  }
}

export async function guardarDesafio(desafio: string): Promise<string> {
  const id = novoId()
  await (await armazem()).gravar(chave('desafio', id), desafio, SEGUNDOS_DO_DESAFIO)
  return id
}

export async function lerDesafio(id: string | null | undefined): Promise<string | null> {
  return idValido(id) ? (await armazem()).obter(chave('desafio', id)) : null
}

export async function apagarDesafio(id: string | null | undefined): Promise<void> {
  if (idValido(id)) {
    await (await armazem()).apagar(chave('desafio', id))
  }
}

/**
 * A sessao de quem pediu a pagina, ou o redirecionamento ao login (D5).
 *
 * **E a guarda de verdade.** O `proxy.ts` so confere que o cookie EXISTE, e
 * qualquer valor passa por ele; e aqui que o valor e procurado no Redis. Uma
 * pagina que mostre dado de lead tem de chamar esta funcao antes de buscar
 * qualquer coisa.
 *
 * `returnTo` e para onde voltar depois do login -- a propria pagina, com os
 * filtros dela.
 */
export async function exigirSessao(returnTo: string): Promise<Sessao> {
  const sessao = await lerSessao((await cookies()).get(COOKIE_DA_SESSAO)?.value)
  if (!sessao) {
    redirect(urlDoLogin({ returnTo }))
  }
  return sessao
}

/**
 * As opcoes dos dois cookies, que so diferem na vida e no caminho.
 *
 * `secure` e SEMPRE verdadeiro, inclusive em desenvolvimento: navegador moderno
 * aceita cookie `Secure` em `http://localhost`, e um `secure` condicionado ao
 * ambiente e exatamente o tipo de linha que alguem liga em producao por engano.
 * `SameSite=Lax` e o que a card pede: manda o cookie na navegacao que chega de
 * link externo, e nao em POST vindo de outra origem.
 */
export function opcoesDoCookie(segundos: number, caminho = '/') {
  return {
    httpOnly: true,
    secure: true,
    sameSite: 'lax' as const,
    path: caminho,
    maxAge: segundos,
  }
}

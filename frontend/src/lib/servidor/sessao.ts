import 'server-only'

import { createHash, randomBytes } from 'node:crypto'

import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { cache } from 'react'

import { urlDoLogin } from '@/lib/destino'
import { MINUTOS_OCIOSO_NO_SERVIDOR } from '@/lib/inatividade'
import { chamarApi } from '@/lib/servidor/api'
import { armazem } from '@/lib/servidor/armazem'
import { tokensDe } from '@/lib/servidor/login'

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

/**
 * A vida da sessao: 7 dias contados do LOGIN, que e a do refresh token
 * (RNF-11). Renovar o access nao estende -- ver a D4 do desenho da TEC-310.
 */
export const SEGUNDOS_DA_SESSAO = 7 * 24 * 60 * 60

/** Quanto antes de o access expirar a renovacao acontece (TEC-310, a regra da card). */
export const MARGEM_DE_RENOVACAO_SEGUNDOS = 5 * 60

// O lock da renovacao (D2). Dez segundos cobrem com folga uma ida ao
// `/auth/refresh`; se o processo morrer no meio, o lock expira sozinho e a
// sessao nao fica travada.
const SEGUNDOS_DO_LOCK = 10
// Quanto quem NAO pegou o lock espera pelo par novo, e de quanto em quanto
// tempo olha.
const ESPERA_PELO_LOCK_MS = 3000
const INTERVALO_DA_ESPERA_MS = 150

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
function chave(tipo: 'sessao' | 'desafio' | 'renovando' | 'atividade', id: string): string {
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
  const loja = await armazem()
  await loja.gravar(chave('sessao', id), JSON.stringify(sessao), SEGUNDOS_DA_SESSAO)
  await marcarAtividade(id)
  return id
}

/**
 * A sessao esteve em uso agora (TEC-311, D3).
 *
 * **Chave propria, com validade de 32 minutos, e nao um campo no registro da
 * sessao.** Regravar o registro seria ler, mudar e gravar -- e uma renovacao
 * concorrente (TEC-310) gravando o par novo no meio seria sobrescrita pelo par
 * antigo, cujo refresh ja foi consumido. A proxima renovacao o apresentaria de
 * novo, e a deteccao de reuso derrubaria a sessao. Aqui e um `SET` com
 * validade, sem leitura: cada uso empurra o fim para 32 minutos a frente, e a
 * chave sumir quer dizer "ociosa".
 */
async function marcarAtividade(id: string): Promise<void> {
  await (await armazem()).gravar(chave('atividade', id), '1', MINUTOS_OCIOSO_NO_SERVIDOR * 60)
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
    const loja = await armazem()
    await loja.apagar(chave('sessao', id))
    await loja.apagar(chave('atividade', id))
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
 * Quando o access expira, em milissegundos, pela claim `exp` -- ou `null`.
 *
 * **Le sem verificar a assinatura, e isso e deliberado** (D1 do desenho da
 * TEC-310). Nao e decisao de seguranca -- quem valida o token e o FastAPI, a
 * cada chamada --, e so agendamento: saber se vale renovar agora. A regra de
 * "nao decodificar JWT" (RN-FE-03.2) e sobre o navegador, e o navegador
 * continua sem ver o token. Claim ilegivel devolve `null`, e quem chama trata
 * como vencido: o erro cai para o lado de renovar a mais.
 */
export function expiracaoDoAcesso(acesso: string): number | null {
  try {
    const carga = JSON.parse(Buffer.from(acesso.split('.')[1] ?? '', 'base64url').toString('utf8'))
    return typeof carga.exp === 'number' ? carga.exp * 1000 : null
  } catch {
    return null
  }
}

function vencido(sessao: Sessao, agora: number): boolean {
  const expira = expiracaoDoAcesso(sessao.acesso)
  return expira === null || expira <= agora
}

function precisaRenovar(sessao: Sessao, agora: number): boolean {
  const expira = expiracaoDoAcesso(sessao.acesso)
  return expira === null || expira - agora <= MARGEM_DE_RENOVACAO_SEGUNDOS * 1000
}

/** O FastAPI nao respondeu a renovacao, e o access que havia ja venceu. */
export class RenovacaoIndisponivel extends Error {
  constructor() {
    super('nao foi possivel renovar a sessao agora')
    this.name = 'RenovacaoIndisponivel'
  }
}

/**
 * O access antigo, se ainda valer -- senao, `RenovacaoIndisponivel`.
 *
 * E o desfecho de uma renovacao que nao aconteceu por causa do BACKEND (fora do
 * ar, 5xx, lock que nao soltou a tempo): a sessao nao e invalida por isso, e
 * nao e apagada (D3). Como a renovacao comeca 5 minutos antes do fim, o access
 * antigo quase sempre ainda serve.
 */
function antigaSeValer(sessao: Sessao): Sessao {
  if (vencido(sessao, Date.now())) {
    throw new RenovacaoIndisponivel()
  }
  return sessao
}

/**
 * Grava o par novo conservando a validade original da sessao (D4).
 *
 * O registro vale 7 dias desde o LOGIN, e nao desde a renovacao: o cookie foi
 * emitido com esse `Max-Age` e Server Component nao consegue reemiti-lo. Uma
 * sessao que no Redis durasse mais que o cookie seria um refresh valido que
 * ninguem mais alcanca.
 */
async function gravarRenovada(id: string, sessao: Sessao): Promise<void> {
  const restante = Date.parse(sessao.criadaEm) + SEGUNDOS_DA_SESSAO * 1000 - Date.now()
  const loja = await armazem()
  if (!(restante > 0)) {
    await loja.apagar(chave('sessao', id))
    return
  }
  await loja.gravar(chave('sessao', id), JSON.stringify(sessao), Math.ceil(restante / 1000))
}

function dormir(ms: number): Promise<void> {
  return new Promise((resolver) => setTimeout(resolver, ms))
}

/**
 * Troca o refresh por um par novo, com lock (D2 e D3 do desenho da TEC-310).
 *
 * **O lock existe porque o refresh da TEC-201 e rotativo com deteccao de
 * reuso**: apresentar um refresh ja trocado revoga a familia inteira,
 * inclusive a do usuario legitimo. Duas requisicoes renovando juntas -- duas
 * abas, um prefetch ao lado da navegacao -- mandariam o mesmo refresh duas
 * vezes, e a segunda desligaria a pessoa como se fosse roubo.
 *
 * Quem pega o lock renova; quem nao pega espera o par novo aparecer no Redis.
 *
 * - `401` do `/auth/refresh` (revogado, expirado, reusado): a sessao acabou.
 *   E apagada, e o retorno e `null` -- quem chama leva ao login.
 * - FastAPI fora, 5xx, corpo sem os tokens: nada e apagado; vale o access
 *   antigo se ainda valer (`antigaSeValer`).
 */
async function renovar(id: string, sessao: Sessao): Promise<Sessao | null> {
  const loja = await armazem()
  const trava = chave('renovando', id)

  if (await loja.gravarSeAusente(trava, '1', SEGUNDOS_DO_LOCK)) {
    try {
      let resposta: Response
      try {
        resposta = await chamarApi('/api/v1/auth/refresh', {
          metodo: 'POST',
          corpo: JSON.stringify({ refresh: sessao.refresh }),
          tipoDoCorpo: 'application/json',
        })
      } catch {
        return antigaSeValer(sessao)
      }
      if (resposta.status === 401) {
        await apagarSessao(id)
        return null
      }
      const tokens = resposta.ok ? tokensDe(await resposta.json().catch(() => null)) : null
      if (!tokens) {
        return antigaSeValer(sessao)
      }
      const nova: Sessao = { ...tokens, criadaEm: sessao.criadaEm }
      await gravarRenovada(id, nova)
      return nova
    } finally {
      await loja.apagar(trava)
    }
  }

  const limite = Date.now() + ESPERA_PELO_LOCK_MS
  while (Date.now() < limite) {
    await dormir(INTERVALO_DA_ESPERA_MS)
    const atual = await lerSessao(id)
    if (!atual) {
      // Quem tinha o lock recebeu 401 e apagou: a sessao acabou para esta
      // requisicao tambem.
      return null
    }
    if (atual.acesso !== sessao.acesso) {
      return atual
    }
  }
  return antigaSeValer(sessao)
}

/**
 * A sessao deste id, ja renovada se faltarem 5 minutos ou menos -- ou `null`.
 *
 * E o que toda leitura de sessao do painel usa (TEC-310, D1). O `cache` do
 * React faz o layout e a pagina, que rodam na mesma requisicao,
 * compartilharem uma leitura e no maximo uma renovacao.
 *
 * **Toda leitura conta como atividade** (TEC-311, D3), e a sessao ociosa ha
 * mais de 32 minutos e apagada aqui.
 *
 * Pode lancar `RenovacaoIndisponivel` (D3): o backend nao respondeu e o access
 * ja venceu. Nao e "sem sessao", e quem chama nao deve mandar ao login.
 */
export const obterSessaoValida = cache(
  async (id: string | null | undefined): Promise<Sessao | null> => {
    const sessao = await lerSessao(id)
    if (!sessao || !idValido(id)) {
      return null
    }
    // Ociosa ha mais de 32 minutos: acabou, mesmo que o cookie e o refresh
    // ainda valham (TEC-311, D3). E o que protege o celular esquecido, que nao
    // roda o aviso de cliente.
    if ((await (await armazem()).obter(chave('atividade', id))) === null) {
      await apagarSessao(id)
      return null
    }
    await marcarAtividade(id)
    return precisaRenovar(sessao, Date.now()) ? renovar(id, sessao) : sessao
  },
)

/**
 * Apaga a sessao de quem fez a requisicao (TEC-310, D5).
 *
 * Para quando o FastAPI recusa o token (`401`) mesmo depois da renovacao --
 * `JWT_SEGREDO` trocado, usuario desativado. Sem isto, o login veria a sessao
 * ainda no Redis e mandaria de volta a pagina, que tomaria 401 de novo: o laco
 * que a TEC-309 deixou. Apagar do Redis funciona em Server Component, ao
 * contrario de apagar cookie, e o cookie que sobra passa a apontar para nada.
 */
export async function apagarSessaoDaRequisicao(): Promise<void> {
  await apagarSessao((await cookies()).get(COOKIE_DA_SESSAO)?.value)
}

/**
 * A sessao de quem pediu a pagina, ou o redirecionamento ao login (D5 do
 * desenho da TEC-309).
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
  const id = (await cookies()).get(COOKIE_DA_SESSAO)?.value
  const sessao = await obterSessaoValida(id)
  if (!sessao) {
    // Havia cookie e nao ha sessao: ela expirou ou a renovacao foi recusada
    // (cenario 2 do Gherkin da TEC-310). A tela diz isso, e o destino vai junto.
    redirect(urlDoLogin({ returnTo, erro: id ? 'sessao_expirada' : undefined }))
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

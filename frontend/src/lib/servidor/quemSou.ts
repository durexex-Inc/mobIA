import 'server-only'

import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { cache } from 'react'

import { urlDoLogin } from '@/lib/destino'
import { chamarApi } from '@/lib/servidor/api'
import { COOKIE_DA_SESSAO, exigirSessao, lerSessao, type Sessao } from '@/lib/servidor/sessao'

/**
 * Quem esta logado e o que pode (TEC-312, D2).
 *
 * Vem de `GET /api/v1/auth/me`, que devolve a matriz da TEC-202 ja resolvida
 * para o papel -- o painel nunca decodifica o JWT, e e o que a RN-FE-03.2 pede.
 */
export type QuemSou = {
  usuarioId: string
  papel: string
  corretorId: string | null
  permissoes: ReadonlySet<string>
}

/** O FastAPI recusou o token: o access expirou (sem a TEC-310, ninguem o renova). */
export class SessaoRecusada extends Error {
  constructor() {
    super('o FastAPI recusou o token da sessao')
    this.name = 'SessaoRecusada'
  }
}

/**
 * `/auth/me` com o JWT da sessao, uma vez por requisicao.
 *
 * **O `cache` do React e o que faz o layout e a pagina nao pedirem duas
 * vezes.** O layout le para desenhar o menu, a pagina le para conferir a
 * permissao (D3), e os dois rodam na mesma requisicao. Sem o `cache`, seriam
 * duas idas ao FastAPI por pagina. O `cache` vale so dentro de uma requisicao
 * -- nao ha risco de a identidade de um usuario servir a outro.
 *
 * `no-store`, e nao o Data Cache: a resposta e da pessoa, e o custo de uma ida
 * por pagina e o de uma consulta que nem toca o banco (`/auth/me` le so as
 * claims do token).
 */
export const quemSou = cache(async (acesso: string): Promise<QuemSou> => {
  const resposta = await chamarApi('/api/v1/auth/me', { acesso })
  if (resposta.status === 401) {
    throw new SessaoRecusada()
  }
  if (!resposta.ok) {
    throw new Error(`/auth/me respondeu ${resposta.status}`)
  }
  const corpo = (await resposta.json()) as {
    usuarioId: string
    papel: string
    corretorId: string | null
    permissoes: string[]
  }
  return {
    usuarioId: corpo.usuarioId,
    papel: corpo.papel,
    corretorId: corpo.corretorId,
    permissoes: new Set(corpo.permissoes),
  }
})

/**
 * Quem esta logado, para o layout desenhar o menu -- ou `null`.
 *
 * **Nunca redireciona e nunca lanca.** O layout nao e a guarda (D3): quem
 * decide se a pagina abre e a propria pagina, com `exigirPermissao`. Se nao
 * houver sessao, a pagina redireciona; se o FastAPI estiver fora, a pagina
 * mostra o erro dela. O layout so deixa de desenhar o menu.
 */
export async function quemSouDaRequisicao(): Promise<QuemSou | null> {
  try {
    const sessao = await lerSessao((await cookies()).get(COOKIE_DA_SESSAO)?.value)
    return sessao ? await quemSou(sessao.acesso) : null
  } catch {
    return null
  }
}

/**
 * A guarda de pagina (D3): sessao, identidade e se a permissao pedida esta nela.
 *
 * **Toda pagina do painel chama isto ANTES de buscar qualquer dado.** O layout
 * nao protege nada -- a documentacao do Next 16 diz que um layout "does not
 * control whether the rest of the route renders", e a pagina filha roda mesmo
 * que o layout a esconda. E aqui que o cenario 2 do Gherkin ("nenhum dado
 * administrativo e carregado") vira verdade por construcao.
 *
 * Devolve `permitido: false` em vez de redirecionar: quem nao pode ve a tela
 * "Sem permissao" no mesmo endereco, com o nome do papel (RN-FE-03.4).
 */
export async function exigirPermissao(
  returnTo: string,
  permitido: (permissoes: ReadonlySet<string>) => boolean,
): Promise<{ sessao: Sessao; quem: QuemSou; permitido: boolean }> {
  const sessao = await exigirSessao(returnTo)
  let quem: QuemSou
  try {
    quem = await quemSou(sessao.acesso)
  } catch (erro) {
    if (erro instanceof SessaoRecusada) {
      redirect(urlDoLogin({ returnTo, erro: 'sessao_expirada' }))
    }
    throw erro
  }
  return { sessao, quem, permitido: permitido(quem.permissoes) }
}

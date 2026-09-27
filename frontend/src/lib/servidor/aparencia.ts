import 'server-only'

import { type Aparencia, lerAparencia } from '@/lib/aparencia'

import { chamarApi } from './api'

/**
 * O formato do slug antes de ele virar pedaco de caminho da API. Minusculas,
 * digitos e hifen: o que cabe num `data-tenant` sem escape. Barra e ponto
 * ficam de fora, e com eles `../../health` nunca vira outra rota do FastAPI.
 */
const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/

/**
 * A aparencia do tenant, ou `null` se o slug nao existe.
 *
 * **Com cache de 60 s, e esse cache e requisito, nao otimizacao** (D4): quem
 * chama o FastAPI e este servidor, e o `RateLimitPorIP` de la ve o IP dele.
 * Sem cache, todos os visitantes de todos os sites dividiriam um balde so.
 *
 * Lanca quando o FastAPI responde outra coisa que 200 ou 404, ou devolve um
 * corpo que nao e aparencia: e defeito, e nao "tenant ausente".
 */
export async function buscarAparencia(tenant: string): Promise<Aparencia | null> {
  if (!SLUG.test(tenant)) {
    return null
  }
  const resposta = await chamarApi(`/widget/aparencia/${tenant}`, { revalidarEmSegundos: 60 })
  if (resposta.status === 404) {
    return null
  }
  if (!resposta.ok) {
    throw new Error(`aparencia do widget: o FastAPI respondeu ${resposta.status}`)
  }
  const aparencia = lerAparencia(await resposta.json())
  if (!aparencia) {
    throw new Error('aparencia do widget: o FastAPI devolveu um corpo fora do formato')
  }
  return aparencia
}

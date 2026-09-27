import 'server-only'

import { type Aparencia, lerAparencia } from '@/lib/aparencia'
import { lerDominios } from '@/lib/dominios'

import { chamarApi } from './api'

/**
 * O formato do slug do `data-tenant`. Minusculas, digitos e hifen: o que cabe
 * num atributo sem escape. O backend recusa subir com um `TENANT_SLUG` fora
 * dele (`Settings._tenant_slug_no_formato_do_next`, em `app/config.py`), e as
 * duas copias tem de bater -- senao nenhum slug casaria, e nada avisaria.
 *
 * Malformado nao chega a chamar a API: nao ha o que comparar.
 */
const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/

/**
 * A aparencia do tenant, ou `null` se o slug nao e o configurado -- inclusive
 * quando nao ha slug configurado nenhum. Os dois casos dao o mesmo `null`, e
 * a rota o mesmo 404: distinguir diria a quem sonda se existe algum tenant.
 *
 * **Com cache de 60 s, e esse cache e requisito, nao otimizacao** (D4): quem
 * chama o FastAPI e este servidor, e o `RateLimitPorIP` de la ve o IP dele.
 * Sem cache, todos os visitantes de todos os sites dividiriam um balde so --
 * o mesmo do painel inteiro.
 *
 * **Por isso a comparacao do slug e daqui, e nao do FastAPI** (emenda da
 * TEC-344 ao D3). O Data Cache do Next so guarda resposta 200; se o FastAPI
 * respondesse 404 a slug errado, cada visita de slug errado -- e, com
 * `TENANT_SLUG` vazio, de qualquer slug -- iria ao FastAPI. Ele responde
 * sempre 200 com o slug configurado, num URL so, e o cache fica com uma
 * entrada so, qualquer que seja o `data-tenant` pedido.
 *
 * Lanca quando o FastAPI responde outra coisa que 200, ou devolve um corpo
 * que nao e aparencia: e defeito, e nao "tenant ausente".
 *
 * **Os `dominios` vem junto (TEC-345, D3)**, porque sao do mesmo corpo e do
 * mesmo cache: `/embed/aparencia` os usa para negar a aparencia a quem pede de
 * outro site. Nao vao ao loader -- a rota os tira antes de responder.
 */
export async function buscarAparencia(
  tenant: string,
): Promise<(Aparencia & { dominios: string[] }) | null> {
  if (!SLUG.test(tenant)) {
    return null
  }
  const resposta = await chamarApi('/widget/aparencia', { revalidarEmSegundos: 60 })
  if (!resposta.ok) {
    throw new Error(`aparencia do widget: o FastAPI respondeu ${resposta.status}`)
  }
  const corpo: unknown = await resposta.json()
  const configurado =
    typeof corpo === 'object' && corpo !== null ? (corpo as Record<string, unknown>).tenant : undefined
  const aparencia = lerAparencia(corpo)
  const dominios = lerDominios((corpo as Record<string, unknown> | null)?.dominios)
  if (!aparencia || !dominios || (configurado !== null && typeof configurado !== 'string')) {
    throw new Error('aparencia do widget: o FastAPI devolveu um corpo fora do formato')
  }
  if (configurado !== tenant) {
    return null
  }
  return { ...aparencia, dominios }
}

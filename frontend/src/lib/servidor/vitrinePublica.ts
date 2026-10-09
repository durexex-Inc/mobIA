import 'server-only'

import type { FiltrosDoPortal } from '@/lib/buscaPublica'
import { detalheDe } from '@/lib/metricas'
import { imovelDetalheDe, type ImovelDetalhe } from '@/lib/imovelDetalhe'
import { itemDaVitrineDe, type ImovelDaVitrine, type PaginaDaVitrine } from '@/lib/vitrine'

import { chamarApi } from './api'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDoPortal extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDoPortal'
    this.status = status
    this.requestId = requestId
  }
}

function buscaDe(filtros: FiltrosDoPortal): URLSearchParams {
  const busca = new URLSearchParams()
  busca.set('operacao', filtros.operacao)
  if (filtros.precoMinCentavos !== undefined) {
    busca.set('precoMin', String(filtros.precoMinCentavos))
  }
  if (filtros.precoMaxCentavos !== undefined) {
    busca.set('precoMax', String(filtros.precoMaxCentavos))
  }
  if (filtros.tipo) {
    busca.set('tipo', filtros.tipo)
  }
  if (filtros.quartosMin !== undefined) {
    busca.set('quartosMin', String(filtros.quartosMin))
  }
  if (filtros.vagasMin !== undefined) {
    busca.set('vagasMin', String(filtros.vagasMin))
  }
  // Repetido, e nao separado por virgula: e o que `portal.py`
  // (`regioes: list[str] = Query(default=[])`) espera do lado do FastAPI. A
  // URL da propria pagina do Next fala outro formato -- ver `urlDaBusca` em
  // `lib/buscaPublica.ts`.
  for (const regiao of filtros.regioes ?? []) {
    busca.append('regioes', regiao)
  }
  if (filtros.ordem) {
    busca.set('ordem', filtros.ordem)
  }
  if (filtros.pagina !== undefined) {
    busca.set('pagina', String(filtros.pagina))
  }
  return busca
}

/**
 * `GET /portal/vitrine`, sem `acesso`: a rota e publica, e `chamarApi` so
 * manda `Authorization` quando `opcoes.acesso` esta presente.
 *
 * **Substitui a chamada a `GET /portal/imoveis`** (D7 do desenho do visual
 * do portal): aquela e a busca do agente, com no maximo dez imoveis e sem
 * paginacao; a vitrine pagina todos os que casam. O endpoint antigo continua
 * no backend, sem uso pelo portal.
 *
 * **Com cache de 60 s** (`revalidarEmSegundos`), no mesmo espirito de
 * `buscarAparencia`: a resposta nao varia por visitante, entao cachea-la no
 * Data Cache do Next e so ganho -- sem o cuidado de exclusividade com
 * `idDeRequisicao` que `api.ts` documenta para chamada autenticada.
 *
 * Um item que falhar a validacao (`itemDaVitrineDe`) e DESCARTADO da lista,
 * nunca quebra a pagina inteira.
 */
export async function buscarVitrine(filtros: FiltrosDoPortal): Promise<PaginaDaVitrine> {
  const resposta = await chamarApi('/portal/vitrine', {
    busca: buscaDe(filtros),
    revalidarEmSegundos: 60,
  })
  if (!resposta.ok) {
    throw new Error(`vitrine publica: o FastAPI respondeu ${resposta.status}`)
  }
  const corpo = (await resposta.json()) as {
    itens: unknown[]
    total: number
    pagina: number
    porPagina: number
  }
  return {
    itens: corpo.itens.map(itemDaVitrineDe).filter((item): item is ImovelDaVitrine => item !== null),
    total: corpo.total,
    pagina: corpo.pagina,
    porPagina: corpo.porPagina,
  }
}

/**
 * `GET /portal/imoveis/{id}`, sem `acesso` -- o detalhe publico (TEC-388,
 * D1). Lanca `ErroDoPortal` com o status para a pagina distinguir 404/422
 * (imovel indisponivel ou id malformado, D3) de outra falha.
 *
 * Sem cache: ao contrario da listagem, o detalhe e aberto bem menos vezes por
 * visitante, e a TEC-388 nao tem requisito de performance que justifique
 * cachear -- `revalidarEmSegundos` fica para quando (se) isso importar.
 */
export async function buscarDetalheDoImovel(id: string): Promise<ImovelDetalhe> {
  const resposta = await chamarApi(`/portal/imoveis/${encodeURIComponent(id)}`, {})
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDoPortal(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  const corpo: unknown = await resposta.json()
  const detalhe = imovelDetalheDe(corpo)
  if (!detalhe) {
    throw new Error('detalhe do imovel: o FastAPI devolveu um corpo fora do formato')
  }
  return detalhe
}

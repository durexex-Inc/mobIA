import 'server-only'

import type { FiltrosDoPortal } from '@/lib/buscaPublica'
import { detalheDe } from '@/lib/metricas'
import { imovelDe, type ImovelCard } from '@/lib/imovel'
import { imovelDetalheDe, type ImovelDetalhe } from '@/lib/imovelDetalhe'

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

export type ResultadoDoPortal = {
  itens: ImovelCard[]
  totalCandidatos: number
  relaxamentoAplicado: boolean
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
  return busca
}

/**
 * `GET /portal/imoveis`, sem `acesso`: a rota e publica (D1 do desenho da
 * TEC-387), e `chamarApi` so manda `Authorization` quando `opcoes.acesso`
 * esta presente.
 *
 * **Com cache de 60 s** (`revalidarEmSegundos`), no mesmo espirito de
 * `buscarAparencia`: a resposta nao varia por visitante, entao cachea-la no
 * Data Cache do Next e so ganho -- sem o cuidado de exclusividade com
 * `idDeRequisicao` que `api.ts` documenta para chamada autenticada.
 *
 * **O corpo vira `ImovelCard` pelo mesmo parser da rede** (`imovelDe`):
 * `preco` da API vira `precoCentavos`, e os quatro campos que a busca nao tem
 * (`condominioCentavos`, `diferencial`, `foto`) ficam `null` -- o parser ja
 * trata ausencia como nulo para esses, de proposito (D4 do desenho de
 * `imovel.ts`). Um item que falhar a validacao (campo obrigatorio ausente ou
 * com tipo errado) e DESCARTADO da lista, nunca quebra a pagina inteira.
 *
 * **`url` aponta para o detalhe interno** (`/busca/{id}`, TEC-388) -- montada
 * aqui, depois do `imovelDe`, e nao vinda da rede: `urlSegura` so aceita
 * `http(s)` absoluto (pensado para link externo de catalogo de terceiro), e
 * um caminho relativo construido por nos mesmos nao precisa dessa validacao.
 * `CardDeImovel` distingue link interno de externo pelo `/` inicial (D5).
 */
export async function buscarVitrinePublica(filtros: FiltrosDoPortal): Promise<ResultadoDoPortal> {
  const resposta = await chamarApi('/portal/imoveis', {
    busca: buscaDe(filtros),
    revalidarEmSegundos: 60,
  })
  if (!resposta.ok) {
    throw new Error(`vitrine publica: o FastAPI respondeu ${resposta.status}`)
  }
  const corpo = (await resposta.json()) as {
    itens: Record<string, unknown>[]
    totalCandidatos: number
    relaxamentoAplicado: boolean
  }
  const itens = corpo.itens
    .map((item) => imovelDe({ ...item, precoCentavos: item.preco }))
    .filter((item): item is ImovelCard => item !== null)
    .map((item) => ({ ...item, url: `/busca/${item.id}` }))
  return { itens, totalCandidatos: corpo.totalCandidatos, relaxamentoAplicado: corpo.relaxamentoAplicado }
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

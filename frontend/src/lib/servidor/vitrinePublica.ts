import 'server-only'

import type { FiltrosDoPortal } from '@/lib/buscaPublica'
import { imovelDe, type ImovelCard } from '@/lib/imovel'

import { chamarApi } from './api'

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
 * `GET /portal/imoveis`, sem `acesso`: a rota e publica (D1 do desenho), e
 * `chamarApi` so manda `Authorization` quando `opcoes.acesso` esta presente.
 *
 * **Com cache de 60 s** (`revalidarEmSegundos`), no mesmo espirito de
 * `buscarAparencia`: a resposta nao varia por visitante, entao cachea-la no
 * Data Cache do Next e so ganho -- sem o cuidado de exclusividade com
 * `idDeRequisicao` que `api.ts` documenta para chamada autenticada.
 *
 * **O corpo vira `ImovelCard` pelo mesmo parser da rede** (`imovelDe`):
 * `preco` da API vira `precoCentavos`, e os quatro campos que a busca nao tem
 * (`condominioCentavos`, `diferencial`, `foto`, `url`) ficam `null` -- o
 * parser ja trata ausencia como nulo para esses quatro, de proposito (D4 do
 * desenho de `imovel.ts`). Um item que falhar a validacao (campo obrigatorio
 * ausente ou com tipo errado) e DESCARTADO da lista, nunca quebra a pagina
 * inteira.
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
  return { itens, totalCandidatos: corpo.totalCandidatos, relaxamentoAplicado: corpo.relaxamentoAplicado }
}

import { detalheDe, ErroDeMetricas, type Filtros } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'

/** Os quatro campos de `TokensDoModelo` (`custo.py`), por modelo. */
export type TokensPorModelo = {
  entrada: number
  saida: number
  cacheLeitura: number
  cacheEscrita: number
}

/**
 * O bloco de orçamento, ou ausente quando nenhum foi configurado (TEC-191,
 * D3 daquele desenho). `null` aqui é "sem orçamento", não "orçamento zero" --
 * a mesma distinção que `estadoDe` protege em outros lugares deste painel.
 */
export type Orcamento = {
  mensalUsd: number
  doPeriodoUsd: number
  consumidoUsd: number
  consumidoPct: number
  alerta: boolean
}

/**
 * `GET /api/v1/metricas/custo-ia`, como a TEC-191 o devolve.
 *
 * **`custoTotalUsd` nunca é nulo** (D2 do desenho da TEC-319): o backend usa
 * `COALESCE(SUM(...), 0)`, e um período sem gasto é `0` de verdade.
 * `custoPorConversaUsd`/`custoPorLeadQualificadoUsd` são nulos com
 * denominador zero -- "não houve conversa" não é "custou zero".
 */
export type CustoDeIA = {
  custoTotalUsd: number
  custoPorConversaUsd: number | null
  custoPorLeadQualificadoUsd: number | null
  tokensPorModelo: Record<string, TokensPorModelo>
  conversas: number
  leadsQualificados: number
  mensagensSemPreco: number
  alvoPorLeadQualificadoUsd: number
  acimaDoAlvo: boolean | null
  orcamento: Orcamento | null
}

/**
 * Busca o custo de IA no FastAPI. Roda só no servidor -- `chamarApi` importa
 * `server-only` (TEC-302).
 *
 * **Sem cache**, como a lista de leads (D6 da TEC-321): o painel de custo não
 * tem o problema de carga que o funil tinha (RN-17.3 pede 60s de defasagem
 * ali; aqui não há teto parecido), e cachear introduziria a mesma
 * complexidade de chave por `Authorization` sem necessidade equivalente.
 */
export async function buscarCusto(filtros: Filtros, acesso: string): Promise<CustoDeIA> {
  const busca = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) {
      busca.set(chave, valor)
    }
  }

  const resposta = await chamarApi('/api/v1/metricas/custo-ia', { acesso, busca })

  if (!resposta.ok) {
    const { mensagem, campos } = await detalheDe(resposta)
    throw new ErroDeMetricas(resposta.status, mensagem, {
      requestId: resposta.headers.get('x-request-id'),
      campos,
    })
  }

  return (await resposta.json()) as CustoDeIA
}

import 'server-only'

import type { DetalheDoLead } from '@/lib/detalhe'
import type { Ordem, PaginaDeLeads } from '@/lib/leads'
import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDeLeads extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDeLeads'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * A primeira pagina de `GET /api/v1/leads` (TEC-321).
 *
 * **Sem cache** (D6 do desenho), ao contrario do funil. O score e recalculado
 * a cada turno do agente, entao um `revalidate` faria o corretor ver o lead
 * esquentar com atraso. E cada combinacao de busca e ordem seria uma entrada
 * de cache propria, sem acerto que compensasse.
 *
 * `busca` chega aqui ja filtrada por `buscaEfetiva`: a regra dos 2 caracteres
 * e de quem chama, e nao desta funcao, para que o teste da pagina possa
 * afirmar que a busca curta nao sai.
 */
export async function buscarLeads(
  { busca, ordem }: { busca?: string; ordem: Ordem },
  acesso: string,
): Promise<PaginaDeLeads> {
  const parametros = new URLSearchParams({ ordenar: ordem })
  if (busca) {
    parametros.set('busca', busca)
  }

  const resposta = await chamarApi('/api/v1/leads', { acesso, busca: parametros })

  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeLeads(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }

  return (await resposta.json()) as PaginaDeLeads
}

/**
 * `GET /api/v1/leads/{leadId}` (TEC-323).
 *
 * **Cada chamada grava um acesso na trilha** (D3 da TEC-193), e por isso ela
 * e `no-store` e so sai quando a pagina e aberta de fato -- nunca por
 * prefetch (D2 do desenho da TEC-323). O `leadId` vai codificado: ele vem da
 * URL, e um valor com `/` nao pode virar outro caminho da API.
 */
export async function buscarDetalhe(leadId: string, acesso: string): Promise<DetalheDoLead> {
  const resposta = await chamarApi(`/api/v1/leads/${encodeURIComponent(leadId)}`, { acesso })

  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeLeads(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }

  return (await resposta.json()) as DetalheDoLead
}

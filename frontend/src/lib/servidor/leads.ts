import 'server-only'

import type { DetalheDoLead } from '@/lib/detalhe'
import type { FiltrosDaLista, Ordem, PaginaDeLeads, PosicaoNaLista } from '@/lib/leads'
import type { PaginaDaTranscricao } from '@/lib/transcricao'
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
 * Uma pagina de `GET /api/v1/leads` (TEC-321; filtros e cursor desde a
 * TEC-322).
 *
 * **Sem cache** (D6 do desenho da TEC-321), ao contrario do funil. O score e
 * recalculado a cada turno do agente, entao um `revalidate` faria o corretor
 * ver o lead esquentar com atraso. E cada combinacao de busca, ordem e filtro
 * seria uma entrada de cache propria, sem acerto que compensasse.
 *
 * `busca` chega aqui ja filtrada por `buscaEfetiva`, e os filtros por
 * `filtrosDaUrl`: a regra e de quem chama, para que o teste da pagina possa
 * afirmar o que nao sai.
 */
export async function buscarLeads(
  {
    busca,
    ordem,
    filtros = {},
    cursor,
  }: { busca?: string; ordem: Ordem; filtros?: FiltrosDaLista; cursor?: string },
  acesso: string,
): Promise<PaginaDeLeads> {
  const parametros = new URLSearchParams({ ordenar: ordem })
  if (busca) {
    parametros.set('busca', busca)
  }
  for (const chave of ['status', 'temperatura', 'canal', 'corretorId'] as const) {
    const valor = filtros[chave]
    if (valor) {
      parametros.set(chave, valor)
    }
  }
  if (cursor) {
    parametros.set('cursor', cursor)
  }

  const resposta = await chamarApi('/api/v1/leads', { acesso, busca: parametros })

  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeLeads(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }

  return (await resposta.json()) as PaginaDeLeads
}

/**
 * As paginas que a tela desenha, cada uma com o seu numero (TEC-322, D2 e D3).
 *
 * **Sem `acumular`, uma chamada so**: a pagina atual. Com ele -- o "carregar
 * mais" --, a pagina 1, as de `anteriores` e a atual, **em paralelo**: os
 * cursores ja estao todos na URL, e nenhuma depende da outra. O custo sao N
 * chamadas para a pagina N, e so o "carregar mais" o paga.
 */
export async function buscarPaginas(
  consulta: { busca?: string; ordem: Ordem; filtros?: FiltrosDaLista },
  posicao: PosicaoNaLista,
  acesso: string,
): Promise<Array<PaginaDeLeads & { numero: number }>> {
  const cursores: Array<string | undefined> = posicao.acumular
    ? [undefined, ...posicao.anteriores, posicao.cursor]
    : [posicao.cursor]
  const primeira = posicao.acumular ? 1 : posicao.cursor ? posicao.anteriores.length + 2 : 1
  const paginas = await Promise.all(
    cursores.map((cursor) => buscarLeads({ ...consulta, cursor }, acesso)),
  )
  return paginas.map((pagina, i) => ({ ...pagina, numero: primeira + i }))
}

/** Um corretor para o filtro da lista (TEC-322, D5). */
export type CorretorDoFiltro = { id: string; nome: string }

/**
 * Os corretores ativos, para o filtro da lista. **So para quem tem
 * `GERIR_CORRETORES`** -- a rota o exige, e hoje so o ADMIN o tem (D5). Quem
 * chama decide pela permissao antes; aqui, uma recusa vira lista vazia, e o
 * filtro fica sem opcoes em vez de derrubar a lista.
 */
export async function buscarCorretores(acesso: string): Promise<CorretorDoFiltro[]> {
  const resposta = await chamarApi('/api/v1/corretores', {
    acesso,
    busca: new URLSearchParams({ ativos: 'true' }),
  })
  if (!resposta.ok) {
    return []
  }
  const corretores = (await resposta.json()) as Array<{ id: string; nome: string }>
  return corretores.map(({ id, nome }) => ({ id, nome }))
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

/**
 * A primeira pagina da transcricao: as 100 falas mais recentes (TEC-324, D1).
 *
 * Grava um acesso na trilha com `campo=transcricao`, como `buscarDetalhe`
 * grava o dele (D3 da TEC-193). As paginas anteriores nao passam por aqui: o
 * componente de cliente as busca pelo proxy `/bff/*`.
 */
export async function buscarTranscricao(
  leadId: string,
  acesso: string,
): Promise<PaginaDaTranscricao> {
  const resposta = await chamarApi(`/api/v1/leads/${encodeURIComponent(leadId)}/mensagens`, {
    acesso,
  })

  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeLeads(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }

  return (await resposta.json()) as PaginaDaTranscricao
}

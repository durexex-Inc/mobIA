import 'server-only'

import {
  fimDoDia,
  type FiltrosDaTrilha,
  inicioDoDia,
  type PaginaDaTrilha,
  type PosicaoNaTrilha,
} from '@/lib/auditoria'
import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDaTrilha extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDaTrilha'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * Uma pagina de `GET /api/v1/auditoria` (TEC-343). `de`/`ate` chegam como
 * data (`aaaa-mm-dd`) e viram limites com fuso aqui (D4 do desenho) -- e nao
 * em `lib/auditoria.ts`, que e sem I/O mas nao teria por que saber que isso e
 * problema de fetch e nao de exibicao.
 *
 * **Sem cache**, como a lista de leads: um evento novo tem de aparecer na
 * proxima carga.
 */
export async function buscarTrilha(
  { filtros = {}, cursor }: { filtros?: FiltrosDaTrilha; cursor?: string },
  acesso: string,
): Promise<PaginaDaTrilha> {
  const parametros = new URLSearchParams()
  if (filtros.ator) {
    parametros.set('ator', filtros.ator)
  }
  if (filtros.acao) {
    parametros.set('acao', filtros.acao)
  }
  if (filtros.de) {
    parametros.set('de', inicioDoDia(filtros.de))
  }
  if (filtros.ate) {
    parametros.set('ate', fimDoDia(filtros.ate))
  }
  if (cursor) {
    parametros.set('cursor', cursor)
  }

  const resposta = await chamarApi('/api/v1/auditoria', { acesso, busca: parametros })

  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDaTrilha(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }

  return (await resposta.json()) as PaginaDaTrilha
}

/**
 * As paginas que a tela desenha (D2 do desenho): so "Carregar mais", entao
 * sempre acumula -- a pagina 1, as de `anteriores` e a atual, em paralelo: os
 * cursores ja estao todos na URL, e nenhuma depende da outra.
 */
export async function buscarPaginas(
  filtros: FiltrosDaTrilha | undefined,
  posicao: PosicaoNaTrilha,
  acesso: string,
): Promise<PaginaDaTrilha[]> {
  const cursores: Array<string | undefined> = posicao.cursor
    ? [undefined, ...posicao.anteriores, posicao.cursor]
    : [undefined]
  return Promise.all(cursores.map((cursor) => buscarTrilha({ filtros, cursor }, acesso)))
}

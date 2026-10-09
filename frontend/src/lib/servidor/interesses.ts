import 'server-only'

import type { EstadoDosPedidos, PaginaDePedidos } from '@/lib/interesses'
import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDeInteresses extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDeInteresses'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * Uma pagina de `GET /api/v1/interesses` (TEC-404, D9 do desenho).
 *
 * **Sem cache**: o atendimento muda a cada aceite, escalada e notificacao, e
 * o corretor que acabou de assumir nao pode ver o pedido ainda pendente. O
 * `cursor` e opaco, e vem da pagina anterior; um invalido o FastAPI recusa
 * com 422, e a pagina mostra a mensagem.
 */
export async function buscarInteresses(
  { estado, cursor }: { estado: EstadoDosPedidos; cursor?: string },
  acesso: string,
): Promise<PaginaDePedidos> {
  const parametros = new URLSearchParams({ estado })
  if (cursor) {
    parametros.set('cursor', cursor)
  }

  const resposta = await chamarApi('/api/v1/interesses', { acesso, busca: parametros })

  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeInteresses(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }

  return (await resposta.json()) as PaginaDePedidos
}

import 'server-only'

import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'
import type { PedidoDoTitular } from '@/lib/titular'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDaFilaDoTitular extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDaFilaDoTitular'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * Os pedidos ABERTOS de `GET /api/v1/titular/solicitacoes` (TEC-340, D2),
 * na ordem da API -- quem vence primeiro no topo.
 *
 * **Sem cache**, como a lista de leads: um pedido registrado agora pelo
 * WhatsApp tem de aparecer na proxima carga, e o prazo e o que a tela existe
 * para vigiar.
 */
export async function buscarFilaDoTitular(acesso: string): Promise<PedidoDoTitular[]> {
  const resposta = await chamarApi('/api/v1/titular/solicitacoes', {
    acesso,
    busca: new URLSearchParams({ status: 'ABERTA' }),
  })
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDaFilaDoTitular(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  return ((await resposta.json()) as { itens: PedidoDoTitular[] }).itens
}

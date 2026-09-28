import 'server-only'

import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'
import type { Corretor } from '@/lib/corretores'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDeCorretores extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDeCorretores'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * Todos os corretores, ativos e inativos juntos (D6 do desenho, D8 da
 * listagem inicial).
 *
 * **Sem `?ativos=`.** O parametro `ativos` do backend, apesar do nome,
 * significa "somente ativos" (`corretores.py::listar`) -- omitido ou
 * `false`, devolve todos. A card pede que inativo e plantonista apareçam na
 * mesma lista, marcados por texto; buscar so os ativos esconderia a metade
 * do que a tela precisa mostrar.
 *
 * **Roda so no servidor**, como `buscarFilaDoTitular`: a chamada sai por
 * `servidor/api.ts`, que importa `server-only`. As mutacoes (cadastrar,
 * editar, desativar) passam pelo `/bff/*` a partir do `'use client'` -- ver
 * a D8 do desenho.
 */
export async function buscarCorretores(acesso: string): Promise<Corretor[]> {
  const resposta = await chamarApi('/api/v1/corretores', { acesso })
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeCorretores(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  return (await resposta.json()) as Corretor[]
}

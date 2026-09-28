import 'server-only'

import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'
import type { Importacao } from '@/lib/importacaoDeImoveis'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDeImportacao extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDeImportacao'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * A importacao mais recente, ou `null` quando nunca houve uma (D4 do
 * desenho). `GET /api/v1/imoveis/importacoes?limite=1` -- mesmo padrao de
 * `buscarImoveis`/`buscarCorretores`: roda so no servidor, direto de
 * `servidor/api.ts`, que importa `server-only`.
 *
 * Se a importacao devolvida estiver `PROCESSANDO`, e `AcompanharImportacao`
 * (D3) que assume dali -- esta funcao so le o estado no momento do render.
 */
export async function buscarImportacaoMaisRecente(acesso: string): Promise<Importacao | null> {
  const resposta = await chamarApi('/api/v1/imoveis/importacoes', {
    acesso,
    busca: new URLSearchParams({ limite: '1' }),
  })
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeImportacao(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  const corpo = (await resposta.json()) as { itens: Importacao[] }
  return corpo.itens[0] ?? null
}

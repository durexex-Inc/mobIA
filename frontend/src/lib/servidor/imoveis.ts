import 'server-only'

import { detalheDe } from '@/lib/metricas'
import { chamarApi } from '@/lib/servidor/api'
import type { Imovel } from '@/lib/imoveis'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDeImoveis extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDeImoveis'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * Os imoveis da administracao, de todo status junto (D6 do desenho).
 *
 * **Sem `?status=`.** Omitido, `GET /api/v1/imoveis` devolve todo status,
 * inclusive `INATIVO` (`cadastro.listar`, D5 do desenho da TEC-197) -- o
 * terceiro cenario do Gherkin exige que o imovel retirado continue visivel
 * aqui, marcado como retirado.
 *
 * **Sem paginacao.** So o `limite` padrao do backend (`cadastro.LIMITE_PADRAO`,
 * 50), sem consumir `proximoCursor` -- lacuna declarada da D6, esta tela nao
 * tem busca nem paginacao na primeira versao.
 *
 * **Roda so no servidor**, como `buscarCorretores`: a chamada sai por
 * `servidor/api.ts`, que importa `server-only`. As mutacoes (cadastrar,
 * editar, retirar) passam pelo `/bff/*` a partir do `'use client'` -- D7 do
 * desenho.
 */
export async function buscarImoveis(acesso: string): Promise<Imovel[]> {
  const resposta = await chamarApi('/api/v1/imoveis', { acesso })
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeImoveis(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  const corpo = (await resposta.json()) as { itens: Imovel[]; proximoCursor: string | null }
  return corpo.itens
}

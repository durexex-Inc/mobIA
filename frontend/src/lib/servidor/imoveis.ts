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
 * Os imoveis da administracao, de todo status junto (D6 do desenho da
 * TEC-333), nas `paginas` primeiras paginas (TEC-401).
 *
 * **Sem `?status=`.** Omitido, `GET /api/v1/imoveis` devolve todo status,
 * inclusive `INATIVO` (`cadastro.listar`, D5 do desenho da TEC-197) -- o
 * terceiro cenario do Gherkin exige que o imovel retirado continue visivel
 * aqui, marcado como retirado.
 *
 * **As paginas sao percorridas em sequencia**, cada uma pelo `proximoCursor`
 * da anterior (D2 da TEC-401), e nao refeitas em paralelo a partir de
 * cursores guardados como na trilha de auditoria: o catalogo muda em
 * qualquer ponto da ordem por codigo, e cursores velhos pulariam ou
 * repetiriam imovel (D1). Para quando a API nao devolve mais cursor.
 *
 * **Roda so no servidor**, como `buscarCorretores`: a chamada sai por
 * `servidor/api.ts`, que importa `server-only`. As mutacoes (cadastrar,
 * editar, retirar) passam pelo `/bff/*` a partir do `'use client'` -- D7 do
 * desenho da TEC-333.
 */
export async function buscarImoveis(
  acesso: string,
  paginas = 1,
): Promise<{ itens: Imovel[]; haMais: boolean }> {
  const itens: Imovel[] = []
  let cursor: string | null = null
  for (let pagina = 0; pagina < paginas; pagina += 1) {
    const busca = cursor ? new URLSearchParams({ cursor }) : undefined
    const resposta = await chamarApi('/api/v1/imoveis', { acesso, busca })
    if (!resposta.ok) {
      const { mensagem } = await detalheDe(resposta)
      throw new ErroDeImoveis(resposta.status, mensagem, resposta.headers.get('x-request-id'))
    }
    const corpo = (await resposta.json()) as { itens: Imovel[]; proximoCursor: string | null }
    itens.push(...corpo.itens)
    cursor = corpo.proximoCursor
    if (!cursor) {
      break
    }
  }
  return { itens, haMais: cursor !== null }
}

/**
 * Um imovel, para a pagina de edicao (TEC-400): `GET /api/v1/imoveis/{id}`,
 * de qualquer status -- como a listagem, e a visao de quem administra. Um 404
 * sobe como `ErroDeImoveis` e a pagina o trata como "nao encontrado".
 */
export async function buscarImovel(acesso: string, id: string): Promise<Imovel> {
  const resposta = await chamarApi(`/api/v1/imoveis/${encodeURIComponent(id)}`, { acesso })
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeImoveis(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  return (await resposta.json()) as Imovel
}

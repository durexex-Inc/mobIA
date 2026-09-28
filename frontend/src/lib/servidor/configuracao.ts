import 'server-only'

import { detalheDe } from '@/lib/metricas'
import type { Configuracao, EntradaDoHistorico, Limites } from '@/lib/configuracao'
import { chamarApi } from '@/lib/servidor/api'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDeConfiguracao extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDeConfiguracao'
    this.status = status
    this.requestId = requestId
  }
}

/**
 * A configuracao vigente do agente, os limites de cada campo e a versao
 * (TEC-337, D1). Roda so no servidor, como `buscarImoveis` -- a mutacao
 * (`PATCH`) e quem faz a leitura de novo apos salvar passam pelo `/bff/*` a
 * partir do `'use client'`.
 */
export async function buscarConfiguracao(
  acesso: string,
): Promise<{ configuracao: Configuracao; limites: Limites; versao: string | null }> {
  const resposta = await chamarApi('/api/v1/configuracao/agente', { acesso })
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeConfiguracao(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  return (await resposta.json()) as {
    configuracao: Configuracao
    limites: Limites
    versao: string | null
  }
}

/**
 * O historico de alteracoes, mais recente primeiro -- ja ordenado pelo
 * backend (D1 da rota `GET /agente/historico`).
 */
export async function buscarHistorico(
  acesso: string,
  limite = 20,
): Promise<{ itens: EntradaDoHistorico[] }> {
  const busca = new URLSearchParams({ limite: String(limite) })
  const resposta = await chamarApi('/api/v1/configuracao/agente/historico', { acesso, busca })
  if (!resposta.ok) {
    const { mensagem } = await detalheDe(resposta)
    throw new ErroDeConfiguracao(resposta.status, mensagem, resposta.headers.get('x-request-id'))
  }
  return (await resposta.json()) as { itens: EntradaDoHistorico[] }
}

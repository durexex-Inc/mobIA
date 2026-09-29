import 'server-only'

import { detalheDe } from '@/lib/metricas'
import type {
  AgenteAtivo,
  AgenteDaRota,
  PromptDoAgente,
  VersaoComTexto,
  VersaoResumida,
} from '@/lib/prompts'
import { nomeDoAgenteNaApi } from '@/lib/prompts'
import { chamarApi } from '@/lib/servidor/api'

/** A recusa do FastAPI, com o `X-Request-Id` da resposta quando ele veio. */
export class ErroDePrompt extends Error {
  status: number
  requestId: string | null

  constructor(status: number, mensagem: string, requestId: string | null) {
    super(mensagem)
    this.name = 'ErroDePrompt'
    this.status = status
    this.requestId = requestId
  }
}

async function erroDaResposta(resposta: Response): Promise<ErroDePrompt> {
  const { mensagem } = await detalheDe(resposta)
  return new ErroDePrompt(resposta.status, mensagem, resposta.headers.get('x-request-id'))
}

/** Os dois agentes com a versao ativa de cada um (D1 do desenho). */
export async function buscarAgentes(acesso: string): Promise<{ itens: AgenteAtivo[] }> {
  const resposta = await chamarApi('/api/v1/prompts', { acesso })
  if (!resposta.ok) {
    throw await erroDaResposta(resposta)
  }
  return (await resposta.json()) as { itens: AgenteAtivo[] }
}

/** A versao ativa de um agente, com o texto, o padrao do codigo e os limites. */
export async function buscarAgente(acesso: string, agente: AgenteDaRota): Promise<PromptDoAgente> {
  const resposta = await chamarApi(`/api/v1/prompts/${nomeDoAgenteNaApi(agente)}`, { acesso })
  if (!resposta.ok) {
    throw await erroDaResposta(resposta)
  }
  return (await resposta.json()) as PromptDoAgente
}

/** A lista de versoes publicadas, para o seletor de comparacao (sem texto). */
export async function buscarVersoes(
  acesso: string,
  agente: AgenteDaRota,
  limite = 20,
): Promise<{ ativa: number; itens: VersaoResumida[] }> {
  const busca = new URLSearchParams({ limite: String(limite) })
  const resposta = await chamarApi(`/api/v1/prompts/${nomeDoAgenteNaApi(agente)}/versoes`, {
    acesso,
    busca,
  })
  if (!resposta.ok) {
    throw await erroDaResposta(resposta)
  }
  return (await resposta.json()) as { ativa: number; itens: VersaoResumida[] }
}

/**
 * Uma versao com o texto, para a comparacao lado a lado (D3 do desenho).
 *
 * **So o Server Component da pagina de detalhe chama isto** -- trocar qual par
 * comparar e navegacao por `searchParams`, nao fetch de cliente, entao esta
 * rota nunca precisou entrar em `lib/servidor/bff.ts`.
 */
export async function buscarVersao(
  acesso: string,
  agente: AgenteDaRota,
  numero: number,
): Promise<VersaoComTexto> {
  const resposta = await chamarApi(
    `/api/v1/prompts/${nomeDoAgenteNaApi(agente)}/versoes/${numero}`,
    { acesso },
  )
  if (!resposta.ok) {
    throw await erroDaResposta(resposta)
  }
  return (await resposta.json()) as VersaoComTexto
}

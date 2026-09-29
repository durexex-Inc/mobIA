/**
 * O prompt de um agente, sem I/O (TEC-338).
 *
 * **D2 do desenho: a rota usa o segmento minusculo do enum, sem tabela de
 * traducao.** `AgenteDoPrompt` do backend (`domain/prompts/modelo.py`) so tem
 * dois valores, `AGENTE` e `INVESTIDOR` -- `agenteDaRota` e `rotaDoAgente` sao
 * so o `toUpperCase`/`toLowerCase` entre o segmento da URL e o valor que a API
 * espera, guardado por um `Set` dos dois validos.
 */

export type AgenteDaRota = 'agente' | 'investidor'

const AGENTES_VALIDOS: ReadonlySet<string> = new Set(['agente', 'investidor'])

/** O rotulo de cada agente, para o titulo da tela. */
export const ROTULO_DO_AGENTE: Record<AgenteDaRota, string> = {
  agente: 'Agente principal',
  investidor: 'Subagente investidor',
}

/** `null` quando o segmento nao e um dos dois agentes -- a pagina responde com `notFound()`. */
export function agenteDaRota(segmento: string): AgenteDaRota | null {
  return AGENTES_VALIDOS.has(segmento) ? (segmento as AgenteDaRota) : null
}

/** O valor que `domain/prompts/modelo.py::AgenteDoPrompt` espera no caminho da API. */
export function nomeDoAgenteNaApi(agente: AgenteDaRota): string {
  return agente.toUpperCase()
}

export function rotaDoAgente(agenteNaApi: string): AgenteDaRota {
  return agenteNaApi.toLowerCase() as AgenteDaRota
}

/** `GET /api/v1/prompts::itens[]` e o `ativa` de `GET /api/v1/prompts/{agente}`. */
export type AgenteAtivo = {
  agente: string
  versao: number
  padrao: boolean
  publicadaPor: string | null
  publicadaEm: string | null
  ativadaPor: string | null
  ativadaEm: string | null
  motivo: string | null
}

/** `GET /api/v1/prompts/{agente}::limites`. */
export type LimitesDoPrompt = {
  marcadores: string[]
  maximoDeCaracteres: number
}

/** `GET /api/v1/prompts/{agente}`: a ativa com o texto, o padrao do codigo e os limites. */
export type PromptDoAgente = {
  ativa: AgenteAtivo & { texto: string }
  padrao: string
  limites: LimitesDoPrompt
}

/** Um item de `GET /api/v1/prompts/{agente}/versoes` -- sem `texto` (D3 do desenho). */
export type VersaoResumida = {
  versao: number
  anterior: number | null
  autor: string
  em: string
  diff: string
}

/** `GET /api/v1/prompts/{agente}/versoes/{numero}`, com o texto (D3 do desenho). */
export type VersaoComTexto = VersaoResumida & { texto: string; padrao?: boolean }

/**
 * `POST /api/v1/prompts/{agente}/rollback` (TEC-339, D1).
 *
 * `tempoDeAtivacaoMs` e quanto a propria chamada levou -- nao ha cache nem
 * fila para propagar (D1 do desenho), entao a versao ja esta ativa quando a
 * resposta volta. So aparece no sucesso: 404/409 nao tem o campo.
 */
export type RespostaDoRollback = {
  ativa: AgenteAtivo
  tempoDeAtivacaoMs: number
}

/**
 * A trilha de auditoria, sem I/O (TEC-343).
 *
 * **Modulo puro de proposito**, no molde de `lib/leads.ts`: o filtro e
 * componente de cliente, e nada que ele importe pode arrastar `server-only`.
 * A chamada ao FastAPI mora em `lib/servidor/auditoria.ts`.
 */

/** Um item de `GET /api/v1/auditoria`, como a TEC-206 o devolve. */
export type EventoDaTrilha = {
  id: string
  criadoEm: string
  atorTipo: string
  atorId: string | null
  acao: string
  entidade: string
  entidadeId: string | null
  campo: string | null
  detalhes: Record<string, string | null> | null
  ip: string | null
  correlationId: string | null
}

export type PaginaDaTrilha = { itens: EventoDaTrilha[]; proximoCursor: string | null }

/**
 * Os tipos de evento, legiveis (`Acao` de `domain/auditoria/vocabulario.py`).
 * Exportado porque o filtro sai daqui, e `tests/unit/test_vocabulario_da_tela.py`
 * o compara com o backend -- no molde de `TEMPERATURAS`/`STATUS` de `lib/leads.ts`.
 */
export const ACOES: Record<string, string> = {
  DADO_PESSOAL_ACESSADO: 'Dado pessoal acessado',
  QUALIFICACAO_ALTERADA: 'Qualificação alterada',
  HANDOFF_CRIADO: 'Handoff criado',
  OPTOUT_REGISTRADO: 'Opt-out registrado',
  OPTOUT_REATIVADO: 'Opt-out reativado',
  PROMPT_PUBLICADO: 'Prompt publicado',
  ACESSO_NEGADO: 'Acesso negado',
  INJECAO_DETECTADA: 'Injeção detectada',
  CONFIGURACAO_ALTERADA: 'Configuração alterada',
  PROMPT_REVERTIDO: 'Prompt revertido',
  TITULAR_SOLICITOU: 'Titular solicitou',
  DADOS_EXPORTADOS: 'Dados exportados',
  LEAD_ANONIMIZADO: 'Lead anonimizado',
  TITULAR_RECUSADO: 'Titular recusado',
}

/** As entidades (`Entidade` de `domain/auditoria/vocabulario.py`). */
export const ENTIDADES: Record<string, string> = {
  handoff: 'Handoff',
  optout_event: 'Evento de opt-out',
  rota: 'Rota',
  lead_qualification: 'Qualificação do lead',
  configuracao_agente: 'Configuração do agente',
  lead: 'Lead',
  mensagem: 'Mensagem',
  solicitacao_de_titular: 'Solicitação do titular',
}

/** Valor desconhecido aparece como veio -- e anomalia, e o valor cru e a pista. */
export function acaoLegivel(valor: string): string {
  return ACOES[valor] ?? valor
}

export type CategoriaDaAcao = 'risco' | 'alteracao' | 'neutra'

const ACOES_DE_RISCO = new Set(['ACESSO_NEGADO', 'INJECAO_DETECTADA', 'TITULAR_RECUSADO'])
const ACOES_DE_ALTERACAO = new Set([
  'QUALIFICACAO_ALTERADA',
  'CONFIGURACAO_ALTERADA',
  'PROMPT_PUBLICADO',
  'PROMPT_REVERTIDO',
])

/**
 * A cor do selo do tipo de evento (D3 da TEC-399): recusa e risco, alteracao,
 * ou o resto. So reforca -- o texto do selo continua dizendo o tipo. Acao
 * desconhecida cai em `neutra`, como cai no texto cru em `acaoLegivel`.
 */
export function categoriaDaAcao(valor: string): CategoriaDaAcao {
  if (ACOES_DE_RISCO.has(valor)) {
    return 'risco'
  }
  return ACOES_DE_ALTERACAO.has(valor) ? 'alteracao' : 'neutra'
}

export function entidadeLegivel(valor: string): string {
  return ENTIDADES[valor] ?? valor
}

/** Os filtros da trilha (D1, D3 e D4 do desenho). Ausente e "sem filtro". */
export type FiltrosDaTrilha = {
  ator?: string
  acao?: string
  de?: string
  ate?: string
}

/**
 * Onde a trilha esta (D2 do desenho): so "Carregar mais", nunca pagina
 * numerada. `anteriores` sao os cursores ja vistos, na ordem -- toda
 * "proxima pagina" pedida ACUMULA.
 */
export type PosicaoNaTrilha = { cursor?: string; anteriores: string[] }

export const PRIMEIRA_PAGINA: PosicaoNaTrilha = { anteriores: [] }

export type EstadoDaTrilha = { filtros?: FiltrosDaTrilha; posicao?: PosicaoNaTrilha }

/**
 * O endereco da tela com este estado (no molde de `urlDaLista` de `lib/leads.ts`).
 * Mudar filtro chama sem `posicao`: um cursor de uma consulta continuado
 * noutra devolveria uma pagina plausivel e errada.
 */
export function urlDaLista({ filtros = {}, posicao }: EstadoDaTrilha): string {
  const parametros = new URLSearchParams()
  for (const chave of ['ator', 'acao', 'de', 'ate'] as const) {
    const valor = filtros[chave]
    if (valor) {
      parametros.set(chave, valor)
    }
  }
  if (posicao?.cursor) {
    parametros.set('cursor', posicao.cursor)
    for (const anterior of posicao.anteriores) {
      parametros.append('anterior', anterior)
    }
  }
  const texto = parametros.toString()
  return texto ? `/admin/auditoria?${texto}` : '/admin/auditoria'
}

type ParametrosDaUrl = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

function todos(valor: string | string[] | undefined): string[] {
  if (valor === undefined) {
    return []
  }
  return (Array.isArray(valor) ? valor : [valor]).filter(Boolean)
}

/** Os filtros que a URL pede. Tipo desconhecido cai em "sem filtro": o backend
 * recusaria com 422, e a tela nao repassa o que nao sabe mostrar. */
export function filtrosDaUrl(parametros: ParametrosDaUrl): FiltrosDaTrilha {
  const acao = um(parametros.acao)
  return {
    ator: um(parametros.ator) || undefined,
    acao: acao !== undefined && acao in ACOES ? acao : undefined,
    de: um(parametros.de) || undefined,
    ate: um(parametros.ate) || undefined,
  }
}

/** A posicao que a URL pede. Sem `cursor`, e a primeira pagina. */
export function posicaoDaUrl(parametros: ParametrosDaUrl): PosicaoNaTrilha {
  const cursor = um(parametros.cursor)
  if (!cursor) {
    return PRIMEIRA_PAGINA
  }
  return { cursor, anteriores: todos(parametros.anterior) }
}

/** A pagina seguinte: o cursor atual entra em `anteriores` (D2). */
export function posicaoDaProxima(atual: PosicaoNaTrilha, proximo: string): PosicaoNaTrilha {
  return {
    cursor: proximo,
    anteriores: atual.cursor ? [...atual.anteriores, atual.cursor] : [],
  }
}

/**
 * `de`/`ate` da URL sao datas (`aaaa-mm-dd`, o que o `<input type="date">`
 * produz), e o backend exige `datetime` com fuso (D4). `-03:00` fixo: o fuso
 * unico da POC, sem horario de verao desde 2019.
 */
export function inicioDoDia(data: string): string {
  return `${data}T00:00:00-03:00`
}

/**
 * `ate` e o limite EXCLUSIVO (`[de, ate)`): sem virar o dia seguinte,
 * filtrar "ate 30/09" excluiria o proprio dia 30.
 */
export function fimDoDia(data: string): string {
  const [ano, mes, dia] = data.split('-').map(Number)
  const proximoDia = new Date(Date.UTC(ano, mes - 1, dia + 1)).toISOString().slice(0, 10)
  return `${proximoDia}T00:00:00-03:00`
}

const DATA_HORA = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'short',
  timeStyle: 'short',
  timeZone: 'America/Sao_Paulo',
})

/** "26/09/2026, 14:03", no fuso da operacao. */
export function dataHoraLegivel(iso: string): string {
  return DATA_HORA.format(new Date(iso))
}

/** O tipo de ator, legivel; o identificador vai a parte (D4 da TEC-399). */
export const ATORES: Record<string, string> = { USUARIO: 'Usuário', AGENTE: 'Agente', SISTEMA: 'Sistema' }

/** `detalhes` como pares "chave: valor", sem tradução (D6) -- pula os nulos. */
export function detalhesLegiveis(detalhes: Record<string, string | null> | null): string {
  if (!detalhes) {
    return ''
  }
  return Object.entries(detalhes)
    .filter(([, valor]) => valor !== null)
    .map(([chave, valor]) => `${chave}: ${valor}`)
    .join(', ')
}

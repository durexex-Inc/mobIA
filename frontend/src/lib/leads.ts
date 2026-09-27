/**
 * A lista de leads, sem I/O (TEC-321).
 *
 * **Modulo puro de proposito**: a caixa de busca e componente de cliente e
 * precisa de `buscaEfetiva`, e nada que ela importe pode arrastar
 * `server-only`. A chamada ao FastAPI mora em `lib/servidor/leads.ts`.
 */

/** Um item de `GET /api/v1/leads`, como a TEC-192 e a TEC-195 o devolvem. */
export type LeadDaLista = {
  leadId: string
  channel: string
  telefone: string | null
  score: number | null
  temperatura: string | null
  status: string
  regiao: string | null
  intencao: string | null
  qualificadoEm: string | null
  ultimaInteracaoEm: string
}

export type PaginaDeLeads = { itens: LeadDaLista[]; proximoCursor: string | null }

/** Os valores de `ordenar` da secao 6.2 do SRS (Emenda E-02, TEC-321). */
export const ORDENS = ['score_desc', 'ultima_interacao_desc'] as const
export type Ordem = (typeof ORDENS)[number]

/**
 * A ordem pedida na URL, ou a por score.
 *
 * **Aqui o desconhecido cai no padrao, e no backend ele e 422** -- e nao e
 * contradicao. O backend recusa porque quem chama leria a resposta como a
 * ordem pedida. Na tela, a ordem em vigor esta marcada no cabecalho da coluna
 * (`aria-sort`), entao ninguem le a lista numa ordem que nao e a mostrada.
 */
export function ordemDaUrl(valor: string | undefined): Ordem {
  return ORDENS.find((ordem) => ordem === valor) ?? 'score_desc'
}

/** O minimo de caracteres para a busca sair (RN-FE-07.3). */
export const BUSCA_MINIMA = 2

/**
 * A busca que vai ao FastAPI, ou `undefined` quando ela nao deve sair.
 *
 * **A mesma regra vale no cliente e no servidor** (D5 do desenho): a caixa
 * nao navega com um caractere so, e a pagina nao repassa uma `?busca=a` que
 * alguem tenha digitado na URL. O telefone vai como foi digitado -- quem
 * normaliza para a forma canonica e o backend (TEC-192, D3).
 */
export function buscaEfetiva(texto: string | undefined): string | undefined {
  const limpa = texto?.trim()
  return limpa && limpa.length >= BUSCA_MINIMA ? limpa : undefined
}

/**
 * O endereco da lista com esta busca e esta ordem.
 *
 * A ordem padrao nao vai na URL: `/leads` e `/leads?ordenar=score_desc` sao a
 * mesma tela, e um endereco so para ela e o que a pessoa ve e compartilha.
 */
export function urlDaLista({ busca, ordem }: { busca?: string; ordem: Ordem }): string {
  const parametros = new URLSearchParams()
  if (busca) {
    parametros.set('busca', busca)
  }
  if (ordem !== 'score_desc') {
    parametros.set('ordenar', ordem)
  }
  const texto = parametros.toString()
  return texto ? `/leads?${texto}` : '/leads'
}

/**
 * Como a linha identifica o lead: o telefone mascarado (D3 do desenho).
 *
 * Nao ha nome -- nenhuma tabela o guarda (Emenda E-02 da RN-15.1). Sem
 * telefone, a celula diz por que, em vez de ficar vazia, e o motivo depende do
 * canal. No site, e o visitante que nunca digitou o numero. Fora dele, e um
 * numero que o backend nao conseguiu resolver -- visto na verificacao de ponta
 * a ponta, num lead do WhatsApp gravado antes da TEC-203 --, e chama-lo de
 * visitante do site afirmaria um canal que a coluna ao lado desmente.
 */
export function identificacaoDoLead(lead: Pick<LeadDaLista, 'telefone' | 'channel'>): string {
  if (lead.telefone) {
    return lead.telefone
  }
  return lead.channel === 'web' ? 'Visitante do site' : 'Telefone indisponível'
}

const TEMPERATURAS: Record<string, string> = { QUENTE: 'Quente', MORNO: 'Morno', FRIO: 'Frio' }
const STATUS: Record<string, string> = { ATIVA: 'Ativa', ENCERRADA: 'Encerrada' }
const CANAIS: Record<string, string> = { whatsapp: 'WhatsApp', web: 'Site' }

/**
 * Temperatura nula e travessao, e nunca "Frio": o lead ainda nao foi
 * classificado, e isso nao e o mesmo que estar frio. Valor desconhecido
 * aparece como veio, como em `nomeDoPapel`.
 */
export function temperaturaLegivel(valor: string | null): string {
  return valor === null ? '—' : (TEMPERATURAS[valor] ?? valor)
}

export function statusLegivel(valor: string): string {
  return STATUS[valor] ?? valor
}

export function canalLegivel(valor: string): string {
  return CANAIS[valor] ?? valor
}

const RELATIVO = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' })

const ABSOLUTA = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'short',
  timeStyle: 'short',
  timeZone: 'America/Sao_Paulo',
})

const UNIDADES: ReadonlyArray<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

/**
 * "há 5 minutos", calculado contra `agora` (D7 do desenho).
 *
 * Menos de um minuto e "agora": "há 20 segundos" mudaria a cada recarga sem
 * dizer nada que "agora" nao diga.
 */
export function tempoRelativo(iso: string, agora: Date): string {
  const segundos = Math.round((new Date(iso).getTime() - agora.getTime()) / 1000)
  for (const [unidade, tamanho] of UNIDADES) {
    if (Math.abs(segundos) >= tamanho) {
      return RELATIVO.format(Math.trunc(segundos / tamanho), unidade)
    }
  }
  return 'agora'
}

/** "26/09/2026, 14:03", no fuso da operacao, para o `title` do relativo. */
export function dataAbsoluta(iso: string): string {
  return ABSOLUTA.format(new Date(iso))
}

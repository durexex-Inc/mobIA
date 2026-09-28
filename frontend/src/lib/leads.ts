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

/** Os filtros da lista (TEC-322, D5). Ausente e "todos". */
export type FiltrosDaLista = {
  status?: string
  temperatura?: string
  canal?: string
  corretorId?: string
}

/**
 * A origem de uma etapa do funil (TEC-318, D6): `de`/`ate`/`intencao` sao a
 * coorte, `etapa` e o que foi clicado. Separada de `FiltrosDaLista` de
 * proposito -- os quatro campos nao tem controle nenhum em `FiltrosDeLeads`,
 * so chegam pelo link que `Funil.tsx` monta, e misturar os dois tipos
 * confundiria "o que a gerente escolhe na tela" com "de onde ela veio".
 */
export type OrigemDoFunil = { de?: string; ate?: string; intencao?: string; etapa?: string }

/**
 * Onde a lista esta (TEC-322, D2 e D3). A pagina 1 nao tem cursor;
 * `anteriores` sao os cursores das paginas 2 a N-1, na ordem; `acumular` e o
 * "carregar mais", que desenha todas as paginas ate a atual.
 */
export type PosicaoNaLista = { cursor?: string; anteriores: string[]; acumular: boolean }

export type EstadoDaLista = {
  busca?: string
  ordem: Ordem
  filtros?: FiltrosDaLista
  posicao?: PosicaoNaLista
  origemDoFunil?: OrigemDoFunil
}

export const PRIMEIRA_PAGINA: PosicaoNaLista = { anteriores: [], acumular: false }

/**
 * O endereco da lista com este estado (TEC-322, D1).
 *
 * A ordem padrao nao vai na URL: `/leads` e `/leads?ordenar=score_desc` sao a
 * mesma tela, e um endereco so para ela e o que a pessoa ve e compartilha.
 * Quem muda busca, ordem ou filtro chama sem `posicao`: o cursor e de uma
 * consulta, e continua-lo noutra devolveria uma pagina plausivel e errada.
 */
export function urlDaLista({
  busca,
  ordem,
  filtros = {},
  posicao,
  origemDoFunil,
}: EstadoDaLista): string {
  const parametros = new URLSearchParams()
  if (busca) {
    parametros.set('busca', busca)
  }
  if (ordem !== 'score_desc') {
    parametros.set('ordenar', ordem)
  }
  for (const chave of ['status', 'temperatura', 'canal', 'corretorId'] as const) {
    const valor = filtros[chave]
    if (valor) {
      parametros.set(chave, valor)
    }
  }
  // A origem do funil sobrevive a paginacao e a ordenacao (TEC-318, D6): sem
  // isto, "Proxima pagina" ou reordenar por score enquanto se ve a etapa
  // "Recomendado" devolveria silenciosamente a lista INTEIRA.
  for (const chave of ['de', 'ate', 'intencao', 'etapa'] as const) {
    const valor = origemDoFunil?.[chave]
    if (valor) {
      parametros.set(chave, valor)
    }
  }
  if (posicao?.cursor) {
    parametros.set('cursor', posicao.cursor)
    for (const anterior of posicao.anteriores) {
      parametros.append('anterior', anterior)
    }
    if (posicao.acumular) {
      parametros.set('acumular', '1')
    }
  }
  const texto = parametros.toString()
  return texto ? `/leads?${texto}` : '/leads'
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

const FORMA_DE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Os filtros que a URL pede, so os do vocabulario (D1). Valor desconhecido
 * cai em "todos", como a ordem cai na padrao: o backend recusaria `status`
 * fora do vocabulario com 422, e a tela nao repassa o que nao sabe mostrar.
 */
export function filtrosDaUrl(parametros: ParametrosDaUrl): FiltrosDaLista {
  const dentro = (valor: string | undefined, mapa: Record<string, string>) =>
    valor !== undefined && valor in mapa ? valor : undefined
  const corretorId = um(parametros.corretorId)
  return {
    status: dentro(um(parametros.status), STATUS),
    temperatura: dentro(um(parametros.temperatura), TEMPERATURAS),
    canal: dentro(um(parametros.canal), CANAIS),
    corretorId: corretorId && FORMA_DE_UUID.test(corretorId) ? corretorId : undefined,
  }
}

/**
 * A origem do funil que a URL pede, ou `undefined` sem nenhum dos quatro
 * campos (TEC-318). Ao contrario de `filtrosDaUrl`, nao ha vocabulario para
 * validar aqui -- `de`/`ate`/`intencao`/`etapa` sao conferidos pelo backend
 * (o mesmo `montar_recorte` do funil), e a tela so precisa saber se algum
 * deles veio, para preservar os quatro juntos (D6).
 */
export function origemDoFunilDaUrl(parametros: ParametrosDaUrl): OrigemDoFunil | undefined {
  const origem: OrigemDoFunil = {
    de: um(parametros.de),
    ate: um(parametros.ate),
    intencao: um(parametros.intencao),
    etapa: um(parametros.etapa),
  }
  return Object.values(origem).some(Boolean) ? origem : undefined
}

/** A posicao que a URL pede. Sem `cursor`, e a primeira pagina. */
export function posicaoDaUrl(parametros: ParametrosDaUrl): PosicaoNaLista {
  const cursor = um(parametros.cursor)
  if (!cursor) {
    return PRIMEIRA_PAGINA
  }
  return { cursor, anteriores: todos(parametros.anterior), acumular: um(parametros.acumular) === '1' }
}

/** O numero da pagina atual: 1 sem cursor, e depois uma a mais por cursor visto. */
export function numeroDaPagina(posicao: PosicaoNaLista): number {
  return posicao.cursor ? posicao.anteriores.length + 2 : 1
}

/**
 * A pagina seguinte. O cursor atual entra em `anteriores`, e e isso que deixa
 * voltar a ela depois sem o total (D2).
 */
export function posicaoDaProxima(atual: PosicaoNaLista, proximo: string, acumular: boolean): PosicaoNaLista {
  return {
    cursor: proximo,
    anteriores: atual.cursor ? [...atual.anteriores, atual.cursor] : [],
    acumular,
  }
}

/** A posicao da pagina `numero` ja visitada (1 <= numero <= a atual). Nunca acumula. */
export function posicaoDaPagina(atual: PosicaoNaLista, numero: number): PosicaoNaLista {
  if (numero <= 1) {
    return PRIMEIRA_PAGINA
  }
  const todosOsCursores = [...atual.anteriores, ...(atual.cursor ? [atual.cursor] : [])]
  return {
    cursor: todosOsCursores[numero - 2],
    anteriores: todosOsCursores.slice(0, numero - 2),
    acumular: false,
  }
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

/**
 * Os vocabularios dos filtros e das colunas (TEC-322, D5). Exportados porque
 * as listas de filtro saem deles, e `tests/unit/test_vocabulario_da_tela.py`
 * os compara com o backend: `Temperatura`, `Status` da conversa e os canais
 * de `messages/canais.py`.
 */
export const TEMPERATURAS: Record<string, string> = {
  QUENTE: 'Quente',
  MORNO: 'Morno',
  FRIO: 'Frio',
}
export const STATUS: Record<string, string> = {
  ATIVA: 'Ativa',
  ENCERRADA: 'Encerrada',
}
export const CANAIS: Record<string, string> = {
  whatsapp: 'WhatsApp',
  web: 'Site',
}

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

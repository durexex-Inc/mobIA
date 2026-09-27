/**
 * O detalhe do lead, sem I/O (TEC-323).
 *
 * Os tipos sao a forma de `GET /api/v1/leads/{leadId}` (D4 da TEC-193). A
 * chamada mora em `lib/servidor/leads.ts`.
 */

export type ResumoDoLead = {
  handoffId: string
  texto: string
  geradoEm: string | null
  modelo: string | null
  fallback: boolean
}

export type AgendamentoDoLead = {
  id: string
  tipo: string
  inicio: string
  fim: string
  status: string
  imovelId: string | null
}

export type FollowUpDoLead = { tentativa: number; temperatura: string; disparadoEm: string }

/** Um recalculo do score, em ordem cronologica crescente (TEC-325). */
export type RecalculoDoScore = {
  em: string
  anterior: number | null
  novo: number
  fatores: Record<string, number>
  causas: string[]
}

/** Um imovel apresentado ao lead, com a reacao dele (TEC-325). */
export type ImovelRecomendado = {
  imovelId: string
  codigo: string
  titulo: string
  bairro: string
  scoreMatch: number
  motivoMatch: string
  reacao: string | null
  motivoDescarte: string | null
  apresentadoEm: string
}

export type Qualificacao = Record<string, unknown>

/** Quem tem a conversa agora (TEC-327, D2), ou `null` no detalhe. */
export type Atendimento = {
  assumidoPor: { corretorId: string; nome: string }
  assumidoEm: string
}

export type DetalheDoLead = {
  leadId: string
  channel: string
  status: string
  ultimaInteracaoEm: string
  contato: { telefone: string | null; email: string | null }
  score: number | null
  resumo: ResumoDoLead | null
  qualificacao: Qualificacao | null
  agendamentos: AgendamentoDoLead[]
  followups: FollowUpDoLead[]
  historicoScore: RecalculoDoScore[]
  recomendacoes: ImovelRecomendado[]
  atendimento: Atendimento | null
  /** Quando fecha a janela de 24 h do WhatsApp (TEC-328, D2). `null` no site. */
  janelaDeServicoFechaEm: string | null
}

/**
 * Os seis marcadores da TEC-175, e o titulo com que cada um aparece na tela.
 *
 * Os marcadores sao literais sem acento porque o validador de
 * `domain/handoff/resumo.py` os confere assim; o titulo e texto de tela e leva
 * acento (D3 do desenho). Se a TEC-175 mudar um marcador, este corte deixa de
 * reconhecer o texto e a tela o mostra inteiro -- nada some.
 */
const MARCADORES: ReadonlyArray<[string, string]> = [
  ['## Quem e o lead', 'Quem é o lead'],
  ['## O que procura', 'O que procura'],
  ['## Score e temperatura', 'Score e temperatura'],
  ['## Imoveis apresentados', 'Imóveis apresentados'],
  ['## Pontos de atencao', 'Pontos de atenção'],
  ['## Proxima acao', 'Próxima ação'],
]

export type ResumoEmBlocos = { preambulo: string; blocos: { titulo: string; corpo: string }[] }

/**
 * O resumo cortado nos seis blocos, ou `null` quando o texto nao se deixa
 * cortar -- marcador faltando ou fora de ordem.
 *
 * **O preambulo do resumo simplificado some** (D3): e a nota entre colchetes
 * que a TEC-176 poe no comeco do texto para quem o recebe cru, na
 * notificacao. Na tela, a etiqueta "Resumo simplificado" diz o mesmo. No
 * resumo do assistente nao ha preambulo; se houver, ele fica.
 */
export function dividirResumo(texto: string, { fallback }: { fallback: boolean }): ResumoEmBlocos | null {
  const posicoes = MARCADORES.map(([marcador]) => texto.indexOf(marcador))
  if (posicoes.some((posicao, i) => posicao < 0 || (i > 0 && posicao < posicoes[i - 1]))) {
    return null
  }

  const blocos = MARCADORES.map(([marcador, titulo], i) => {
    const fim = i + 1 < posicoes.length ? posicoes[i + 1] : texto.length
    return { titulo, corpo: texto.slice(posicoes[i] + marcador.length, fim).trim() }
  })
  const preambulo = fallback ? '' : texto.slice(0, posicoes[0]).trim()
  return { preambulo, blocos }
}

/**
 * `LONGO_PRAZO` vira "Longo prazo". O que nao tem rotulo proprio aparece assim.
 *
 * Os campos de investidor nao tem vocabulario fechado no backend, e fixar um
 * aqui obrigaria esta tela a acompanhar o agente a cada valor novo.
 */
export function humanizar(valor: string): string {
  const texto = valor.replaceAll('_', ' ').toLowerCase()
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}

function rotuloDe(mapa: Record<string, string>, valor: string): string {
  return mapa[valor] ?? humanizar(valor)
}

const INTENCOES: Record<string, string> = {
  COMPRA: 'Compra',
  ALUGUEL: 'Aluguel',
  INVESTIMENTO: 'Investimento',
  VENDER_IMOVEL: 'Vender imóvel',
  SUPORTE_CONTRATO: 'Suporte a contrato',
  INDEFINIDA: 'Indefinida',
  FORA_DE_ESCOPO: 'Fora de escopo',
}
/**
 * Os tres vocabularios fechados que a correcao da qualificacao edita (TEC-329,
 * D2). Sao os de `agente/schemas.py`, e nao os do catalogo: o `TipoImovel` do
 * catalogo tem `COBERTURA`, que o `PATCH` recusaria. Um teste do lado Python
 * (`tests/unit/test_vocabulario_da_tela.py`) le estes tres mapas e os compara
 * com os enums -- valor novo de um lado so reprova la.
 */
export const TIPOS_DE_IMOVEL: Record<string, string> = {
  APARTAMENTO: 'Apartamento',
  CASA: 'Casa',
  TERRENO: 'Terreno',
  COMERCIAL: 'Comercial',
  RURAL: 'Rural',
}
export const URGENCIAS: Record<string, string> = {
  IMEDIATA: 'Imediata',
  ATE_3_MESES: 'Até 3 meses',
  ATE_6_MESES: 'Até 6 meses',
  SEM_PRESSA: 'Sem pressa',
}
export const FORMAS_DE_PAGAMENTO: Record<string, string> = {
  A_VISTA: 'À vista',
  FINANCIAMENTO: 'Financiamento',
  CONSORCIO: 'Consórcio',
  FGTS: 'FGTS',
  INDEFINIDA: 'Indefinida',
}
/**
 * Os motivos de cada recalculo do score (TEC-325, D4): as constantes
 * `CAUSA_*` de `context/auditoria.py`. O teste do lado Python compara as
 * chaves com elas.
 */
export const CAUSAS_DO_SCORE: Record<string, string> = {
  PRIMEIRO_CALCULO: 'Primeiro cálculo',
  CAMPOS_OBRIGATORIOS: 'Campos da qualificação',
  URGENCIA: 'Urgência',
  CATALOGO: 'Catálogo',
  ENGAJAMENTO: 'Engajamento',
  FORMA_DE_PAGAMENTO: 'Forma de pagamento',
  PENALIDADE: 'Penalidade',
  EDICAO_MANUAL: 'Edição manual',
  RECALCULO_MANUAL: 'Recálculo manual',
  NAO_COMPARECIMENTO: 'Não compareceu à visita',
  MUDANCA_DE_INTENCAO: 'Mudança de intenção',
}

/**
 * A reacao do lead a um imovel (TEC-325, D3): `ReacaoLead`. "Gostei" e
 * "Não é pra mim" sao os rotulos dos botoes do chat web (TEC-350) -- o
 * corretor le a mesma palavra que o lead clicaria.
 */
export const REACOES: Record<string, string> = {
  INTERESSE: 'Gostei',
  DESCARTE: 'Não é pra mim',
  NEUTRO: 'Viu, sem opinar',
  SEM_RESPOSTA: 'Sem resposta',
}

/** Por que o lead descartou (TEC-325, D3): `CategoriaDescarte`. */
export const DESCARTES: Record<string, string> = {
  DISTANCIA: 'distância',
  PRECO: 'preço',
  TAMANHO: 'tamanho',
  OUTRO: 'outro motivo',
}

/** "Gostei", "Não é pra mim · distância", ou "Aguardando reação" sem reação. */
export function reacaoLegivel(reacao: string | null, motivoDescarte: string | null): string {
  if (reacao === null) {
    return 'Aguardando reação'
  }
  const rotulo = rotuloDe(REACOES, reacao)
  if (reacao === 'DESCARTE' && motivoDescarte) {
    return `${rotulo} · ${DESCARTES[motivoDescarte] ?? humanizar(motivoDescarte).toLowerCase()}`
  }
  return rotulo
}

/** Os motivos de um recalculo, em portugues, separados por virgula. */
export function motivosDoRecalculo(causas: string[]): string {
  return causas.map((causa) => rotuloDe(CAUSAS_DO_SCORE, causa)).join(', ')
}

/** O valor de um recalculo: "30 → 47", ou "30" no primeiro. */
export function valorDoRecalculo(recalculo: Pick<RecalculoDoScore, 'anterior' | 'novo'>): string {
  return recalculo.anterior === null ? String(recalculo.novo) : `${recalculo.anterior} → ${recalculo.novo}`
}

/**
 * Os pontos do grafico de linha (D2), numa caixa `largura` x `altura`. O Y vai
 * de 0 a 100 -- o score e limitado a isso -- e o X espaca os pontos por igual:
 * a distancia entre recalculos nao e o que o corretor procura, e os horarios
 * estao na lista. Um ponto so fica no meio.
 */
export function pontosDoGrafico(
  valores: number[],
  { largura, altura, margem }: { largura: number; altura: number; margem: number },
): Array<{ x: number; y: number }> {
  const util = { x: largura - 2 * margem, y: altura - 2 * margem }
  return valores.map((valor, i) => ({
    x: margem + (valores.length === 1 ? util.x / 2 : (util.x * i) / (valores.length - 1)),
    y: margem + util.y * (1 - Math.min(100, Math.max(0, valor)) / 100),
  }))
}

/** O resumo do grafico para leitor de tela: "Score de 30 a 82 em 3 recálculos". */
export function resumoDoGrafico(valores: number[]): string {
  if (valores.length === 1) {
    return `Score ${valores[0]} no único cálculo`
  }
  return `Score de ${valores[0]} a ${valores.at(-1)} em ${valores.length} recálculos`
}

const TIPOS_DE_AGENDAMENTO: Record<string, string> = {
  VISITA_PRESENCIAL: 'Visita presencial',
  REUNIAO_REMOTA: 'Reunião remota',
}
const STATUS_DE_AGENDAMENTO: Record<string, string> = {
  RESERVADO: 'Reservado',
  CONFIRMADO: 'Confirmado',
  EXPIRADO: 'Expirado',
  CANCELADO: 'Cancelado',
  REAGENDADO: 'Reagendado',
  REALIZADO: 'Realizado',
  NO_SHOW: 'Não compareceu',
}

export function tipoDoAgendamento(valor: string): string {
  return rotuloDe(TIPOS_DE_AGENDAMENTO, valor)
}

export function statusDoAgendamento(valor: string): string {
  return rotuloDe(STATUS_DE_AGENDAMENTO, valor)
}

const REAIS = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  maximumFractionDigits: 0,
})

function reais(centavos: number): string {
  // O `Intl` separa "R$" do numero com espaco inseparavel; o espaco comum e o
  // que o resto da tela usa, e o que um teste consegue escrever.
  return REAIS.format(centavos / 100).replace(/ /g, ' ')
}

/** A faixa de preco em reais. Nula quando o lead nao disse nenhum dos dois. */
export function faixaDePreco(min: number | null, max: number | null): string | null {
  if (min !== null && max !== null) {
    return `${reais(min)} a ${reais(max)}`
  }
  if (min !== null) {
    return `a partir de ${reais(min)}`
  }
  if (max !== null) {
    return `até ${reais(max)}`
  }
  return null
}

export const NAO_INFORMADO = 'Não informado'

type Linha = { rotulo: string; valor: string }

function texto(valor: unknown, mapa?: Record<string, string>): string | null {
  if (valor === null || valor === undefined || valor === '') {
    return null
  }
  if (typeof valor === 'boolean') {
    return valor ? 'Sim' : 'Não'
  }
  if (typeof valor === 'string' && mapa) {
    return rotuloDe(mapa, valor)
  }
  return String(valor)
}

function numero(valor: unknown): number | null {
  return typeof valor === 'number' ? valor : null
}

/** Os campos de investidor, em ordem. So aparecem se algum estiver preenchido (D6). */
const DE_INVESTIDOR: ReadonlyArray<[string, string]> = [
  ['ticketInvestimentoCentavos', 'Ticket de investimento'],
  ['retornoEsperadoPct', 'Retorno esperado'],
  ['retornoEsperadoTipo', 'Tipo de retorno'],
  ['horizonte', 'Horizonte'],
  ['toleranciaReforma', 'Tolerância a reforma'],
  ['jaInvesteEmImoveis', 'Já investe em imóveis'],
  ['perfilInvestidor', 'Perfil de investidor'],
]

/**
 * As linhas da qualificacao, na ordem da tela (D6 do desenho).
 *
 * **Os campos-base aparecem sempre, com "Nao informado"**: o que falta e o
 * que o corretor tem de perguntar na ligacao. Os de investidor so aparecem
 * quando algum esta preenchido -- para quem compra para morar, seriam sete
 * linhas de ausencia.
 */
export function linhasDaQualificacao(q: Qualificacao): Linha[] {
  const base: Array<[string, string | null]> = [
    ['Intenção', texto(q.intencao, INTENCOES)],
    ['Região', texto(q.regiao)],
    ['Tipo de imóvel', texto(q.tipoImovel, TIPOS_DE_IMOVEL)],
    ['Quartos', texto(q.quartos)],
    ['Vagas', texto(q.vagas)],
    [
      'Faixa de preço',
      faixaDePreco(numero(q.faixaPrecoMinCentavos), numero(q.faixaPrecoMaxCentavos)),
    ],
    ['Urgência', texto(q.urgencia, URGENCIAS)],
    ['Forma de pagamento', texto(q.formaPagamento, FORMAS_DE_PAGAMENTO)],
    ['Tem imóvel para vender', texto(q.temImovelParaVender)],
  ]
  const linhas: Linha[] = base.map(([rotulo, valor]) => ({ rotulo, valor: valor ?? NAO_INFORMADO }))

  if (DE_INVESTIDOR.some(([campo]) => texto(q[campo]) !== null)) {
    for (const [campo, rotulo] of DE_INVESTIDOR) {
      const bruto = q[campo]
      let valor: string | null
      if (campo === 'ticketInvestimentoCentavos') {
        valor = numero(bruto) === null ? null : reais(numero(bruto) as number)
      } else if (campo === 'retornoEsperadoPct') {
        valor = numero(bruto) === null ? null : `${String(bruto).replace('.', ',')}%`
      } else {
        valor = typeof bruto === 'string' ? humanizar(bruto) : texto(bruto)
      }
      linhas.push({ rotulo, valor: valor ?? NAO_INFORMADO })
    }
  }

  // Recusa e fato diferente de "ainda nao perguntado" (TEC-148): linha propria,
  // e so quando houve recusa.
  const recusados = Array.isArray(q.camposRecusados) ? (q.camposRecusados as string[]) : []
  if (recusados.length > 0) {
    linhas.push({ rotulo: 'Recusou informar', valor: recusados.join(', ') })
  }
  return linhas
}

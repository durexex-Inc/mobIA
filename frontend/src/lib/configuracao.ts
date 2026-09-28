/**
 * Configurar tom, pesos do score, cadencia de follow-up e orcamento, sem I/O
 * (TEC-337).
 *
 * O formulario guarda TEXTO -- o que um `<input>` devolve --, e este modulo
 * traduz nos dois sentidos: da configuracao vigente para o formulario, e da
 * diferenca do formulario para o corpo do `PATCH`
 * (`api/routes/configuracao.py::PedidoDeAlteracao`). Mesmo molde de
 * `lib/imoveis.ts`.
 *
 * **Fora de escopo (decisao previa do desenho): `corPrimaria`, `posicaoDoBotao`
 * e `dominiosDoChat`.** Eles existem na mesma resposta de `GET`/`PATCH`, mas
 * pertencem a tela de aparencia do widget (TEC-344/345) -- `Configuracao`
 * inclui os tres porque a API os traz, mas `Formulario` nao tem lugar para
 * eles, e `pedidoDeEdicao` nunca os escreve no corpo.
 *
 * **D2 do desenho: as faixas de validacao vem de `limites`, nunca hardcoded.**
 * `GET /agente` devolve `_LIMITES` do backend exatamente para a tela nao
 * guardar uma segunda copia -- por isso `validarFormulario` recebe `Limites`
 * como parametro, ao inves de ter os numeros escritos aqui.
 *
 * **D3 do desenho: a cadencia e uma grade de campos fixos.** A quantidade de
 * intervalos por temperatura vem de `limites.cadencia.tentativasPorTemperatura`,
 * e a validacao do cliente e so "campo vazio" -- faixa e "crescente" sao do
 * backend, cuja mensagem (uma STRING so) e mostrada como veio.
 */

/** `domain/configuracao/vigente.py::Tom`. */
export type Tom = 'CORDIAL' | 'FORMAL' | 'DESCONTRAIDO'

/**
 * O vocabulario fixo de `domain/context/temperatura.py::Temperatura` -- QUENTE
 * (lead quente), MORNO, FRIO, nessa ordem. Nao e um limite a buscar (D2): e a
 * ORDEM de iteracao das linhas da grade de cadencia, que a propria D3 do
 * desenho permite hardcoded porque a quantidade de valores e fixa no enum,
 * nao um numero de configuracao.
 */
export const TEMPERATURAS = ['QUENTE', 'MORNO', 'FRIO'] as const

/**
 * A configuracao como a API devolve (`_na_api(como_plano(...))`): camelCase,
 * cadencia em HORAS por temperatura. `corPrimaria`/`posicaoDoBotao`/
 * `dominiosDoChat` existem no tipo porque a resposta os traz, mesmo que o
 * formulario desta tela nao os edite.
 */
export type Configuracao = {
  nomeDoAssistente: string | null
  tom: Tom
  tetoDePerguntas: number
  pesoCompletude: number
  pesoUrgencia: number
  pesoCatalogo: number
  pesoEngajamento: number
  pesoCapacidade: number
  cadencia: Record<string, number[]>
  orcamentoMensalUsd: string | null
  corPrimaria: string
  posicaoDoBotao: string
  dominiosDoChat: string[]
}

/** `_LIMITES` de `api/routes/configuracao.py`, tal como `GET /agente` devolve. */
export type Limites = {
  nomeDoAssistente: { maximoDeCaracteres: number; nulavel: boolean }
  tom: { valores: Tom[] }
  tetoDePerguntas: { minimo: number; maximo: number }
  pesos: { minimo: number; maximo: number; somaMaxima: number }
  cadencia: {
    tentativasPorTemperatura: Record<string, number>
    horaMinima: number
    horaMaxima: number
  }
  orcamentoMensalUsd: { minimo: string; maximo: string; nulavel: boolean }
  corPrimaria: unknown
  posicaoDoBotao: unknown
  dominiosDoChat: unknown
}

/** `GET /agente/historico::itens[]`. */
export type EntradaDoHistorico = {
  id: string
  autor: string
  em: string
  mudancas: Array<{ campo: string; anterior: unknown; novo: unknown }>
}

/** Os cinco pesos, na ordem que a tela mostra. */
export const PESOS = [
  'pesoCompletude',
  'pesoUrgencia',
  'pesoCatalogo',
  'pesoEngajamento',
  'pesoCapacidade',
] as const

/**
 * Os campos do formulario -- so os sete que esta tela edita (decisao previa do
 * desenho). Pesos, teto de perguntas e orcamento ficam como TEXTO: e o que um
 * `<input>` devolve, e a conversao para numero/decimal so acontece na hora do
 * pedido. A cadencia e um array de strings POR TEMPERATURA -- uma por campo da
 * grade.
 */
export type Formulario = {
  nomeDoAssistente: string
  tom: Tom | ''
  tetoDePerguntas: string
  pesoCompletude: string
  pesoUrgencia: string
  pesoCatalogo: string
  pesoEngajamento: string
  pesoCapacidade: string
  cadencia: Record<string, string[]>
  orcamentoMensalUsd: string
}

/** Os rotulos por campo, reusados pelo diff de confirmacao e pelo historico. */
export const ROTULOS_DE_CAMPO: Record<string, string> = {
  nomeDoAssistente: 'Nome do assistente',
  tom: 'Tom',
  tetoDePerguntas: 'Teto de perguntas',
  pesoCompletude: 'Peso de completude',
  pesoUrgencia: 'Peso de urgência',
  pesoCatalogo: 'Peso de catálogo',
  pesoEngajamento: 'Peso de engajamento',
  pesoCapacidade: 'Peso de capacidade',
  cadencia: 'Cadência',
  orcamentoMensalUsd: 'Orçamento mensal (USD)',
}

export function rotuloDeCampo(campo: string): string {
  return ROTULOS_DE_CAMPO[campo] ?? campo
}

/** O formulario a partir da configuracao vigente -- so os sete campos desta tela. */
export function formularioDe(configuracao: Configuracao): Formulario {
  const cadencia: Record<string, string[]> = {}
  for (const [temperatura, horas] of Object.entries(configuracao.cadencia)) {
    cadencia[temperatura] = horas.map((hora) => String(hora))
  }
  return {
    nomeDoAssistente: configuracao.nomeDoAssistente ?? '',
    tom: configuracao.tom,
    tetoDePerguntas: String(configuracao.tetoDePerguntas),
    pesoCompletude: String(configuracao.pesoCompletude),
    pesoUrgencia: String(configuracao.pesoUrgencia),
    pesoCatalogo: String(configuracao.pesoCatalogo),
    pesoEngajamento: String(configuracao.pesoEngajamento),
    pesoCapacidade: String(configuracao.pesoCapacidade),
    cadencia,
    orcamentoMensalUsd: configuracao.orcamentoMensalUsd ?? '',
  }
}

export type Recusa = {
  /** Mensagem ao lado de cada campo -- so a validacao do cliente preenche isto. */
  porCampo: Partial<Record<keyof Formulario, string>>
  /** Mensagem do topo do formulario: a `string` do backend, mostrada inteira. */
  geral: string | null
}

const SEM_ERRO: Recusa = { porCampo: {}, geral: null }

/**
 * A validacao do lado do cliente (D2 do desenho): as faixas vem de `limites`,
 * nunca de numero escrito aqui. A cadencia so confere "campo vazio" -- faixa e
 * "crescente" sao do backend (D3).
 */
export function validarFormulario(formulario: Formulario, limites: Limites): Recusa {
  const porCampo: Partial<Record<keyof Formulario, string>> = {}

  if (formulario.nomeDoAssistente.length > limites.nomeDoAssistente.maximoDeCaracteres) {
    porCampo.nomeDoAssistente = `No máximo ${limites.nomeDoAssistente.maximoDeCaracteres} caracteres.`
  }

  if (!formulario.tom) {
    porCampo.tom = 'Escolha o tom.'
  }

  const teto = Number(formulario.tetoDePerguntas)
  if (
    !formulario.tetoDePerguntas.trim() ||
    Number.isNaN(teto) ||
    teto < limites.tetoDePerguntas.minimo ||
    teto > limites.tetoDePerguntas.maximo
  ) {
    porCampo.tetoDePerguntas = `Entre ${limites.tetoDePerguntas.minimo} e ${limites.tetoDePerguntas.maximo}.`
  }

  for (const campo of PESOS) {
    const valor = Number(formulario[campo])
    if (
      !formulario[campo].trim() ||
      Number.isNaN(valor) ||
      valor < limites.pesos.minimo ||
      valor > limites.pesos.maximo
    ) {
      porCampo[campo] = `Entre ${limites.pesos.minimo} e ${limites.pesos.maximo}.`
    }
  }

  for (const horas of Object.values(formulario.cadencia)) {
    if (horas.some((valor) => !valor.trim())) {
      porCampo.cadencia = 'Preencha todos os intervalos da cadência.'
      break
    }
  }

  const orcamento = formulario.orcamentoMensalUsd.trim()
  if (orcamento) {
    const valor = Number(orcamento)
    const minimo = Number(limites.orcamentoMensalUsd.minimo)
    const maximo = Number(limites.orcamentoMensalUsd.maximo)
    if (Number.isNaN(valor) || valor < minimo || valor > maximo) {
      porCampo.orcamentoMensalUsd = `Entre ${limites.orcamentoMensalUsd.minimo} e ${limites.orcamentoMensalUsd.maximo}.`
    }
  }

  return { porCampo, geral: null }
}

export function formularioValido(formulario: Formulario, limites: Limites): boolean {
  return Object.keys(validarFormulario(formulario, limites).porCampo).length === 0
}

export type LinhaDoDiff = {
  campo: keyof Formulario
  rotulo: string
  de: string
  para: string
}

const CAMPOS_SIMPLES = [
  'nomeDoAssistente',
  'tom',
  'tetoDePerguntas',
  ...PESOS,
  'orcamentoMensalUsd',
] as const satisfies ReadonlyArray<Exclude<keyof Formulario, 'cadencia'>>

/**
 * O diff de confirmacao (D4 do desenho): so o que mudou, com o texto tal como
 * o campo aparece no formulario -- sem reformatar peso/hora/dinheiro de um
 * jeito e o formulario de outro.
 *
 * A cadencia entra por TEMPERATURA -- "Cadência (QUENTE)" -- porque e assim
 * que a grade a mostra, mesmo que o `PATCH` (`pedidoDeEdicao`) mande o objeto
 * inteiro quando qualquer uma mudar (o backend valida as tres juntas).
 */
export function diffDe(inicial: Formulario, atual: Formulario): LinhaDoDiff[] {
  const linhas: LinhaDoDiff[] = []

  for (const campo of CAMPOS_SIMPLES) {
    const de = String(inicial[campo])
    const para = String(atual[campo])
    if (de !== para) {
      linhas.push({ campo, rotulo: rotuloDeCampo(campo), de, para })
    }
  }

  for (const temperatura of Object.keys(atual.cadencia)) {
    const de = (inicial.cadencia[temperatura] ?? []).join(', ')
    const para = (atual.cadencia[temperatura] ?? []).join(', ')
    if (de !== para) {
      linhas.push({
        campo: 'cadencia',
        rotulo: `${rotuloDeCampo('cadencia')} (${temperatura})`,
        de,
        para,
      })
    }
  }

  return linhas
}

function mesmaListaDeStrings(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((item, i) => item === b[i])
}

/**
 * O corpo do `PATCH` (`PedidoDeAlteracao`): so o que mudou (`exclude_unset`),
 * mesmo molde de `lib/imoveis.ts::pedidoDeEdicao`.
 *
 * **A cadencia vai INTEIRA quando qualquer temperatura muda.** `vigente.aplicar`
 * substitui o dict todo -- mandar so a temperatura alterada faria as outras
 * desaparecerem da vigente nova, e `vigente.validar` recusaria com "precisa de
 * exatamente N intervalos" para elas.
 *
 * **Nunca inclui `seVersao`**: e o token de concorrencia, nao um campo do
 * formulario -- quem chama acrescenta antes de mandar (D1 do desenho).
 */
export function pedidoDeEdicao(inicial: Formulario, atual: Formulario): Record<string, unknown> {
  const corpo: Record<string, unknown> = {}

  const nomeAtual = atual.nomeDoAssistente.trim()
  if (inicial.nomeDoAssistente.trim() !== nomeAtual) {
    corpo.nomeDoAssistente = nomeAtual ? nomeAtual : null
  }
  if (inicial.tom !== atual.tom) {
    corpo.tom = atual.tom
  }
  if (inicial.tetoDePerguntas !== atual.tetoDePerguntas) {
    corpo.tetoDePerguntas = Number(atual.tetoDePerguntas)
  }
  for (const campo of PESOS) {
    if (inicial[campo] !== atual[campo]) {
      corpo[campo] = Number(atual[campo])
    }
  }

  const cadenciaMudou = Object.keys(atual.cadencia).some(
    (temperatura) =>
      !mesmaListaDeStrings(inicial.cadencia[temperatura] ?? [], atual.cadencia[temperatura] ?? []),
  )
  if (cadenciaMudou) {
    corpo.cadencia = Object.fromEntries(
      Object.entries(atual.cadencia).map(([temperatura, horas]) => [
        temperatura,
        horas.map((hora) => Number(hora)),
      ]),
    )
  }

  const orcamentoAtual = atual.orcamentoMensalUsd.trim()
  if (inicial.orcamentoMensalUsd.trim() !== orcamentoAtual) {
    corpo.orcamentoMensalUsd = orcamentoAtual ? orcamentoAtual : null
  }

  return corpo
}

export function estaSujo(inicial: Formulario, atual: Formulario): boolean {
  return diffDe(inicial, atual).length > 0
}

/**
 * O que dizer quando o backend recusa. Mesmo molde de `lib/imoveis.ts::recusaDe`,
 * mais o 409 do controle de concorrencia (D1/D5 do desenho): `conflitoDeVersao`
 * distingue esse caso para o componente mostrar "Recarregar" em vez do aviso
 * generico de "tente de novo".
 */
export function recusaDe(status: number, detail: unknown): Recusa & { conflitoDeVersao?: boolean } {
  if (status === 401) {
    return { porCampo: {}, geral: 'Sua sessão terminou. Recarregue a página para entrar de novo.' }
  }
  if (status === 403) {
    return { porCampo: {}, geral: 'Você não tem permissão para configurar o agente.' }
  }
  if (status === 409 && typeof detail === 'string') {
    return { porCampo: {}, geral: detail, conflitoDeVersao: true }
  }
  if (status === 422 && typeof detail === 'string') {
    return { porCampo: {}, geral: detail }
  }
  return { porCampo: {}, geral: 'Não foi possível salvar. Tente de novo.' }
}

/**
 * O valor de uma entrada do historico, para exibicao (`GET /agente/historico`).
 * `null`/`undefined` vira um traco -- "nenhum" e um valor legitimo em alguns
 * campos (nome, orcamento). A cadencia chega como objeto (`{QUENTE: [2,24,...]}`);
 * os demais campos chegam como numero, string ou booleano, e `String()` basta.
 */
export function formatarValorDoHistorico(valor: unknown): string {
  if (valor === null || valor === undefined) {
    return '—'
  }
  if (typeof valor === 'object' && !Array.isArray(valor)) {
    return Object.entries(valor as Record<string, unknown>)
      .map(([temperatura, horas]) => `${temperatura}: ${Array.isArray(horas) ? horas.join(', ') : String(horas)}`)
      .join('; ')
  }
  return String(valor)
}

export { SEM_ERRO as SEM_RECUSA }

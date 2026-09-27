/**
 * A correcao da qualificacao, sem I/O (TEC-329).
 *
 * O formulario guarda TEXTO -- e o que um `<input>` e um `<select>` devolvem
 * --, e este modulo traduz nos dois sentidos: da ficha do detalhe para o
 * formulario, e da diferenca do formulario para o corpo do
 * `PATCH /leads/{leadId}/qualificacao` (D3 do desenho). A leitura do 422 mora
 * aqui pela mesma razao: e regra, e se testa sem montar componente.
 */
import type { Qualificacao } from '@/lib/detalhe'

/**
 * Os campos do formulario. Os nomes sao os da API, menos a faixa de preco,
 * que a tela digita em reais e a API recebe em centavos.
 */
export type Formulario = {
  regiao: string
  tipoImovel: string
  quartos: string
  vagas: string
  precoMinReais: string
  precoMaxReais: string
  urgencia: string
  formaPagamento: string
  /** `''` e "nao informado"; `'true'` e `'false'` sao o booleano. */
  temImovelParaVender: string
}

export type CampoDoFormulario = keyof Formulario

const CAMPOS: readonly CampoDoFormulario[] = [
  'regiao',
  'tipoImovel',
  'quartos',
  'vagas',
  'precoMinReais',
  'precoMaxReais',
  'urgencia',
  'formaPagamento',
  'temImovelParaVender',
]

/** O nome do campo no corpo do `PATCH`, e no `loc` do 422. */
const NA_API: Record<CampoDoFormulario, string> = {
  regiao: 'regiao',
  tipoImovel: 'tipoImovel',
  quartos: 'quartos',
  vagas: 'vagas',
  precoMinReais: 'faixaPrecoMinCentavos',
  precoMaxReais: 'faixaPrecoMaxCentavos',
  urgencia: 'urgencia',
  formaPagamento: 'formaPagamento',
  temImovelParaVender: 'temImovelParaVender',
}

const DA_API: Record<string, CampoDoFormulario> = Object.fromEntries(
  CAMPOS.map((campo) => [NA_API[campo], campo]),
)

function comoTexto(valor: unknown): string {
  return typeof valor === 'string' || typeof valor === 'number' ? String(valor) : ''
}

function reaisDe(centavos: unknown): string {
  return typeof centavos === 'number' ? String(Math.round(centavos / 100)) : ''
}

/** O formulario preenchido com a ficha atual. Sem ficha, tudo vazio. */
export function formularioDe(q: Qualificacao | null): Formulario {
  const ficha = q ?? {}
  return {
    regiao: comoTexto(ficha.regiao),
    tipoImovel: comoTexto(ficha.tipoImovel),
    quartos: comoTexto(ficha.quartos),
    vagas: comoTexto(ficha.vagas),
    precoMinReais: reaisDe(ficha.faixaPrecoMinCentavos),
    precoMaxReais: reaisDe(ficha.faixaPrecoMaxCentavos),
    urgencia: comoTexto(ficha.urgencia),
    formaPagamento: comoTexto(ficha.formaPagamento),
    temImovelParaVender:
      typeof ficha.temImovelParaVender === 'boolean' ? String(ficha.temImovelParaVender) : '',
  }
}

function valorNaApi(campo: CampoDoFormulario, texto: string): unknown {
  const limpo = texto.trim()
  if (limpo === '') {
    return null
  }
  switch (campo) {
    case 'quartos':
    case 'vagas':
      return Number(limpo)
    case 'precoMinReais':
    case 'precoMaxReais':
      return Math.round(Number(limpo) * 100)
    case 'temImovelParaVender':
      return limpo === 'true'
    default:
      return limpo
  }
}

/**
 * O corpo do `PATCH`: SO o que mudou em relacao ao formulario de partida.
 *
 * Comparar com o formulario, e nao com a ficha, e o que impede um campo
 * intocado de ir: `500000,50` reais viram `500001` no formulario, e mandar
 * isso de volta registraria na trilha uma edicao que ninguem fez. Esvaziar
 * vai como `null`, que no `PATCH` e "limpa"; ausente e "nao muda".
 */
export function pedidoDaEdicao(inicial: Formulario, atual: Formulario): Record<string, unknown> {
  const corpo: Record<string, unknown> = {}
  for (const campo of CAMPOS) {
    if (inicial[campo].trim() !== atual[campo].trim()) {
      corpo[NA_API[campo]] = valorNaApi(campo, atual[campo])
    }
  }
  return corpo
}

export function estaSujo(inicial: Formulario, atual: Formulario): boolean {
  return Object.keys(pedidoDaEdicao(inicial, atual)).length > 0
}

export type Recusa = {
  /** Mensagem ao lado de cada campo que o backend apontou. */
  porCampo: Partial<Record<CampoDoFormulario, string>>
  /** Mensagem do topo do formulario, quando a recusa nao e de um campo. */
  geral: string | null
}

type ErroDoPydantic = { type?: unknown; loc?: unknown; msg?: unknown; ctx?: unknown }

function traducao(erro: ErroDoPydantic): string {
  const ctx = (typeof erro.ctx === 'object' && erro.ctx !== null ? erro.ctx : {}) as Record<
    string,
    unknown
  >
  switch (erro.type) {
    case 'less_than_equal':
      return `Deve ser no máximo ${String(ctx.le)}.`
    case 'greater_than_equal':
      return `Deve ser no mínimo ${String(ctx.ge)}.`
    case 'string_too_long':
      return `Use até ${String(ctx.max_length)} caracteres.`
    case 'enum':
      return 'Escolha um valor da lista.'
    case 'int_parsing':
    case 'int_from_float':
    case 'int_type':
      return 'Informe um número inteiro.'
    default:
      return typeof erro.msg === 'string' ? erro.msg : 'Valor recusado.'
  }
}

/**
 * O que dizer quando o backend recusa (D5 do desenho).
 *
 * O 422 tem duas formas. A do pydantic e uma lista com `loc: ["body",
 * "<campo>"]`, e cada erro vai para o campo que ele aponta. A de dominio e a
 * string `faixa_invertida`, conferida contra o que ja estava gravado, e vai
 * para a faixa de preco: nao ha um campo so a culpar.
 */
export function recusaDe(status: number, detail: unknown): Recusa {
  if (status === 422 && detail === 'faixa_invertida') {
    return {
      porCampo: { precoMinReais: 'O valor mínimo não pode passar do máximo.' },
      geral: null,
    }
  }
  if (status === 422 && Array.isArray(detail)) {
    const porCampo: Partial<Record<CampoDoFormulario, string>> = {}
    const soltos: string[] = []
    for (const erro of detail as ErroDoPydantic[]) {
      const loc = Array.isArray(erro.loc) ? erro.loc : []
      const campo = typeof loc[1] === 'string' ? DA_API[loc[1]] : undefined
      if (campo) {
        porCampo[campo] ??= traducao(erro)
      } else {
        soltos.push(traducao(erro))
      }
    }
    return { porCampo, geral: soltos.length > 0 ? soltos.join(' ') : null }
  }
  if (status === 409 && detail === 'conversa_encerrada') {
    return {
      porCampo: {},
      geral: 'A conversa foi encerrada: a qualificação não pode mais ser editada.',
    }
  }
  if (status === 401) {
    return { porCampo: {}, geral: 'Sua sessão terminou. Recarregue a página para entrar de novo.' }
  }
  if (status === 403) {
    return { porCampo: {}, geral: 'Você não tem permissão para editar este lead.' }
  }
  if (status === 404) {
    return { porCampo: {}, geral: 'Este lead não existe mais.' }
  }
  return { porCampo: {}, geral: 'Não foi possível salvar. Tente de novo.' }
}

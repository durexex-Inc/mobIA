/**
 * Cadastrar, editar e desativar corretores, sem I/O (TEC-332).
 *
 * O formulario guarda TEXTO -- o que um `<input>` devolve --, e este modulo
 * traduz nos dois sentidos: da ficha do corretor para o formulario, e da
 * diferenca do formulario para o corpo do `POST`/`PATCH`
 * (`api/routes/corretores.py::CorretorNovo` e `::CorretorEditado`). A leitura
 * do 409 de e-mail duplicado mora aqui pela mesma razao que `recusaDe` mora em
 * `lib/qualificacao.ts`: e regra, e se testa sem montar componente.
 *
 * D4 do desenho: `gerente` nao aparece no formulario. Nunca vai no corpo do
 * `POST` nem no do `PATCH` -- o backend grava o default dele (`false`) em
 * todo cadastro feito por esta tela.
 */

/** As quatro especialidades da card (`domain/corretores/vocabulario.py::Especialidade`). */
export type Especialidade = 'COMPRA' | 'ALUGUEL' | 'INVESTIMENTO' | 'INVESTIMENTO_ALTO_TICKET'

export const ESPECIALIDADES: Record<Especialidade, string> = {
  COMPRA: 'Compra',
  ALUGUEL: 'Aluguel',
  INVESTIMENTO: 'Investimento',
  INVESTIMENTO_ALTO_TICKET: 'Investimento alto ticket',
}

/**
 * A jornada e uma janela so, em hora inteira (D1 do desenho) -- nao "por dia
 * da semana", que a card pede mas o backend nao tem
 * (`vocabulario.py::HORA_MINIMA`/`HORA_MAXIMA`).
 */
export const HORA_MINIMA = 0
export const HORA_MAXIMA = 23

export const CAPACIDADE_MINIMA = 1

/**
 * O teto que so existe nesta tela (D3 do desenho). O backend so garante
 * `capacidade_diaria >= CAPACIDADE_MINIMA`
 * (`vocabulario.py::CAPACIDADE_MINIMA`) -- nao ha teto de 20 em lugar nenhum
 * do backend. Uma chamada direta a API ainda grava capacidade > 20.
 */
export const CAPACIDADE_MAXIMA = 20

export type Corretor = {
  id: string
  nome: string
  email: string
  telefone: string
  creci: string | null
  especialidades: Especialidade[]
  regioesAtuacao: string[]
  horarioInicio: number
  horarioFim: number
  capacidadeDiaria: number
  plantao: boolean
  gerente: boolean
  ativo: boolean
}

/**
 * Os campos do formulario. `especialidades`/`regioesAtuacao`/`plantao` ja
 * ficam no tipo final (checkbox e lista, nao texto de `<input>`); os demais
 * ficam como texto, no mesmo molde de `Formulario` em `lib/qualificacao.ts`.
 * `gerente` fica de fora de proposito (D4): esta tela nunca le nem escreve
 * esse campo.
 */
export type Formulario = {
  nome: string
  email: string
  telefone: string
  creci: string
  especialidades: Especialidade[]
  regioesAtuacao: string[]
  horarioInicio: string
  horarioFim: string
  capacidadeDiaria: string
  plantao: boolean
}

/** Os campos de texto/numero -- os unicos que os campos de formulario editam por string. */
export type CampoDeTexto =
  | 'nome'
  | 'email'
  | 'telefone'
  | 'creci'
  | 'horarioInicio'
  | 'horarioFim'
  | 'capacidadeDiaria'

const VAZIO: Formulario = {
  nome: '',
  email: '',
  telefone: '',
  creci: '',
  especialidades: [],
  regioesAtuacao: [],
  horarioInicio: '',
  horarioFim: '',
  capacidadeDiaria: '',
  plantao: false,
}

/**
 * O formulario a partir do corretor -- ou vazio, para o cadastro
 * (`corretor === null`).
 */
export function formularioDe(corretor: Corretor | null): Formulario {
  if (!corretor) {
    return { ...VAZIO }
  }
  return {
    nome: corretor.nome,
    email: corretor.email,
    telefone: corretor.telefone,
    creci: corretor.creci ?? '',
    especialidades: [...corretor.especialidades],
    regioesAtuacao: [...corretor.regioesAtuacao],
    horarioInicio: String(corretor.horarioInicio),
    horarioFim: String(corretor.horarioFim),
    capacidadeDiaria: String(corretor.capacidadeDiaria),
    plantao: corretor.plantao,
  }
}

function mesmaLista(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((item, i) => item === b[i])
}

export type Recusa = {
  /** Mensagem ao lado de cada campo. As chaves sao as de `Formulario`. */
  porCampo: Partial<Record<keyof Formulario, string>>
  /** Mensagem do topo do formulario, quando a recusa nao e de um campo. */
  geral: string | null
}

const SEM_ERRO: Recusa = { porCampo: {}, geral: null }

/**
 * A validacao do lado do cliente (D3 do desenho): a faixa 1-20 da
 * capacidade so existe aqui, e por isso e checada antes do `fetch`, e nao so
 * pelo `min`/`max` do `<input type="number">` -- um envio disparado por
 * teclado com o campo invalido ainda passaria pelo HTML sem esta checagem.
 */
export function validarFormulario(formulario: Formulario): Recusa {
  const porCampo: Partial<Record<keyof Formulario, string>> = {}

  if (!formulario.nome.trim()) {
    porCampo.nome = 'Informe o nome.'
  }
  if (!formulario.email.trim()) {
    porCampo.email = 'Informe o e-mail.'
  }
  if (!formulario.telefone.trim()) {
    porCampo.telefone = 'Informe o telefone.'
  }
  if (formulario.especialidades.length === 0) {
    porCampo.especialidades = 'Escolha ao menos uma especialidade.'
  }
  if (formulario.regioesAtuacao.filter((regiao) => regiao.trim()).length === 0) {
    porCampo.regioesAtuacao = 'Informe ao menos uma região.'
  }

  const inicio = Number(formulario.horarioInicio)
  const fim = Number(formulario.horarioFim)
  const jornadaValida =
    formulario.horarioInicio.trim() !== '' &&
    formulario.horarioFim.trim() !== '' &&
    Number.isInteger(inicio) &&
    Number.isInteger(fim) &&
    inicio >= HORA_MINIMA &&
    fim <= HORA_MAXIMA &&
    inicio < fim
  if (!jornadaValida) {
    porCampo.horarioFim = 'Informe um horário válido, com o início antes do fim.'
  }

  const capacidade = Number(formulario.capacidadeDiaria)
  const capacidadeValida =
    formulario.capacidadeDiaria.trim() !== '' &&
    Number.isInteger(capacidade) &&
    capacidade >= CAPACIDADE_MINIMA &&
    capacidade <= CAPACIDADE_MAXIMA
  if (!capacidadeValida) {
    porCampo.capacidadeDiaria = `Informe um número entre ${CAPACIDADE_MINIMA} e ${CAPACIDADE_MAXIMA}.`
  }

  return { porCampo, geral: null }
}

export function formularioValido(formulario: Formulario): boolean {
  return Object.keys(validarFormulario(formulario).porCampo).length === 0
}

/**
 * O corpo do `POST` de cadastro (`CorretorNovo`). Sempre completo, e
 * `gerente` nunca entra (D4): o backend grava o default dele.
 */
export function pedidoDeCadastro(formulario: Formulario): Record<string, unknown> {
  return {
    nome: formulario.nome.trim(),
    email: formulario.email.trim(),
    telefone: formulario.telefone.trim(),
    creci: formulario.creci.trim() || null,
    especialidades: formulario.especialidades,
    regioesAtuacao: formulario.regioesAtuacao.map((regiao) => regiao.trim()).filter(Boolean),
    horarioInicio: Number(formulario.horarioInicio),
    horarioFim: Number(formulario.horarioFim),
    capacidadeDiaria: Number(formulario.capacidadeDiaria),
    plantao: formulario.plantao,
  }
}

/**
 * O corpo do `PATCH` de edicao (`CorretorEditado`): SO o que mudou, mesma
 * ideia de `pedidoDaEdicao` em `lib/qualificacao.ts` e do `exclude_unset` do
 * backend. `gerente` nunca vai (D4), mesmo quando o corretor ja e gerente:
 * esta tela nao le nem escreve esse campo, entao nao ha "mudanca" a detectar
 * nele.
 */
export function pedidoDeEdicao(inicial: Formulario, atual: Formulario): Record<string, unknown> {
  const corpo: Record<string, unknown> = {}

  if (inicial.nome.trim() !== atual.nome.trim()) {
    corpo.nome = atual.nome.trim()
  }
  if (inicial.email.trim() !== atual.email.trim()) {
    corpo.email = atual.email.trim()
  }
  if (inicial.telefone.trim() !== atual.telefone.trim()) {
    corpo.telefone = atual.telefone.trim()
  }
  if (inicial.creci.trim() !== atual.creci.trim()) {
    corpo.creci = atual.creci.trim() || null
  }
  if (!mesmaLista([...inicial.especialidades].sort(), [...atual.especialidades].sort())) {
    corpo.especialidades = atual.especialidades
  }
  const regioesAtual = atual.regioesAtuacao.map((regiao) => regiao.trim()).filter(Boolean)
  if (!mesmaLista(inicial.regioesAtuacao, regioesAtual)) {
    corpo.regioesAtuacao = regioesAtual
  }
  if (inicial.horarioInicio !== atual.horarioInicio || inicial.horarioFim !== atual.horarioFim) {
    corpo.horarioInicio = Number(atual.horarioInicio)
    corpo.horarioFim = Number(atual.horarioFim)
  }
  if (inicial.capacidadeDiaria !== atual.capacidadeDiaria) {
    corpo.capacidadeDiaria = Number(atual.capacidadeDiaria)
  }
  if (inicial.plantao !== atual.plantao) {
    corpo.plantao = atual.plantao
  }

  return corpo
}

export function estaSujo(inicial: Formulario, atual: Formulario): boolean {
  return Object.keys(pedidoDeEdicao(inicial, atual)).length > 0
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
    default:
      return typeof erro.msg === 'string' ? erro.msg : 'Valor recusado.'
  }
}

const CAMPOS_DO_FORMULARIO = new Set<string>([
  'nome',
  'email',
  'telefone',
  'creci',
  'especialidades',
  'regioesAtuacao',
  'horarioInicio',
  'horarioFim',
  'capacidadeDiaria',
  'plantao',
])

/**
 * O que dizer quando o backend recusa (D9 do desenho).
 *
 * **O 409 de e-mail duplicado vira erro do campo e-mail**, nao aviso geral
 * -- `EmailJaCadastrado`, respondido com `detail: "e-mail ja cadastrado"`
 * (`corretores.py::cadastrar`/`::editar`). O 422 do pydantic vai para o
 * campo do `loc`, que ja e o nome de `Formulario` porque os aliases de
 * `CorretorNovo`/`CorretorEditado` sao os mesmos nomes.
 */
export function recusaDe(status: number, detail: unknown): Recusa {
  if (status === 409 && detail === 'e-mail ja cadastrado') {
    return { porCampo: { email: 'Este e-mail já está cadastrado.' }, geral: null }
  }
  if (status === 422 && Array.isArray(detail)) {
    const porCampo: Partial<Record<keyof Formulario, string>> = {}
    const soltos: string[] = []
    for (const erro of detail as ErroDoPydantic[]) {
      const loc = Array.isArray(erro.loc) ? erro.loc : []
      const campo = typeof loc[1] === 'string' && CAMPOS_DO_FORMULARIO.has(loc[1]) ? loc[1] : undefined
      if (campo) {
        porCampo[campo as keyof Formulario] ??= traducao(erro)
      } else {
        soltos.push(traducao(erro))
      }
    }
    return { porCampo, geral: soltos.length > 0 ? soltos.join(' ') : null }
  }
  if (status === 401) {
    return { porCampo: {}, geral: 'Sua sessão terminou. Recarregue a página para entrar de novo.' }
  }
  if (status === 403) {
    return { porCampo: {}, geral: 'Você não tem permissão para gerir corretores.' }
  }
  if (status === 404) {
    return { porCampo: {}, geral: 'Este corretor não existe mais.' }
  }
  return { porCampo: {}, geral: 'Não foi possível salvar. Tente de novo.' }
}

export { SEM_ERRO as SEM_RECUSA }

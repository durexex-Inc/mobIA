/**
 * Cadastrar, editar e retirar imoveis, sem I/O (TEC-333).
 *
 * O formulario guarda TEXTO -- o que um `<input>` devolve --, e este modulo
 * traduz nos dois sentidos: da ficha do imovel para o formulario, e da
 * diferenca do formulario para o corpo do `POST`/`PATCH`
 * (`api/routes/imoveis.py::CorpoDoImovel`). A leitura da recusa do backend
 * mora aqui pela mesma razao que `recusaDe` mora em `lib/corretores.ts`: e
 * regra, e se testa sem montar componente.
 *
 * D1 do desenho: o formulario tem oito campos a mais do que a card lista --
 * `codigo`, `descricao`, `tipo`, `operacao`, `cidade`, `uf`, `suites`,
 * `banheiros` -- porque `parser._converter` os exige. "Diferencial" da card e
 * o campo `caracteristicas`; nao existe coluna `diferencial`. `zona`,
 * `latitude`, `longitude` e `fotos` ficam fora, por serem opcionais no
 * backend e nao exercitados pelo Gherkin. `iptuMensal` tambem ficava, ate a
 * pagina de edicao da TEC-400 pedir o campo.
 *
 * D2 do desenho: a validacao do lado do cliente e so "campo vazio" -- sem
 * faixa nem plausibilidade, porque o backend ja valida isso com mensagem
 * legivel e a resposta e uma STRING unica, nao uma lista por campo.
 */

/** O vocabulario de `domain/catalogo/enums.py::TipoImovel`. */
export type TipoImovel = 'APARTAMENTO' | 'CASA' | 'COBERTURA' | 'TERRENO' | 'COMERCIAL' | 'RURAL'

export const TIPOS_DE_IMOVEL: Record<TipoImovel, string> = {
  APARTAMENTO: 'Apartamento',
  CASA: 'Casa',
  COBERTURA: 'Cobertura',
  TERRENO: 'Terreno',
  COMERCIAL: 'Comercial',
  RURAL: 'Rural',
}

/** `domain/catalogo/enums.py::Operacao`. */
export type Operacao = 'VENDA' | 'ALUGUEL' | 'AMBOS'

export const OPERACOES: Record<Operacao, string> = {
  VENDA: 'Venda',
  ALUGUEL: 'Aluguel',
  AMBOS: 'Ambos',
}

/** `domain/catalogo/enums.py::StatusImovel`. */
export type StatusImovel = 'DISPONIVEL' | 'RESERVADO' | 'VENDIDO' | 'ALUGADO' | 'INATIVO'

export const STATUS_DO_IMOVEL: Record<StatusImovel, string> = {
  DISPONIVEL: 'Disponível',
  RESERVADO: 'Reservado',
  VENDIDO: 'Vendido',
  ALUGADO: 'Alugado',
  INATIVO: 'Inativo',
}

/**
 * O imovel como a API devolve (`cadastro.como_api`): camelCase, precos e
 * condominio e IPTU em CENTAVOS. `zona`/`latitude`/`longitude`/`fotos`
 * existem no tipo porque a resposta os traz, mesmo que o formulario nao os
 * edite (D1). `iptuMensal` entrou no formulario na TEC-400.
 */
export type Imovel = {
  id: string
  codigo: string
  titulo: string
  descricao: string
  tipo: TipoImovel
  operacao: Operacao
  status: StatusImovel
  precoVenda: number | null
  precoAluguel: number | null
  condominio: number | null
  iptuMensal: number | null
  bairro: string
  cidade: string
  uf: string
  zona: string | null
  latitude: number | null
  longitude: number | null
  areaUtilM2: number
  quartos: number
  suites: number
  banheiros: number
  vagas: number
  caracteristicas: string[]
  fotos: string[]
  atualizadoEm: string
}

/**
 * Os campos do formulario. So os que a tela edita (D1) -- os demais campos de
 * `Imovel` (`zona`, `latitude`, `longitude`, `fotos`) nao tem lugar aqui;
 * `iptuMensal` ganhou lugar na TEC-400. Precos, condominio e IPTU ficam como
 * texto em REAIS: e o que um
 * `<input>` devolve, e a conversao para centavos so acontece na hora do
 * pedido.
 */
export type Formulario = {
  codigo: string
  titulo: string
  descricao: string
  tipo: TipoImovel | ''
  operacao: Operacao | ''
  status: StatusImovel | ''
  precoVenda: string
  precoAluguel: string
  condominio: string
  iptuMensal: string
  bairro: string
  cidade: string
  uf: string
  areaUtilM2: string
  quartos: string
  suites: string
  banheiros: string
  vagas: string
  /** "Diferencial" da card (D1) -- uma por linha/chip, no molde de `regioesAtuacao`. */
  caracteristicas: string[]
}

/** Os campos de texto/numero -- os que os campos de formulario editam por string. */
export type CampoDeTexto =
  | 'codigo'
  | 'titulo'
  | 'descricao'
  | 'precoVenda'
  | 'precoAluguel'
  | 'condominio'
  | 'iptuMensal'
  | 'bairro'
  | 'cidade'
  | 'uf'
  | 'areaUtilM2'
  | 'quartos'
  | 'suites'
  | 'banheiros'
  | 'vagas'

const VAZIO: Formulario = {
  codigo: '',
  titulo: '',
  descricao: '',
  tipo: '',
  operacao: '',
  status: '',
  precoVenda: '',
  precoAluguel: '',
  condominio: '',
  iptuMensal: '',
  bairro: '',
  cidade: '',
  uf: '',
  areaUtilM2: '',
  quartos: '',
  suites: '',
  banheiros: '',
  vagas: '',
  caracteristicas: [],
}

/** Centavos (como a API traz) para uma string em reais (como o `<input>` mostra). */
function centavosParaReais(centavos: number | null): string {
  return centavos == null ? '' : String(centavos / 100)
}

/**
 * Reais digitados de volta para centavos, ou `null` quando o campo esta
 * vazio. Exportada para `PreviewDoCard.tsx` (TEC-336) reusar a mesma
 * conversao numerica em vez de duplica-la -- nao ha validacao aqui para
 * divergir, so aritmetica.
 */
export function reaisParaCentavos(reais: string): number | null {
  const valor = reais.trim()
  if (!valor) {
    return null
  }
  return Math.round(Number(valor) * 100)
}

/**
 * O formulario a partir do imovel -- ou vazio, para o cadastro
 * (`imovel === null`).
 */
export function formularioDe(imovel: Imovel | null): Formulario {
  if (!imovel) {
    return { ...VAZIO, caracteristicas: [] }
  }
  return {
    codigo: imovel.codigo,
    titulo: imovel.titulo,
    descricao: imovel.descricao,
    tipo: imovel.tipo,
    operacao: imovel.operacao,
    status: imovel.status,
    precoVenda: centavosParaReais(imovel.precoVenda),
    precoAluguel: centavosParaReais(imovel.precoAluguel),
    condominio: centavosParaReais(imovel.condominio),
    iptuMensal: centavosParaReais(imovel.iptuMensal),
    bairro: imovel.bairro,
    cidade: imovel.cidade,
    uf: imovel.uf,
    areaUtilM2: String(imovel.areaUtilM2),
    quartos: String(imovel.quartos),
    suites: String(imovel.suites),
    banheiros: String(imovel.banheiros),
    vagas: String(imovel.vagas),
    caracteristicas: [...imovel.caracteristicas],
  }
}

function mesmaLista(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((item, i) => item === b[i])
}

export type Recusa = {
  /** Mensagem ao lado de cada campo -- so a validacao "campo vazio" do cliente (D2) preenche isto. */
  porCampo: Partial<Record<keyof Formulario, string>>
  /** Mensagem do topo do formulario: a `string` do backend, mostrada inteira (D2). */
  geral: string | null
}

const SEM_ERRO: Recusa = { porCampo: {}, geral: null }

const OBRIGATORIOS: ReadonlyArray<[keyof Formulario, string]> = [
  ['codigo', 'Informe o código.'],
  ['titulo', 'Informe o título.'],
  ['descricao', 'Informe a descrição.'],
  ['bairro', 'Informe o bairro.'],
  ['cidade', 'Informe a cidade.'],
  ['uf', 'Informe a UF.'],
  ['areaUtilM2', 'Informe a área útil.'],
  ['quartos', 'Informe o número de quartos.'],
  ['suites', 'Informe o número de suítes.'],
  ['banheiros', 'Informe o número de banheiros.'],
  ['vagas', 'Informe o número de vagas.'],
]

/**
 * A validacao do lado do cliente (D2 do desenho): so "campo vazio", para os
 * obrigatorios de `parser._converter`. Nao ha faixa nem plausibilidade aqui
 * -- essas regras so existem no backend, e a mensagem dele e mostrada como
 * veio (`recusaDe`).
 *
 * O preco segue a operacao: Venda exige `precoVenda`, Aluguel exige
 * `precoAluguel`, Ambos exige ao menos um dos dois -- o mesmo "ao menos um
 * preco" de `parser._converter`.
 */
export function validarFormulario(formulario: Formulario): Recusa {
  const porCampo: Partial<Record<keyof Formulario, string>> = {}

  for (const [campo, mensagem] of OBRIGATORIOS) {
    const valor = formulario[campo]
    if (typeof valor === 'string' && !valor.trim()) {
      porCampo[campo] = mensagem
    }
  }

  if (!formulario.tipo) {
    porCampo.tipo = 'Escolha o tipo.'
  }
  if (!formulario.operacao) {
    porCampo.operacao = 'Escolha a operação.'
  }
  if (!formulario.status) {
    porCampo.status = 'Escolha o status.'
  }

  if (formulario.operacao === 'VENDA' && !formulario.precoVenda.trim()) {
    porCampo.precoVenda = 'Informe o preço de venda.'
  }
  if (formulario.operacao === 'ALUGUEL' && !formulario.precoAluguel.trim()) {
    porCampo.precoAluguel = 'Informe o preço de aluguel.'
  }
  if (
    formulario.operacao === 'AMBOS' &&
    !formulario.precoVenda.trim() &&
    !formulario.precoAluguel.trim()
  ) {
    porCampo.precoVenda = 'Informe ao menos um dos preços.'
  }

  return { porCampo, geral: null }
}

export function formularioValido(formulario: Formulario): boolean {
  return Object.keys(validarFormulario(formulario).porCampo).length === 0
}

/**
 * O corpo do `POST` de cadastro (`CorpoDoImovel`). Sempre completo -- os
 * campos fora do escopo desta tela (`zona`, `latitude`, `longitude`, `fotos`)
 * nunca entram, e o backend os trata como ausentes. `iptuMensal` entra
 * (TEC-400), `null` quando vazio, como o condominio.
 */
export function pedidoDeCadastro(formulario: Formulario): Record<string, unknown> {
  return {
    codigo: formulario.codigo.trim(),
    titulo: formulario.titulo.trim(),
    descricao: formulario.descricao.trim(),
    tipo: formulario.tipo,
    operacao: formulario.operacao,
    status: formulario.status,
    precoVenda: reaisParaCentavos(formulario.precoVenda),
    precoAluguel: reaisParaCentavos(formulario.precoAluguel),
    condominio: reaisParaCentavos(formulario.condominio),
    iptuMensal: reaisParaCentavos(formulario.iptuMensal),
    bairro: formulario.bairro.trim(),
    cidade: formulario.cidade.trim(),
    uf: formulario.uf.trim(),
    areaUtilM2: Number(formulario.areaUtilM2),
    quartos: Number(formulario.quartos),
    suites: Number(formulario.suites),
    banheiros: Number(formulario.banheiros),
    vagas: Number(formulario.vagas),
    caracteristicas: formulario.caracteristicas.map((item) => item.trim()).filter(Boolean),
  }
}

/**
 * O corpo do `PATCH` de edicao: SO o que mudou, mesmo `exclude_unset` do
 * backend que `lib/corretores.ts::pedidoDeEdicao` segue.
 *
 * **`codigo` nunca entra** (D5 do desenho): o campo e desabilitado na edicao
 * pelo componente, entao `inicial.codigo` e `atual.codigo` sao sempre iguais
 * -- mas a funcao nem olha para `codigo`, para que trocar isso no componente
 * amanha nao reabra a porta que o `422 codigo_imutavel` do backend fecha.
 */
export function pedidoDeEdicao(inicial: Formulario, atual: Formulario): Record<string, unknown> {
  const corpo: Record<string, unknown> = {}

  if (inicial.titulo.trim() !== atual.titulo.trim()) {
    corpo.titulo = atual.titulo.trim()
  }
  if (inicial.descricao.trim() !== atual.descricao.trim()) {
    corpo.descricao = atual.descricao.trim()
  }
  if (inicial.tipo !== atual.tipo) {
    corpo.tipo = atual.tipo
  }
  if (inicial.operacao !== atual.operacao) {
    corpo.operacao = atual.operacao
  }
  if (inicial.status !== atual.status) {
    corpo.status = atual.status
  }
  if (inicial.precoVenda.trim() !== atual.precoVenda.trim()) {
    corpo.precoVenda = reaisParaCentavos(atual.precoVenda)
  }
  if (inicial.precoAluguel.trim() !== atual.precoAluguel.trim()) {
    corpo.precoAluguel = reaisParaCentavos(atual.precoAluguel)
  }
  if (inicial.condominio.trim() !== atual.condominio.trim()) {
    corpo.condominio = reaisParaCentavos(atual.condominio)
  }
  if (inicial.iptuMensal.trim() !== atual.iptuMensal.trim()) {
    corpo.iptuMensal = reaisParaCentavos(atual.iptuMensal)
  }
  if (inicial.bairro.trim() !== atual.bairro.trim()) {
    corpo.bairro = atual.bairro.trim()
  }
  if (inicial.cidade.trim() !== atual.cidade.trim()) {
    corpo.cidade = atual.cidade.trim()
  }
  if (inicial.uf.trim() !== atual.uf.trim()) {
    corpo.uf = atual.uf.trim()
  }
  if (inicial.areaUtilM2 !== atual.areaUtilM2) {
    corpo.areaUtilM2 = Number(atual.areaUtilM2)
  }
  if (inicial.quartos !== atual.quartos) {
    corpo.quartos = Number(atual.quartos)
  }
  if (inicial.suites !== atual.suites) {
    corpo.suites = Number(atual.suites)
  }
  if (inicial.banheiros !== atual.banheiros) {
    corpo.banheiros = Number(atual.banheiros)
  }
  if (inicial.vagas !== atual.vagas) {
    corpo.vagas = Number(atual.vagas)
  }
  const caracteristicasAtual = atual.caracteristicas.map((item) => item.trim()).filter(Boolean)
  if (!mesmaLista(inicial.caracteristicas, caracteristicasAtual)) {
    corpo.caracteristicas = caracteristicasAtual
  }

  return corpo
}

/**
 * O custo mensal de quem aluga, em reais: aluguel + condominio + IPTU (TEC-400).
 * So existe com preco de aluguel -- para venda o total nao significa nada --,
 * e campo vazio ou nao numerico conta zero, para o valor acompanhar a
 * digitacao. E so um indicador da tela: nao vai no `PATCH`.
 */
export function totalMensalEstimado(formulario: Formulario): number | null {
  const parcela = (valor: string) => {
    const numero = Number(valor.trim())
    return valor.trim() && Number.isFinite(numero) ? numero : 0
  }
  if (!formulario.precoAluguel.trim()) {
    return null
  }
  return parcela(formulario.precoAluguel) + parcela(formulario.condominio) + parcela(formulario.iptuMensal)
}

export function estaSujo(inicial: Formulario, atual: Formulario): boolean {
  return Object.keys(pedidoDeEdicao(inicial, atual)).length > 0
}

/**
 * O que dizer quando o backend recusa (D2 do desenho).
 *
 * **Nunca por campo.** `CadastroRecusado.detalhe` e uma `string` unica com os
 * motivos concatenados por `; ` (`cadastro.py`), e separa-la por campo aqui
 * seria reimplementar `parser._converter` do lado do cliente -- exatamente o
 * "segundo validador" que a D2 do desenho da TEC-197 recusou para o proprio
 * backend. 409 (`codigo` duplicado) e 422 (invalido ou `codigo_imutavel`) sao
 * ambos texto e vao para o mesmo aviso geral.
 */
export function recusaDe(status: number, detail: unknown): Recusa {
  if (status === 401) {
    return { porCampo: {}, geral: 'Sua sessão terminou. Recarregue a página para entrar de novo.' }
  }
  if (status === 403) {
    return { porCampo: {}, geral: 'Você não tem permissão para gerir o catálogo.' }
  }
  if (status === 404) {
    return { porCampo: {}, geral: 'Este imóvel não existe mais.' }
  }
  if ((status === 409 || status === 422) && typeof detail === 'string') {
    return { porCampo: {}, geral: detail }
  }
  return { porCampo: {}, geral: 'Não foi possível salvar. Tente de novo.' }
}

export { SEM_ERRO as SEM_RECUSA }

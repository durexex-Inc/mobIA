/**
 * A vitrine paginada do portal (visual do portal, D7), do corpo de
 * `GET /portal/vitrine` (`api/routes/portal.py::_card_da_vitrine`). Modulo
 * puro: o mapa e a ordenacao sao Client Components e importam daqui.
 *
 * Tipo proprio, e nao `ImovelCard` (`lib/imovel.ts`): aquele e o card do
 * chat, com foto absoluta `http(s)` e sem suites, banheiros, IPTU nem
 * coordenada. Aqui a foto e caminho relativo deste backend, como no detalhe
 * (`lib/imovelDetalhe.ts`).
 */

export type ImovelDaVitrine = {
  id: string
  codigo: string
  titulo: string
  tipo: string
  operacao: string
  bairro: string
  cidade: string
  uf: string
  areaUtilM2: number
  quartos: number
  suites: number
  banheiros: number
  vagas: number
  /** Em centavos, da operacao buscada (venda ou aluguel). */
  preco: number
  condominio: number | null
  iptuMensal: number | null
  caracteristicas: string[]
  foto: string | null
  latitude: number | null
  longitude: number | null
}

export type PaginaDaVitrine = {
  itens: ImovelDaVitrine[]
  total: number
  pagina: number
  porPagina: number
}

/** `domain/catalogo/vitrine.py::OrdemDaVitrine`, com o rotulo que o visitante le. */
export const ORDENS_DA_VITRINE = {
  recentes: 'Mais recentes',
  menor_preco: 'Menor preço',
  maior_preco: 'Maior preço',
  maior_area: 'Maior área',
} as const

export type OrdemDaVitrine = keyof typeof ORDENS_DA_VITRINE

export const ORDEM_PADRAO: OrdemDaVitrine = 'recentes'

type Bruto = Record<string, unknown>

function inteiro(valor: unknown): valor is number {
  return typeof valor === 'number' && Number.isInteger(valor) && valor >= 0
}

function texto(valor: unknown): valor is string {
  return typeof valor === 'string' && valor.trim() !== ''
}

function coordenada(valor: unknown, limite: number): number | null {
  return typeof valor === 'number' && Number.isFinite(valor) && Math.abs(valor) <= limite ? valor : null
}

/** Um item da vitrine, ou `null` -- item invalido sai da lista, nunca derruba a pagina. */
export function itemDaVitrineDe(valor: unknown): ImovelDaVitrine | null {
  if (typeof valor !== 'object' || valor === null || Array.isArray(valor)) {
    return null
  }
  const dado = valor as Bruto
  const obrigatorios = [dado.id, dado.codigo, dado.titulo, dado.tipo, dado.operacao, dado.bairro, dado.cidade, dado.uf]
  const numeros = [dado.areaUtilM2, dado.quartos, dado.suites, dado.banheiros, dado.vagas, dado.preco]
  if (!obrigatorios.every(texto) || !numeros.every(inteiro)) {
    return null
  }
  const latitude = coordenada(dado.latitude, 90)
  const longitude = coordenada(dado.longitude, 180)
  // So o par inteiro vale: meia coordenada nao poe pino nenhum no mapa.
  const temPar = latitude !== null && longitude !== null
  return {
    id: dado.id as string,
    codigo: dado.codigo as string,
    titulo: dado.titulo as string,
    tipo: dado.tipo as string,
    operacao: dado.operacao as string,
    bairro: dado.bairro as string,
    cidade: dado.cidade as string,
    uf: dado.uf as string,
    areaUtilM2: dado.areaUtilM2 as number,
    quartos: dado.quartos as number,
    suites: dado.suites as number,
    banheiros: dado.banheiros as number,
    vagas: dado.vagas as number,
    preco: dado.preco as number,
    condominio: inteiro(dado.condominio) ? dado.condominio : null,
    iptuMensal: inteiro(dado.iptuMensal) ? dado.iptuMensal : null,
    caracteristicas: Array.isArray(dado.caracteristicas)
      ? dado.caracteristicas.filter((item): item is string => typeof item === 'string')
      : [],
    foto: texto(dado.foto) ? dado.foto : null,
    latitude: temPar ? latitude : null,
    longitude: temPar ? longitude : null,
  }
}

/**
 * O preco do pino do mapa, curto: "R$ 1,78 mi", "R$ 650 mil", "R$ 6,5 mil".
 * Centavos de entrada, como todo preco da API. O card ao lado mostra o valor
 * cheio; aqui so cabe o que se le de relance.
 */
export function precoCurto(centavos: number): string {
  const reais = Math.floor(centavos / 100)
  const numero = (valor: number, casas: number) =>
    valor.toLocaleString('pt-BR', { maximumFractionDigits: casas, minimumFractionDigits: 0 })
  if (reais >= 1_000_000) {
    return `R$ ${numero(Math.floor(reais / 10_000) / 100, 2)} mi`
  }
  if (reais >= 10_000) {
    return `R$ ${numero(Math.floor(reais / 1000), 0)} mil`
  }
  if (reais >= 1000) {
    return `R$ ${numero(Math.floor(reais / 100) / 10, 1)} mil`
  }
  return `R$ ${numero(reais, 0)}`
}

export function totalDePaginas(total: number, porPagina: number): number {
  return Math.max(1, Math.ceil(total / porPagina))
}

/**
 * As paginas que a paginacao mostra: a primeira, a ultima e duas vizinhas da
 * atual, com `null` onde ha salto ("1 … 4 5 6 … 30"). Lista curta sempre --
 * trinta botoes de pagina nao ajudam ninguem.
 */
export function paginasVisiveis(atual: number, ultima: number): (number | null)[] {
  const escolhidas = new Set([1, ultima, atual - 1, atual, atual + 1].filter((p) => p >= 1 && p <= ultima))
  const ordenadas = [...escolhidas].sort((a, b) => a - b)
  const resultado: (number | null)[] = []
  ordenadas.forEach((pagina, indice) => {
    if (indice > 0 && pagina - ordenadas[indice - 1] > 1) {
      resultado.push(null)
    }
    resultado.push(pagina)
  })
  return resultado
}

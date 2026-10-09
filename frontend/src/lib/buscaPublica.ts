/**
 * Os filtros da vitrine publica, sem I/O (TEC-387, D1 e D5 do desenho).
 *
 * Modulo puro, no molde de `lib/auditoria.ts`: o formulario e componente de
 * cliente, e nada que ele importe pode arrastar `server-only`. A chamada ao
 * FastAPI mora em `lib/servidor/vitrinePublica.ts`.
 */

import { reaisParaCentavos, type Operacao, type TipoImovel, TIPOS_DE_IMOVEL } from '@/lib/imoveis'
import { ORDEM_PADRAO, ORDENS_DA_VITRINE, type OrdemDaVitrine } from '@/lib/vitrine'

/**
 * `operacao` continua obrigatoria, igual ao endpoint interno: e ela que
 * escolhe a coluna de preco que o FastAPI compara, e `AMBOS` nao e busca
 * valida. "Sem filtro nenhum" (CA-01) e o estado inicial da TELA, nao da
 * requisicao -- a pagina sempre manda uma operacao.
 */
export type FiltrosDoPortal = {
  operacao: Exclude<Operacao, 'AMBOS'>
  precoMinCentavos?: number
  precoMaxCentavos?: number
  tipo?: TipoImovel
  quartosMin?: number
  vagasMin?: number
  regioes?: string[]
  /** Ausente e `ORDEM_PADRAO`; a URL so a carrega quando e outra. */
  ordem?: OrdemDaVitrine
  /** Comeca em 1; ausente e a primeira. Mudar qualquer filtro volta para ela. */
  pagina?: number
}

/** A operacao padrao quando a URL nao pede nenhuma -- o estado inicial do CA-01. */
export const OPERACAO_PADRAO: Exclude<Operacao, 'AMBOS'> = 'VENDA'

type ParametrosDaUrl = Record<string, string | string[] | undefined>

function um(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor
}

function inteiroOuUndefined(valor: string | undefined): number | undefined {
  if (!valor || !valor.trim()) {
    return undefined
  }
  const numero = Number(valor)
  return Number.isFinite(numero) && numero >= 0 ? Math.trunc(numero) : undefined
}

/**
 * Os filtros que a URL (ou o `FormData` do formulario) pede. `precoMin`/
 * `precoMax` chegam em REAIS do `<input>` -- o mesmo texto que um usuario
 * digita -- e viram centavos aqui, no limite entre o formulario e a API,
 * igual a `pedidoDeCadastro` em `lib/imoveis.ts`.
 *
 * Tipo desconhecido cai em "sem filtro": o backend recusaria com 422, e a
 * tela nao repassa o que nao sabe mostrar.
 */
export function filtrosDaUrl(parametros: ParametrosDaUrl): FiltrosDoPortal {
  const operacaoPedida = um(parametros.operacao)
  const operacao: Exclude<Operacao, 'AMBOS'> =
    operacaoPedida === 'ALUGUEL' ? 'ALUGUEL' : OPERACAO_PADRAO

  const tipoPedido = um(parametros.tipo)
  const tipo = tipoPedido !== undefined && tipoPedido in TIPOS_DE_IMOVEL ? (tipoPedido as TipoImovel) : undefined

  const ordemPedida = um(parametros.ordem)
  const ordem =
    ordemPedida !== undefined && ordemPedida in ORDENS_DA_VITRINE && ordemPedida !== ORDEM_PADRAO
      ? (ordemPedida as OrdemDaVitrine)
      : undefined
  const pagina = inteiroOuUndefined(um(parametros.pagina))

  return {
    operacao,
    precoMinCentavos: reaisParaCentavos(um(parametros.precoMin) ?? '') ?? undefined,
    precoMaxCentavos: reaisParaCentavos(um(parametros.precoMax) ?? '') ?? undefined,
    tipo,
    quartosMin: inteiroOuUndefined(um(parametros.quartosMin)),
    vagasMin: inteiroOuUndefined(um(parametros.vagasMin)),
    regioes: (um(parametros.regioes) ?? '')
      .split(',')
      .map((regiao) => regiao.trim())
      .filter(Boolean),
    ordem,
    pagina: pagina !== undefined && pagina > 1 ? pagina : undefined,
  }
}

/** O endereco da pagina com estes filtros, no molde de `urlDaLista` de `lib/auditoria.ts`. */
export function urlDaBusca(filtros: FiltrosDoPortal): string {
  const parametros = new URLSearchParams()
  parametros.set('operacao', filtros.operacao)
  // Em REAIS na URL, nao centavos: `filtrosDaUrl` le `precoMin`/`precoMax`
  // como o texto que o `<input>` manda (`reaisParaCentavos`), e esta funcao
  // e a inversa dela -- as duas tem de falar a mesma unidade, ou o
  // "ida e volta pela URL" perde precisao (dividido por 100 na volta).
  if (filtros.precoMinCentavos !== undefined) {
    parametros.set('precoMin', String(filtros.precoMinCentavos / 100))
  }
  if (filtros.precoMaxCentavos !== undefined) {
    parametros.set('precoMax', String(filtros.precoMaxCentavos / 100))
  }
  if (filtros.tipo) {
    parametros.set('tipo', filtros.tipo)
  }
  if (filtros.quartosMin !== undefined) {
    parametros.set('quartosMin', String(filtros.quartosMin))
  }
  if (filtros.vagasMin !== undefined) {
    parametros.set('vagasMin', String(filtros.vagasMin))
  }
  // Um parametro so, separado por virgula -- e o que um `<input>` de texto
  // livre produz, e e o que `filtrosDaUrl` espera de volta. A API do FastAPI
  // (`vitrinePublica.ts::buscaDe`) e que fala `regioes=` repetido; sao duas
  // URLs diferentes, com formatos proprios.
  if (filtros.regioes && filtros.regioes.length > 0) {
    parametros.set('regioes', filtros.regioes.join(','))
  }
  if (filtros.ordem && filtros.ordem !== ORDEM_PADRAO) {
    parametros.set('ordem', filtros.ordem)
  }
  if (filtros.pagina !== undefined && filtros.pagina > 1) {
    parametros.set('pagina', String(filtros.pagina))
  }
  return `/busca?${parametros.toString()}`
}

/**
 * A sessao do chat web guardada no navegador, com validade de 30 dias
 * contados DESDE A CRIACAO -- nunca renovados pelo uso (D1, TEC-347).
 *
 * Modulo puro: recebe o storage e o instante como parametros, entao e
 * testavel sem localStorage real e sem relogio real. `Armazem` e o
 * subconjunto de `Storage` que o modulo usa -- basta para aceitar tanto
 * `window.localStorage` quanto um dublê de teste.
 *
 * Nenhuma funcao daqui lanca. Storage bloqueado (Safari ITP, modo privado)
 * e o formato de fato usado em producao: o chat tem de abrir sessao
 * anonima, nao quebrar.
 */

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export const CHAVE_DA_SESSAO = 'mobia:sessao'
export const VALIDADE_DA_SESSAO_MS = 30 * 24 * 60 * 60 * 1000

export type Armazem = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

type SessaoGuardada = {
  sessao: string
  criadaEm: number
}

// Aceita so o formato exato {sessao, criadaEm} com sessao em UUID e
// criadaEm numerico. Qualquer outra coisa -- inclusive o texto puro que a
// TEC-346 gravava antes deste modulo existir -- e tratada como ausencia.
function comoSessaoValida(bruto: string): SessaoGuardada | null {
  let dado: unknown
  try {
    dado = JSON.parse(bruto)
  } catch {
    return null
  }
  if (typeof dado !== 'object' || dado === null || Array.isArray(dado)) {
    return null
  }
  const { sessao, criadaEm } = dado as Record<string, unknown>
  if (typeof sessao !== 'string' || !UUID_RE.test(sessao)) {
    return null
  }
  if (typeof criadaEm !== 'number' || !Number.isFinite(criadaEm)) {
    return null
  }
  return { sessao, criadaEm }
}

/**
 * A sessao valida guardada, ou null. Apaga o que estiver invalido ou
 * vencido. Nunca lanca.
 *
 * Valida (D1): o JSON e um objeto, `sessao` e UUID, `criadaEm` nao esta no
 * futuro e `agora - criadaEm < VALIDADE_DA_SESSAO_MS` -- o prazo e contado
 * desde a criacao, entao uma sessao usada todo dia por 30 dias ainda vence,
 * de proposito (D1: "retomar nao regrava, entao o prazo nao anda").
 */
export function lerSessao(armazem: Armazem | null, agora: number): string | null {
  if (!armazem) {
    return null
  }

  let bruto: string | null
  try {
    bruto = armazem.getItem(CHAVE_DA_SESSAO)
  } catch {
    return null
  }
  if (bruto === null) {
    return null
  }

  const valida = comoSessaoValida(bruto)
  const vencida =
    valida === null || valida.criadaEm > agora || agora - valida.criadaEm >= VALIDADE_DA_SESSAO_MS

  if (vencida) {
    apagarSessao(armazem)
    return null
  }

  return valida.sessao
}

/**
 * Grava `sessao` com `criadaEm = agora`, a menos que ja seja a guardada.
 * Nunca lanca.
 *
 * Por que nao renova (D1): o prazo de retencao no aparelho e um teto desde
 * a criacao, nao uma janela de inatividade. Se toda leitura regravasse
 * `criadaEm`, uma conversa reaberta todo dia nunca venceria -- o que
 * contradiz "no maximo 30 dias". Por isso `gravarSessao` so e chamada
 * quando o servidor emite uma sessao nova (o `sessao` do frame difere do
 * guardado); retomar a mesma sessao nao regrava.
 */
export function gravarSessao(armazem: Armazem | null, sessao: string, agora: number): void {
  if (!armazem) {
    return
  }
  try {
    const bruto = armazem.getItem(CHAVE_DA_SESSAO)
    if (bruto !== null) {
      const valida = comoSessaoValida(bruto)
      if (valida !== null && valida.sessao === sessao) {
        return
      }
    }
    armazem.setItem(CHAVE_DA_SESSAO, JSON.stringify({ sessao, criadaEm: agora }))
  } catch {
    // storage bloqueado ou cheio -- nunca lanca
  }
}

/** Apaga a sessao guardada. Nunca lanca. */
export function apagarSessao(armazem: Armazem | null): void {
  if (!armazem) {
    return
  }
  try {
    armazem.removeItem(CHAVE_DA_SESSAO)
  } catch {
    // storage bloqueado -- nunca lanca
  }
}

/** `window.localStorage`, ou null se acessar lancar. */
export function armazemDoNavegador(): Armazem | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

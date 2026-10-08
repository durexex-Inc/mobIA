/**
 * O tema do painel (TEC-393, D2): o do sistema, a menos que a pessoa tenha
 * escolhido outro no botao do menu.
 *
 * A escolha vive num cookie, e nao no `localStorage`, para o servidor ja
 * mandar a pagina no tema certo -- sem piscar e sem script inline, que a CSP
 * recusaria.
 */
export type Tema = 'claro' | 'escuro'

export const COOKIE_DO_TEMA = 'mobia_tema'

export const SEGUNDOS_DO_TEMA = 365 * 24 * 60 * 60

/** `undefined` e "siga o sistema". */
export function temaDoCookie(valor: string | undefined): Tema | undefined {
  return valor === 'claro' || valor === 'escuro' ? valor : undefined
}

/** O oposto do tema que esta na tela, escolhido ou herdado do sistema. */
export function proximoTema(escolhido: Tema | undefined, sistemaEscuro: boolean): Tema {
  const atual = escolhido ?? (sistemaEscuro ? 'escuro' : 'claro')
  return atual === 'escuro' ? 'claro' : 'escuro'
}

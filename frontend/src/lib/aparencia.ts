/**
 * A aparencia do chat web (TEC-344, D1 e D3): o que o botao e o cabecalho do
 * chat precisam, no formato que `GET /widget/aparencia` devolve (menos o
 * `tenant`, que so serve para `buscarAparencia` comparar o slug, e os
 * `dominios` da TEC-345, que `lerDominios` le a parte).
 *
 * Sem `server-only`: a pagina do chat e o teste leem isto, e nao ha segredo
 * aqui. O loader (`public/widget.js`) repete a mesma conferencia porque nao
 * importa nada -- e JavaScript puro, sem build (D5).
 */

export type PosicaoDoBotao = 'DIREITA' | 'ESQUERDA'

export type Aparencia = {
  nomeDoAssistente: string | null
  corPrimaria: string
  posicaoDoBotao: PosicaoDoBotao
}

const COR = /^#[0-9A-Fa-f]{6}$/
// Lista, e nao objeto: `'constructor' in {}` e verdadeiro, e uma posicao com
// nome de propriedade herdada passaria.
const POSICOES: readonly string[] = ['DIREITA', 'ESQUERDA']

export function lerAparencia(corpo: unknown): Aparencia | null {
  if (typeof corpo !== 'object' || corpo === null) {
    return null
  }
  const { nomeDoAssistente, corPrimaria, posicaoDoBotao } = corpo as Record<string, unknown>
  if (typeof corPrimaria !== 'string' || !COR.test(corPrimaria)) {
    return null
  }
  if (typeof posicaoDoBotao !== 'string' || !POSICOES.includes(posicaoDoBotao)) {
    return null
  }
  if (nomeDoAssistente !== null && typeof nomeDoAssistente !== 'string') {
    return null
  }
  return { nomeDoAssistente, corPrimaria, posicaoDoBotao: posicaoDoBotao as PosicaoDoBotao }
}

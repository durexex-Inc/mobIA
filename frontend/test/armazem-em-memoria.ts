import type { Armazem } from '@/lib/servidor/armazem'

/**
 * O Redis dos testes: um mapa, com a validade guardada ao lado do valor.
 *
 * Uso, no topo do arquivo de teste:
 *
 *     vi.mock('@/lib/servidor/armazem', async () =>
 *       (await import('../test/armazem-em-memoria')).moduloDeArmazem,
 *     )
 *
 * e `limparArmazem()` num `beforeEach`. A validade e guardada e NAO e
 * aplicada: nenhum teste espera o relogio andar, e o que se afirma sobre ela
 * e o numero que foi pedido ao Redis (`validadeDe`).
 */
const valores = new Map<string, { valor: string; segundos: number }>()

export const armazemEmMemoria: Armazem = {
  obter: async (chave) => valores.get(chave)?.valor ?? null,
  gravar: async (chave, valor, segundos) => {
    valores.set(chave, { valor, segundos })
  },
  gravarSeAusente: async (chave, valor, segundos) => {
    if (valores.has(chave)) {
      return false
    }
    valores.set(chave, { valor, segundos })
    return true
  },
  apagar: async (chave) => {
    valores.delete(chave)
  },
}

export const moduloDeArmazem = { armazem: async () => armazemEmMemoria }

export function limparArmazem(): void {
  valores.clear()
}

/** Tudo o que esta gravado, para o teste olhar sem conhecer o formato da chave. */
export function conteudoDoArmazem(): Array<{ chave: string; valor: string; segundos: number }> {
  return [...valores].map(([chave, { valor, segundos }]) => ({ chave, valor, segundos }))
}

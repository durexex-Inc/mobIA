import { lerDominios } from '@/lib/dominios'

/**
 * Os dominios que podem embutir o chat, para o `frame-ancestors` do proxy
 * (TEC-345, D4).
 *
 * **Sem `server-only` e sem `chamarApi`, de proposito.** Quem importa isto e
 * o proxy, e `api.ts` arrasta `server-only`, que e gate do bundle de
 * componentes e nao do proxy. Nao ha credencial aqui: `GET /widget/aparencia`
 * e publica. A base da API e a mesma variavel que `api.ts` le.
 *
 * **Memoria de modulo, e nao o Data Cache.** A referencia de `proxy` do Next
 * 16 nao documenta `fetch` com `next.revalidate` dentro do proxy, e contar com
 * isso seria descobrir o comportamento do cache em producao. Um prazo no
 * proprio processo resolve, e se testa com relogio falso:
 *
 * - a promessa em voo e compartilhada, entao cem requisicoes no vencimento
 *   fazem uma chamada so;
 * - a falha tambem e memorizada, por menos tempo: a API caida nao e martelada
 *   a cada visita, e o embed volta sozinho quando ela volta.
 *
 * **Falha vira lista vazia**, e lista vazia e `frame-ancestors 'none'`: sem
 * resposta da API, nenhum site embute. E o lado seguro.
 */

const PRAZO_DO_SUCESSO_MS = 60_000
const PRAZO_DA_FALHA_MS = 5_000
// O proxy segura a pagina enquanto espera; a API lenta nao pode segurar o
// embed inteiro.
const TEMPO_MAXIMO_MS = 2_000

type Memoria = { vence: number; dominios: Promise<readonly string[]> }

let memoria: Memoria | null = null

function baseDaApi(): string {
  return process.env.MOBIA_API_BASE ?? 'http://localhost:8000'
}

async function buscar(): Promise<readonly string[]> {
  const resposta = await fetch(new URL('/widget/aparencia', baseDaApi()), {
    cache: 'no-store',
    signal: AbortSignal.timeout(TEMPO_MAXIMO_MS),
  })
  if (!resposta.ok) {
    throw new Error(`dominios do embed: o FastAPI respondeu ${resposta.status}`)
  }
  const corpo: unknown = await resposta.json()
  const dominios = lerDominios(
    typeof corpo === 'object' && corpo !== null ? (corpo as Record<string, unknown>).dominios : undefined,
  )
  if (!dominios) {
    throw new Error('dominios do embed: o FastAPI devolveu um corpo fora do formato')
  }
  return dominios
}

export function dominiosDoEmbed(): Promise<readonly string[]> {
  const agora = Date.now()
  if (memoria && agora < memoria.vence) {
    return memoria.dominios
  }
  const entrada: Memoria = { vence: agora + PRAZO_DO_SUCESSO_MS, dominios: Promise.resolve([]) }
  entrada.dominios = buscar().catch((erro: unknown) => {
    // Sem esta linha o embed sumiria de todo site sem rastro. O erro e do
    // FastAPI ou da rede, e nao carrega dado de visitante.
    console.error('proxy: dominios do embed indisponiveis', erro)
    entrada.vence = Date.now() + PRAZO_DA_FALHA_MS
    return []
  })
  memoria = entrada
  return entrada.dominios
}

/** So para os testes: cada um comeca sem memoria. */
export function esquecerDominiosDoEmbed(): void {
  memoria = null
}

export type Etapa = {
  nome: string
  quantidade: number | null
  disponivel: boolean
  conversaoDaAnterior: number | null
}

export type Indicadores = Record<string, number | Record<string, number> | null>

export type Funil = {
  etapas: Etapa[]
  indicadores: Indicadores
  indisponiveis: string[]
}

export type Filtros = {
  de: string
  ate: string
  canal?: string
  intencao?: string
  temperatura?: string
  corretorId?: string
}

export class ErroDeMetricas extends Error {
  status: number

  constructor(status: number, mensagem: string) {
    super(mensagem)
    this.name = 'ErroDeMetricas'
    this.status = status
  }
}

/**
 * Busca o funil no FastAPI. **Roda so no servidor**: le `MOBIA_ADMIN_TOKEN`,
 * que nao e `NEXT_PUBLIC_*` de proposito -- o token e de admin total, e um
 * `NEXT_PUBLIC_` o entregaria a qualquer navegador que abrisse o painel.
 *
 * `revalidate: 60` e o teto de defasagem da RN-17.3, e nao um numero
 * escolhido a esmo. Ele tambem e o que faz N navegadores com o painel aberto
 * virarem UMA chamada por minuto ao FastAPI -- que ve o IP deste servidor, e
 * nao o de cada navegador, e aplica 100 requisicoes por minuto por IP.
 */
export async function buscarFunil(filtros: Filtros): Promise<Funil> {
  const base = process.env.MOBIA_API_BASE ?? 'http://localhost:8000'
  const url = new URL('/api/v1/metricas/funil', base)

  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) {
      url.searchParams.set(chave, valor)
    }
  }

  const resposta = await fetch(url, {
    headers: { 'X-Admin-Token': process.env.MOBIA_ADMIN_TOKEN ?? '' },
    next: { revalidate: 60 },
  })

  if (!resposta.ok) {
    // O `detail` do FastAPI e o que nomeia o filtro recusado num 422. Sem
    // ele, a pagina so poderia dizer "algum filtro esta invalido" e mandar a
    // gerente procurar em cinco. O corpo pode nao ser JSON (um 502 de proxy,
    // por exemplo), e ai o status sozinho ja diz o suficiente.
    let detalhe = `o backend respondeu ${resposta.status}`
    try {
      const corpo = await resposta.json()
      if (typeof corpo?.detail === 'string') {
        detalhe = corpo.detail
      }
    } catch {
      // corpo nao-JSON: fica o detalhe generico acima.
    }
    throw new ErroDeMetricas(resposta.status, detalhe)
  }

  return (await resposta.json()) as Funil
}

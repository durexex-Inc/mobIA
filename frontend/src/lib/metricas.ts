import { chamarApi } from '@/lib/servidor/api'

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

type ErroDeValidacao = { loc?: unknown[]; msg?: string }

/**
 * A razao da recusa, no texto mais especifico que o corpo permitir.
 *
 * **O `detail` do FastAPI vem em DUAS formas, e as duas importam.** Os 422
 * que `montar_recorte` levanta trazem `detail` como string ja escrita para
 * quem le. Os 422 do proprio FastAPI -- UUID malformado no `corretorId`,
 * data invalida no `de` -- trazem uma LISTA de objetos com `loc`, e tratar
 * so a string faria a tela anunciar que ha um filtro errado e se recusar a
 * dizer qual.
 *
 * Corpo nao-JSON (um 502 de proxy, por exemplo) cai no generico: ali o
 * status sozinho ja diz o que da para dizer.
 */
async function detalheDe(resposta: Response): Promise<string> {
  try {
    const corpo = await resposta.json()

    if (typeof corpo?.detail === 'string') {
      return corpo.detail
    }

    if (Array.isArray(corpo?.detail)) {
      const campos = (corpo.detail as ErroDeValidacao[])
        .map((erro) => erro.loc?.at(-1))
        .filter((campo): campo is string => typeof campo === 'string')
      if (campos.length > 0) {
        return `valor invalido em ${[...new Set(campos)].join(', ')}`
      }
    }
  } catch {
    // corpo nao-JSON: cai no generico abaixo.
  }

  return `o backend respondeu ${resposta.status}`
}

/**
 * Busca o funil no FastAPI.
 *
 * **Roda so no servidor**, e desde a TEC-302 isso e garantido em vez de
 * combinado: a chamada sai por `servidor/api.ts`, que importa `server-only` e
 * portanto faz o build reprovar se este modulo for parar num componente de
 * cliente. Ate a TEC-302 a leitura de `MOBIA_ADMIN_TOKEN` era aqui, e nada
 * impedia que um `'use client'` a levasse para o bundle do navegador.
 *
 * `revalidate: 60` e o teto de defasagem da RN-17.3, e nao um numero escolhido
 * a esmo. Ele tambem e o que faz N navegadores com o painel aberto virarem UMA
 * chamada por minuto ao FastAPI -- que ve o IP deste servidor, e nao o de cada
 * navegador, e aplica 100 requisicoes por minuto por IP.
 *
 * **E por ser cacheada que esta chamada NAO leva `X-Request-Id`.** Header entra
 * na chave do Data Cache, entao um id por requisicao zeraria a taxa de acerto e
 * desfaria o paragrafo acima sem nada ficar vermelho. O tipo de
 * `chamarApi` recusa os dois juntos; a razao inteira esta la.
 */
export async function buscarFunil(filtros: Filtros): Promise<Funil> {
  const busca = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) {
      busca.set(chave, valor)
    }
  }

  const resposta = await chamarApi('/api/v1/metricas/funil', {
    busca,
    revalidarEmSegundos: 60,
  })

  if (!resposta.ok) {
    throw new ErroDeMetricas(resposta.status, await detalheDe(resposta))
  }

  return (await resposta.json()) as Funil
}

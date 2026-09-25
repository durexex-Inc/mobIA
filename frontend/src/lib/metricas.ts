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
  /**
   * O `X-Request-Id` da RESPOSTA, quando ela trouxe um (TEC-313, D3).
   *
   * **Nao e um id que nos mandamos** -- o caminho do funil deliberadamente nao
   * manda `X-Request-Id`, porque header entra na chave do Data Cache e um id
   * por requisicao zeraria a taxa de acerto (ver `buscarFunil` abaixo e o
   * README). Este e o id que o FastAPI GERA quando a requisicao chega sem um, e
   * devolve na resposta desde a TEC-368. E ele que identifica a linha do log do
   * backend, que e quem alguem vai consultar num 5xx.
   *
   * `null` quando a resposta nao trouxe nenhum -- um 502 de proxy nunca chegou
   * ao FastAPI. A tela OMITE o campo nesse caso, em vez de inventar: um id
   * falso mandaria alguem procurar no log uma linha que nao existe.
   */
  requestId: string | null
  /**
   * Os campos que o backend recusou, num 422.
   *
   * Estruturado, e nao dentro da prosa de `message`: e a tela que decide onde
   * por a mensagem, e para poe-la AO LADO DO CAMPO ela precisa do nome, nao de
   * uma frase que o contem. Vazio quando o 422 nao aponta campo nenhum -- os
   * que `montar_recorte` levanta trazem `detail` como string ja escrita --, e
   * ai o aviso vai acima do formulario, que e o lugar certo para um erro que
   * nao e de nenhum campo. Ver a D5 do desenho.
   */
  campos: string[]

  constructor(
    status: number,
    mensagem: string,
    opcoes: { requestId?: string | null; campos?: string[] } = {},
  ) {
    super(mensagem)
    this.name = 'ErroDeMetricas'
    this.status = status
    this.requestId = opcoes.requestId ?? null
    this.campos = opcoes.campos ?? []
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
async function detalheDe(resposta: Response): Promise<{ mensagem: string; campos: string[] }> {
  try {
    const corpo = await resposta.json()

    if (typeof corpo?.detail === 'string') {
      return { mensagem: corpo.detail, campos: [] }
    }

    if (Array.isArray(corpo?.detail)) {
      const campos = [
        ...new Set(
          (corpo.detail as ErroDeValidacao[])
            .map((erro) => erro.loc?.at(-1))
            .filter((campo): campo is string => typeof campo === 'string'),
        ),
      ]
      if (campos.length > 0) {
        // A prosa continua sendo montada, e nao virou dispensavel: ela e o que
        // a tela mostra quando o campo citado nao existe no formulario -- um
        // `loc` do FastAPI pode apontar para algo que a UI nao desenha.
        return { mensagem: `valor invalido em ${campos.join(', ')}`, campos }
      }
    }
  } catch {
    // corpo nao-JSON: cai no generico abaixo.
  }

  return { mensagem: `o backend respondeu ${resposta.status}`, campos: [] }
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
    const { mensagem, campos } = await detalheDe(resposta)
    throw new ErroDeMetricas(resposta.status, mensagem, {
      // O id vem da RESPOSTA -- ver o campo na classe. Ler o header aqui nao
      // custa cache nenhum: e caminho de erro, e erro nao e o que se cacheia.
      requestId: resposta.headers.get('x-request-id'),
      campos,
    })
  }

  return (await resposta.json()) as Funil
}

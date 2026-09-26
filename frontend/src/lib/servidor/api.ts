import 'server-only'

/**
 * A UNICA porta deste projeto para o FastAPI (TEC-302).
 *
 * `import 'server-only'` na primeira linha e o gate, e ele e de build: o Next
 * reprova `next build` se este modulo for arrastado para um componente de
 * cliente. Antes da TEC-302 o token nao chegava ao navegador por acidente de
 * onde o codigo estava importado -- `'use client'` no topo da pagina bastava
 * para o quebrar, e nenhum dos tres gates do job `Frontend` dizia nada.
 *
 * O pacote `server-only` esta instalado apesar de o Next nao usar o conteudo
 * dele: quem precisa e o passo `Running TypeScript` do build, que sem a
 * declaracao do modulo reprova com `Cannot find module 'server-only'`.
 */

/**
 * Cache e correlacao sao MUTUAMENTE EXCLUSIVOS, e o tipo e quem garante.
 *
 * O Data Cache do Next casa uma requisicao por URL, metodo, **headers** e
 * corpo (`fetch` API reference, Next 16). Um `X-Request-Id` novo a cada
 * requisicao num fetch cacheado da uma entrada de cache por acesso: taxa de
 * acerto zero, e cada navegador com o painel aberto volta a ser uma chamada ao
 * FastAPI por carregamento. Isso derruba a propriedade que a D9 da TEC-190 usou
 * para justificar que o limite de 100 requisicoes por minuto por IP nao derruba
 * o painel -- o FastAPI ve o IP deste servidor, nao o de cada navegador.
 *
 * O modo de falhar e o pior que existe: nada reprova. Nenhum teste fica
 * vermelho e o painel continua correto; a enxurrada so aparece quando muita
 * gente abrir a tela ao mesmo tempo. Por isso a exclusao e do TIPO, e nao um
 * aviso em comentario: passar os dois juntos e erro de compilacao.
 */
type ChamadaCacheada = {
  revalidarEmSegundos: number
  idDeRequisicao?: never
}

type ChamadaSemCache = {
  revalidarEmSegundos?: never
  idDeRequisicao?: string
}

export type OpcoesDaChamada = {
  /**
   * O access token de quem esta logado, que vira `Authorization: Bearer`
   * (TEC-309, D7). Ausente so nas rotas de `/auth/*` que produzem o token.
   *
   * **Nao ha fallback para token compartilhado**, e isso e o ponto: antes da
   * TEC-309 toda chamada saia com o `X-Admin-Token` do ambiente, um ADMIN sem
   * usuario. Chamada sem `acesso` agora chega ao FastAPI sem credencial nenhuma
   * e leva 403 -- que e o desfecho certo para quem esqueceu de passar a sessao.
   */
  acesso?: string
  metodo?: string
  busca?: URLSearchParams
  corpo?: BodyInit | null
  tipoDoCorpo?: string | null
} & (ChamadaCacheada | ChamadaSemCache)

/** Onde o FastAPI atende. Igual ao default anterior da TEC-190. */
function baseDaApi(): string {
  return process.env.MOBIA_API_BASE ?? 'http://localhost:8000'
}

/**
 * Chama o FastAPI, com o access token de quem esta logado quando houver um.
 *
 * Devolve a `Response` crua: quem chama e que sabe ler o corpo. O painel tem a
 * leitura de `detail` do FastAPI em `metricas.ts`; o proxy `/bff/*` repassa o
 * corpo sem o interpretar.
 */
export async function chamarApi(caminho: string, opcoes: OpcoesDaChamada): Promise<Response> {
  const url = new URL(caminho, baseDaApi())
  if (opcoes.busca) {
    url.search = opcoes.busca.toString()
  }

  // Registro simples, e nao `Headers`: todas as chaves sao nossas e fixas, e
  // `Headers` nao acrescenta nada aqui alem de esconder o valor de quem inspeciona
  // a chamada em teste.
  const cabecalhos: Record<string, string> = {}
  if (opcoes.acesso) {
    cabecalhos.Authorization = `Bearer ${opcoes.acesso}`
  }
  if (opcoes.idDeRequisicao) {
    cabecalhos['X-Request-Id'] = opcoes.idDeRequisicao
  }
  if (opcoes.tipoDoCorpo) {
    cabecalhos['Content-Type'] = opcoes.tipoDoCorpo
  }

  // Sem `revalidarEmSegundos` a chamada e explicitamente `no-store`. Route
  // Handler ja nao e cacheado por padrao; a declaracao existe porque a razao
  // nao e performance: desde a TEC-309 as respostas sao por usuario, e um
  // cache que servisse a de um para outro seria vazamento.
  //
  // **A chamada COM cache nao vaza, e por um motivo que nao esta nesta linha.**
  // O Data Cache casa por URL, metodo, cabecalhos e corpo (referencia de
  // `fetch`, Next 16), entao o `Authorization` acima separa as entradas: cada
  // token tem a sua. Quem trocar o Bearer por algo fora dos cabecalhos -- um
  // parametro de busca que o cache ignore, por exemplo -- desfaz isso.
  const cache =
    opcoes.revalidarEmSegundos === undefined
      ? ({ cache: 'no-store' } as const)
      : ({ next: { revalidate: opcoes.revalidarEmSegundos } } as const)

  return fetch(url, {
    method: opcoes.metodo ?? 'GET',
    headers: cabecalhos,
    body: opcoes.corpo ?? null,
    ...cache,
  })
}

/**
 * As tres decisoes do proxy `/bff/*` (TEC-302), sem ambiente e sem rede.
 *
 * Elas moram aqui e nao dentro do Route Handler pela mesma razao que o lado
 * Python separa `domain/metricas/filtros.py` de `api/routes/metricas.py`: assim
 * a allowlist, a regra de `Origin` e a forma do `X-Request-Id` se testam como
 * funcao pura, sem subir o runtime do Next.
 *
 * Este modulo NAO importa `server-only`: ele nao le segredo nenhum. Quem le e
 * `servidor/api.ts`.
 */

/**
 * O que o navegador pode alcancar atraves do proxy.
 *
 * Uma entrada so, e e a que o epico precisa. A allowlist nasceu (TEC-302) como
 * o que continha o estrago enquanto o proxy nao autenticava ninguem: esta rota
 * e leitura agregada, e o proprio router dela no backend registra que nao ha
 * dado pessoal de lead na resposta, so contagens e medias. Desde a TEC-309 o
 * proxy exige sessao, e a allowlist continua pela outra razao que sempre teve:
 * o navegador so alcanca do FastAPI o que alguem decidiu expor.
 *
 * `*` casa EXATAMENTE um segmento. Nenhuma rota de hoje precisa dele, e ele
 * existe mesmo assim: sem ele, a primeira rota parametrizada do epico chega com
 * a tentacao do `startsWith`, e `startsWith` e o furo classico de allowlist --
 * `/api/v1/metricas/funil` como prefixo libera
 * `/api/v1/metricas/funil/../../corretores`. O custo de evitar isso e uma linha
 * de casamento e dois testes.
 */
export const ROTAS_PERMITIDAS: ReadonlyArray<{
  readonly metodo: string
  readonly padrao: readonly string[]
}> = [{ metodo: 'GET', padrao: ['api', 'v1', 'metricas', 'funil'] }]

/** `GET` e `HEAD`: os que nao alteram nada do outro lado. */
const METODOS_SEGUROS: ReadonlySet<string> = new Set(['GET', 'HEAD'])

/**
 * Segmento que nunca pode entrar num caminho remontado.
 *
 * Barra e contrabando de separador: o `[...rota]` do Next entrega os segmentos
 * ja DECODIFICADOS, entao um `%2F` na URL chega aqui como `/` dentro de um
 * segmento so, e reapareceria como separador na hora do `join`. Barra invertida
 * pela mesma razao em cliente que a normalize. Byte nulo porque trunca caminho
 * em varias camadas abaixo.
 */
const CARACTERE_PROIBIDO = /[/\\\0]/

function segmentoValido(segmento: string): boolean {
  return (
    segmento.length > 0 &&
    segmento !== '.' &&
    segmento !== '..' &&
    !CARACTERE_PROIBIDO.test(segmento)
  )
}

function casa(padrao: readonly string[], segmentos: readonly string[]): boolean {
  return (
    padrao.length === segmentos.length &&
    padrao.every((esperado, i) => esperado === '*' || esperado === segmentos[i])
  )
}

/**
 * O caminho que pode ir ao FastAPI, ou `null` quando a requisicao nao passa.
 *
 * **O caminho devolvido e REMONTADO a partir dos segmentos validados**, nunca
 * copiado da URL de entrada. E isso que mata o traversal por construcao: se um
 * `..` chegasse, ele reprova em `segmentoValido` antes de qualquer casamento, e
 * o que se junta depois ja passou por essa peneira.
 *
 * Metodo certo em rota errada e metodo errado em rota certa recusam os dois --
 * a entrada da tabela e o par, nao a rota sozinha.
 */
export function caminhoPermitido(metodo: string, segmentos: readonly string[]): string | null {
  if (segmentos.length === 0 || !segmentos.every(segmentoValido)) {
    return null
  }

  const permitida = ROTAS_PERMITIDAS.some(
    (rota) => rota.metodo === metodo.toUpperCase() && casa(rota.padrao, segmentos),
  )

  return permitida ? `/${segmentos.join('/')}` : null
}

/**
 * A regra de `Origin`, assimetrica entre metodo seguro e mutacao.
 *
 * | `Origin`                | metodo    | decisao |
 * | ----------------------- | --------- | ------- |
 * | presente e diferente    | qualquer  | recusa  |
 * | ausente                 | mutacao   | recusa  |
 * | ausente                 | seguro    | passa   |
 * | presente e igual        | qualquer  | passa   |
 *
 * **A assimetria e como o navegador se comporta, nao frouxidao.** Em requisicao
 * de mesma origem com metodo seguro o navegador NAO manda `Origin` --
 * navegacao, prefetch e `<img>` chegariam sem ele, e exigi-lo quebraria o
 * consumidor legitimo. Em `fetch` de mesma origem com metodo inseguro ele
 * manda, e por isso a ausencia em mutacao pode ser recusada sem custo.
 *
 * A letra da card fecha com isso: ela recusa `Origin` "diferente do proprio
 * dominio", e ausente nao e diferente.
 *
 * O literal `"null"` -- que iframe em sandbox e alguns redirecionamentos enviam
 * -- cai no primeiro ramo e recusa, porque nao e igual a origem propria. E o
 * desejado: origem opaca nao e mesma origem.
 *
 * **Isto e defesa de CSRF, e nao autenticacao.** Vale porque quem escreve o
 * header e o navegador; `curl` nao manda `Origin` nenhum e por isso um `GET`
 * dele passa desta checagem. Quem autentica e a sessao, conferida logo depois
 * no Route Handler (TEC-309).
 */
export function origemAceita({
  origem,
  propriaOrigem,
  metodo,
}: {
  origem: string | null
  propriaOrigem: string
  metodo: string
}): boolean {
  if (origem) {
    return origem === propriaOrigem
  }
  return METODOS_SEGUROS.has(metodo.toUpperCase())
}

/**
 * De 1 a 200 caracteres de `[A-Za-z0-9._:-]`. Cobre UUID, ULID e os ids de
 * rastreamento usuais sem deixar passar quebra de linha nem texto livre.
 */
const FORMA_DO_ID = /^[A-Za-z0-9._:-]{1,200}$/

/**
 * O `X-Request-Id` que segue para o FastAPI.
 *
 * O de entrada e propagado quando tem forma aceitavel. Quando nao tem, e
 * SUBSTITUIDO por um novo, e nao recusado: o cliente nao deve perder a
 * requisicao por causa de um header de diagnostico. Aceita-lo sem olhar seria
 * deixar entrada nao confiavel escrever no log de quem esta do outro lado.
 */
export function idDeRequisicao(entrada: string | null | undefined): string {
  return entrada && FORMA_DO_ID.test(entrada) ? entrada : crypto.randomUUID()
}

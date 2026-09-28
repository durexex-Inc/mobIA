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
 * A allowlist nasceu (TEC-302) com uma entrada so, o funil, como o que
 * continha o estrago enquanto o proxy nao autenticava ninguem: aquela rota e
 * leitura agregada, sem dado pessoal de lead. Desde a TEC-309 o proxy exige
 * sessao, e a allowlist continua pela outra razao que sempre teve: o navegador
 * so alcanca do FastAPI o que alguem decidiu expor.
 *
 * **A segunda entrada, a transcricao (TEC-324), E dado pessoal**, e passa
 * aqui porque a sessao e o FastAPI ja cuidam dela: o JWT e o de quem esta
 * logado, o recorte do CORRETOR e do backend, e cada pagina grava na trilha.
 * O que a allowlist ainda decide e QUAIS rotas de lead chegam ao navegador:
 * desde a TEC-326 sao sete -- a transcricao, assumir, devolver, a revelacao,
 * a correcao da qualificacao, a resposta do corretor e a regeneracao do resumo
 * --, e o detalhe continua fora.
 *
 * `*` casa EXATAMENTE um segmento. A primeira rota que precisou dele foi a
 * transcricao do lead (TEC-324); ele foi escrito antes, porque sem ele a
 * primeira rota parametrizada chegaria com a tentacao do `startsWith`, e `startsWith` e o furo classico de allowlist --
 * `/api/v1/metricas/funil` como prefixo libera
 * `/api/v1/metricas/funil/../../corretores`. O custo de evitar isso e uma linha
 * de casamento e dois testes.
 */
export const ROTAS_PERMITIDAS: ReadonlyArray<{
  readonly metodo: string
  readonly padrao: readonly string[]
}> = [
  { metodo: 'GET', padrao: ['api', 'v1', 'metricas', 'funil'] },
  // A transcricao do lead (TEC-324, D2): o "carregar anteriores" busca daqui.
  // Entra SO o `GET` das mensagens -- o detalhe continua fora do alcance do
  // navegador. Cada pagina grava um acesso na trilha (D3 da TEC-193), e e por
  // isso que so o clique do usuario a pede.
  { metodo: 'GET', padrao: ['api', 'v1', 'leads', '*', 'mensagens'] },
  // Assumir e devolver a conversa (TEC-327, D4): as primeiras MUTACOES que o
  // navegador faz pelo proxy. A regra de `Origin` ja recusa mutacao sem ela
  // (CSRF), e o corretor em nome de quem se age e o da claim do JWT -- o corpo
  // nem e lido pelo FastAPI.
  { metodo: 'POST', padrao: ['api', 'v1', 'leads', '*', 'assumir'] },
  { metodo: 'POST', padrao: ['api', 'v1', 'leads', '*', 'devolver'] },
  // Revelar telefone ou e-mail (TEC-330, D5): o unico caminho pelo qual o
  // navegador recebe dado pessoal de lead em claro. Quem decide se pode e o
  // `VER_DADOS_COMPLETOS` do JWT, no FastAPI, que grava a trilha antes de
  // responder.
  { metodo: 'POST', padrao: ['api', 'v1', 'leads', '*', 'revelar'] },
  // Corrigir a qualificacao (TEC-329, D6). O unico `PATCH`: o pedido e
  // parcial, e o recorte do CORRETOR e do FastAPI, como nas outras mutacoes.
  { metodo: 'PATCH', padrao: ['api', 'v1', 'leads', '*', 'qualificacao'] },
  // A resposta do corretor (TEC-328, D5): o `POST` da mesma rota cujo `GET`
  // e a transcricao. O corretor e o da claim do JWT, e o `messageId` do corpo
  // e o que torna o reenvio seguro.
  { metodo: 'POST', padrao: ['api', 'v1', 'leads', '*', 'mensagens'] },
  // Regenerar o resumo (TEC-326, D5): a rota e do handoff, e nao do lead,
  // porque o resumo e dele. O dono e conferido pelo FastAPI.
  { metodo: 'POST', padrao: ['api', 'v1', 'handoffs', '*', 'resumo'] },
  // Eliminar os dados do titular (TEC-342, D2): ao contrario do download da
  // TEC-341, a resposta e um JSON pequeno sem cabecalho especial e a chamada
  // ja sabe o `leadId` de antemao -- sem nada a resolver antes de repassar,
  // o proxy generico basta.
  { metodo: 'DELETE', padrao: ['api', 'v1', 'leads', '*', 'dados-pessoais'] },
]

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

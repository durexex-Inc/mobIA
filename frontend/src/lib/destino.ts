/**
 * Para onde o login manda quem acabou de entrar (TEC-309, D6).
 *
 * Funcao pura e sem `server-only`: nao le segredo nenhum, e a pagina de login
 * e as duas rotas de POST a usam do mesmo jeito.
 */

/** A pagina inicial de todos os papeis, por enquanto -- a de cada um e a TEC-312. */
export const PAGINA_INICIAL = '/'

/**
 * Origem de referencia para a checagem final. Nao e o dominio do painel e nao
 * precisa ser: so importa que resolver o valor contra ela nao saia dela.
 */
const ORIGEM_DE_REFERENCIA = 'http://painel.invalid'

// Caractere de controle, incluindo CR e LF: e como se contrabandeia quebra de
// cabecalho para dentro do `Location`.
const CONTROLE = /[\u0000-\u001f\u007f]/

/** Prefixos que levariam a um laco (`/login`) ou a um JSON (`/bff`). */
const PREFIXOS_PROIBIDOS = ['/login', '/bff']

function comecaCom(caminho: string, prefixo: string): boolean {
  return caminho === prefixo || caminho.startsWith(`${prefixo}/`) || caminho.startsWith(`${prefixo}?`)
}

/**
 * O caminho interno para onde mandar, ou a pagina inicial.
 *
 * **As checagens de forma vem antes da resolucao, e a resolucao vem por
 * ultimo, para pegar o que elas nao previram.** `//site-externo.com` e
 * `/\site-externo.com` comecam com barra e sao URL de outro host -- o segundo
 * porque navegador normaliza `\` para `/`. Recusar pela forma e o que torna o
 * motivo legivel; resolver contra uma origem de referencia e conferir que ela
 * nao mudou e o que fecha a porta para o caso que ninguem listou.
 *
 * O valor devolvido e REMONTADO do `URL` resolvido (caminho, busca e ancora),
 * e nao copiado da entrada: e o que o navegador de fato vai pedir.
 */
export function destinoSeguro(bruto: string | null | undefined): string {
  if (!bruto || !bruto.startsWith('/') || bruto.startsWith('//') || bruto.startsWith('/\\')) {
    return PAGINA_INICIAL
  }
  if (CONTROLE.test(bruto) || bruto.includes('\\')) {
    return PAGINA_INICIAL
  }

  let resolvido: URL
  try {
    resolvido = new URL(bruto, ORIGEM_DE_REFERENCIA)
  } catch {
    return PAGINA_INICIAL
  }
  if (resolvido.origin !== ORIGEM_DE_REFERENCIA) {
    return PAGINA_INICIAL
  }
  if (PREFIXOS_PROIBIDOS.some((prefixo) => comecaCom(resolvido.pathname, prefixo))) {
    return PAGINA_INICIAL
  }

  return `${resolvido.pathname}${resolvido.search}${resolvido.hash}`
}

/** Os motivos que a tela de login sabe explicar. Ver `app/login/page.tsx`. */
export type MotivoDoLogin =
  | 'credencial'
  | 'mfa_obrigatorio'
  | 'codigo'
  | 'expirado'
  | 'muitas_tentativas'
  | 'indisponivel'
  | 'sessao_expirada'

/**
 * A URL da tela de login, com o destino preservado.
 *
 * O `returnTo` vai JA filtrado por `destinoSeguro`: a tela de login devolve o
 * valor num campo escondido, e filtrar so na chegada deixaria um valor hostil
 * viajando por tres requisicoes antes de ser recusado.
 */
export function urlDoLogin({
  returnTo,
  erro,
  etapa,
}: {
  returnTo?: string | null
  erro?: MotivoDoLogin
  etapa?: 'mfa'
} = {}): string {
  const busca = new URLSearchParams()
  const destino = destinoSeguro(returnTo)
  if (destino !== PAGINA_INICIAL) {
    busca.set('returnTo', destino)
  }
  if (etapa) {
    busca.set('etapa', etapa)
  }
  if (erro) {
    busca.set('erro', erro)
  }
  const texto = busca.toString()
  return texto ? `/login?${texto}` : '/login'
}

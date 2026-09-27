/**
 * Os dominios em que o chat pode ser embutido (TEC-345, D1): a conferencia do
 * formato e a traducao para a CSP e para o `Origin`.
 *
 * Sem `server-only`, de proposito: o proxy importa isto, e o pacote
 * `server-only` e para o bundle de componentes, nao para o proxy. Nao ha
 * segredo aqui -- os dominios sao os sites onde o chat aparece.
 */

/**
 * `host` ou `host:porta`, em minusculas. Copia de `_DOMINIO_DO_CHAT` em
 * `src/mobia/domain/configuracao/vigente.py`, que recusa gravar outra coisa.
 *
 * **A conferencia e repetida aqui porque o valor e interpolado na CSP.** Um
 * `;` ou um espaco abririam uma diretiva nova no cabecalho; o formato fechado
 * e o que impede, e nao se confia so em quem gravou.
 */
const ROTULO = '[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
// `String.raw`, e nao template comum: nele `\.` vira `.`, que casa qualquer
// caractere -- inclusive o espaco que esta conferencia existe para recusar.
const DOMINIO = new RegExp(String.raw`^${ROTULO}(?:\.${ROTULO})*(?::[0-9]{1,5})?$`)

/**
 * Os dominios que o FastAPI devolveu, ou `null` se o campo nao e uma lista.
 *
 * Entrada fora do formato e DESCARTADA, e nao derruba a lista: o backend nao
 * deixa gravar uma, entao ela so aparece se as duas copias do formato
 * divergirem -- e ai perder um site e melhor que perder todos.
 */
export function lerDominios(bruto: unknown): string[] | null {
  if (!Array.isArray(bruto)) {
    return null
  }
  return bruto.filter((dominio): dominio is string => typeof dominio === 'string' && DOMINIO.test(dominio))
}

/**
 * O `host` de um `Origin` (`host:porta`, sem a porta padrao do esquema), na
 * mesma forma dos dominios cadastrados -- ou `null` se nao for uma origem web.
 *
 * `URL` faz a normalizacao que importa: baixa a caixa do host e omite a porta
 * padrao, exatamente como o navegador escreve o `Origin`.
 */
export function hostDoOrigin(origem: string | null): string | null {
  if (!origem) {
    return null
  }
  try {
    const url = new URL(origem)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.host : null
  } catch {
    return null
  }
}

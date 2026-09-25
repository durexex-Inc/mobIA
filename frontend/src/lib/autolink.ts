/**
 * A quebra de um texto de mensagem em trechos: o que e link e o que e texto
 * (TEC-356, terceira regra da card).
 *
 * **Devolve SEGMENTOS, e nao uma string de HTML, e essa e a decisao inteira
 * deste modulo.** Uma funcao que devolvesse `<a href=...>` obrigaria quem a
 * consome a usar `dangerouslySetInnerHTML` -- ou seja, a fechar um buraco de
 * XSS abrindo outro, numa card cujo proposito e reduzir superficie de XSS.
 * Com segmentos, o React escapa cada trecho de texto por construcao, e nao ha
 * caminho pelo qual a mensagem do lead vire marcacao.
 *
 * **Nada chama este modulo ainda.** A tela de transcricao e a TEC-324, e nao
 * ha hoje nenhum componente que renderize mensagem de lead. Ele nasce com a
 * assinatura pronta em vez de como `TODO` para que aquela card o use em vez de
 * reinventar a regra -- ver a D8 e a lacuna L4 do desenho.
 */

/** O `rel` obrigatorio de todo link gerado a partir de texto de terceiro.
 *
 * Mora aqui, ao lado da regra, e nao dentro do componente: se vivesse so la,
 * uma segunda tela que renderizasse mensagem escreveria o proprio `rel` e
 * erraria em silencio. `noopener`/`noreferrer` cortam o acesso ao `window.opener`
 * e o vazamento de referer; `nofollow` existe porque o texto e de terceiro e
 * nao queremos emprestar reputacao a ele.
 */
export const REL_DE_LINK_EXTERNO = 'noopener noreferrer nofollow'

export type Segmento =
  | { tipo: 'texto'; valor: string }
  | { tipo: 'link'; valor: string; href: string }

/**
 * Casa candidatos a URL. A validacao de verdade e o `URL()` abaixo -- esta
 * expressao so acha onde olhar.
 *
 * Exige `http://` ou `https://` explicito: e o que mantem `javascript:`,
 * `data:` e `vbscript:` fora por construcao, em vez de por lista de bloqueio.
 * Lista de bloqueio erra para o lado de deixar passar o esquema que ninguem
 * lembrou; exigir o esquema certo erra para o lado de nao linkar, que e o
 * lado barato.
 */
const CANDIDATO = /https?:\/\/[^\s<>"']+/gi

/**
 * Pontuacao que quase nunca faz parte da URL e quase sempre e da frase.
 * "Veja https://exemplo.com." nao deve linkar o ponto final.
 *
 * O parenteses fecha a lista porque "(https://exemplo.com)" e comum; o preco e
 * que uma URL que termine em parenteses de verdade perde o ultimo caractere.
 * Aceito: e mais barato que linkar pontuacao em toda frase.
 */
const PONTUACAO_FINAL = /[.,;:!?)\]}]+$/

function hrefSeguro(bruto: string): string | null {
  try {
    const url = new URL(bruto)
    // Confere o protocolo JA PARSEADO, e nao o texto: e o parser do navegador
    // que decide o que aquela string significa, e e a decisao dele que importa.
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

/**
 * Quebra `texto` em segmentos. Texto sem link nenhum devolve um segmento so.
 *
 * O valor do segmento de link e o texto COMO ESTAVA, nao o `href` normalizado:
 * quem le a transcricao precisa ver o que o lead escreveu. O `href`
 * normalizado vai no atributo.
 */
export function segmentosDe(texto: string): Segmento[] {
  const segmentos: Segmento[] = []
  let cursor = 0

  for (const encontrado of texto.matchAll(CANDIDATO)) {
    const inicio = encontrado.index
    const bruto = encontrado[0]
    const semPontuacao = bruto.replace(PONTUACAO_FINAL, '')
    const href = hrefSeguro(semPontuacao)

    if (href === null) {
      // Candidato que nao vira URL valida continua sendo texto, e o laco segue
      // do ponto em que estava -- nada e descartado.
      continue
    }

    if (inicio > cursor) {
      segmentos.push({ tipo: 'texto', valor: texto.slice(cursor, inicio) })
    }
    segmentos.push({ tipo: 'link', valor: semPontuacao, href })
    cursor = inicio + semPontuacao.length
  }

  if (cursor < texto.length) {
    segmentos.push({ tipo: 'texto', valor: texto.slice(cursor) })
  }

  return segmentos
}

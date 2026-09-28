/**
 * O telefone que a visitante digita no campo com mascara do chat (TEC-353,
 * D2). Puro: so digitos entram, e o que sai e o texto da mensagem.
 *
 * **A regra e a de `normalizar` no servidor** (`src/mobia/domain/identidade/
 * telefone.py`), menos o que ele aceita e o campo nao precisa: o `+55` (o
 * campo o poe), o zero de tronco e o celular antigo de oito digitos. O
 * servidor vincula a sessao pela regex sobre a mensagem (TEC-129), entao o
 * texto que sai daqui tem de casar com ela -- e `tests/unit/
 * test_contrato_do_chat_web.py` confere isso do lado de la.
 */

/** O maximo de digitos do campo: DDD e nove do celular. */
export const MAXIMO_DE_DIGITOS = 11

/**
 * DDDs em uso no Brasil. Copia de `_DDDS` em
 * `src/mobia/domain/identidade/telefone.py`: mudar uma sem a outra faz o campo
 * recusar o que o servidor vincularia, ou deixar passar o que ele ignora.
 */
const DDDS = new Set([
  '11', '12', '13', '14', '15', '16', '17', '18', '19',
  '21', '22', '24', '27', '28',
  '31', '32', '33', '34', '35', '37', '38',
  '41', '42', '43', '44', '45', '46', '47', '48', '49',
  '51', '53', '54', '55',
  '61', '62', '63', '64', '65', '66', '67', '68', '69',
  '71', '73', '74', '75', '77', '79',
  '81', '82', '83', '84', '85', '86', '87', '88', '89',
  '91', '92', '93', '94', '95', '96', '97', '98', '99',
]) // prettier-ignore

/** O que o campo mostra quando o numero nao passa (D2). Texto que a visitante le. */
export const FORMATO_ESPERADO =
  'Informe DDD e número: (48) 99999-0021 para celular ou (48) 3333-0021 para fixo.'

/** So os digitos do que foi digitado ou colado, ate o maximo do campo. */
export function digitosDe(bruto: string): string {
  return bruto.replace(/\D/g, '').slice(0, MAXIMO_DE_DIGITOS)
}

/**
 * A mascara enquanto a visitante digita: `(48`, `(48) 9999`, `(48) 99999-0021`.
 * O hifen cai antes dos quatro ultimos digitos, entao o fixo sai
 * `(48) 3333-0021` e o celular `(48) 99999-0021` sem saber de antemao qual e.
 */
export function mascarar(digitos: string): string {
  if (digitos.length === 0) {
    return ''
  }
  const ddd = digitos.slice(0, 2)
  const assinante = digitos.slice(2)
  if (assinante.length === 0) {
    return `(${ddd}`
  }
  if (assinante.length <= 4) {
    return `(${ddd}) ${assinante}`
  }
  const corte = assinante.length - 4
  return `(${ddd}) ${assinante.slice(0, corte)}-${assinante.slice(corte)}`
}

/**
 * O texto da mensagem, `+55 48 99999-0021` ou `+55 48 3333-0021`, ou `null`
 * se o numero nao e um telefone brasileiro em uso: DDD da lista; celular com
 * nove digitos comecando por 9; fixo com oito, comecando de 2 a 5.
 */
export function telefoneParaEnvio(digitos: string): string | null {
  if (!/^\d{10,11}$/.test(digitos)) {
    return null
  }
  const ddd = digitos.slice(0, 2)
  const assinante = digitos.slice(2)
  if (!DDDS.has(ddd)) {
    return null
  }
  const valido = assinante.length === 9 ? assinante.startsWith('9') : /^[2-5]/.test(assinante)
  if (!valido) {
    return null
  }
  return `+55 ${ddd} ${assinante.slice(0, -4)}-${assinante.slice(-4)}`
}

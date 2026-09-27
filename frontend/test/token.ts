/**
 * Um access token com a forma de JWT e a claim `exp` que o teste escolher.
 *
 * Desde a TEC-310 a sessao le o `exp` do access para decidir se renova (D1).
 * Um token de mentira sem `exp` -- `'jwt-da-anelise'` -- conta como vencido, e
 * todo teste que o usasse dispararia uma renovacao que nao pediu. A assinatura
 * e lixo de proposito: o painel nunca a confere, quem confere e o FastAPI.
 *
 * `rotulo` entra na carga para dois tokens do mesmo teste serem distinguiveis.
 */
export function tokenQueExpiraEm(segundos: number, rotulo = 'acesso'): string {
  const b64 = (valor: object) => Buffer.from(JSON.stringify(valor)).toString('base64url')
  const exp = Math.floor(Date.now() / 1000) + segundos
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub: rotulo, exp })}.assinatura`
}

/** Um access que so vence daqui a uma hora: nao dispara renovacao. */
export const ACESSO_VALIDO = tokenQueExpiraEm(3600, 'anelise')

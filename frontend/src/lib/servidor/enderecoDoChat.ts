/**
 * Onde o iframe do chat abre o WebSocket (TEC-346, D2).
 *
 * Lido no servidor -- pela pagina `/embed/chat`, que o passa por prop, e pelo
 * proxy, que monta o `connect-src` -- e nunca por `NEXT_PUBLIC_`: a regra do
 * README e de nenhuma variavel publica, e aqui nao ha necessidade de uma.
 *
 * Sem `server-only` porque o proxy importa este modulo, e ele nao tem segredo.
 */
export function enderecoDoChat(): string {
  const explicito = process.env.MOBIA_WIDGET_WS_URL
  if (explicito) {
    return explicito
  }
  const api = new URL(process.env.MOBIA_API_BASE ?? 'http://localhost:8000')
  api.protocol = api.protocol === 'https:' ? 'wss:' : 'ws:'
  api.pathname = '/widget/chat'
  return api.toString()
}

/** A origem de `enderecoDoChat`, para o `connect-src`. A mesma fonte, para nao divergir. */
export function origemDoChat(): string {
  const url = new URL(enderecoDoChat())
  return `${url.protocol}//${url.host}`
}

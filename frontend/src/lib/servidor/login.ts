import 'server-only'

import { type NextRequest, NextResponse } from 'next/server'

import { type MotivoDoLogin } from '@/lib/destino'
import { origemAceita } from '@/lib/servidor/bff'

/**
 * O que as duas rotas de POST do login (`/login/entrar` e `/login/mfa`)
 * compartilham (TEC-309, D4).
 */

/**
 * A origem do painel, pela mesma regra do proxy `/bff/*`.
 *
 * Atras de proxy, o `Host` que o Next ve pode ser `localhost:3000` enquanto o
 * navegador manda o dominio publico -- e ai o `Origin` de todo login legitimo
 * seria recusado, e o redirecionamento sairia para o host errado.
 */
function origemDoPainel(requisicao: NextRequest): string {
  return process.env.MOBIA_ORIGEM_DO_PAINEL ?? requisicao.nextUrl.origin
}

/**
 * Se o POST veio do proprio painel.
 *
 * **E a defesa contra CSRF de login**, que e menos obvio que o de mutacao:
 * quem ataca faz a vitima entrar na conta DELE, e o que ela digitar depois
 * fica registrado onde ele le. Mesma `origemAceita` do BFF: num POST, `Origin`
 * ausente tambem recusa, porque navegador sempre o manda em POST de formulario.
 */
export function veioDoPainel(requisicao: NextRequest): boolean {
  return origemAceita({
    origem: requisicao.headers.get('origin'),
    propriaOrigem: origemDoPainel(requisicao),
    metodo: 'POST',
  })
}

/**
 * `303 See Other` para um caminho do painel.
 *
 * 303, e nao 302 ou 307: e o status que obriga o navegador a seguir com GET.
 * Com 307 ele repetiria o POST -- com a senha no corpo -- no destino.
 */
export function redirecionar(requisicao: NextRequest, caminho: string): NextResponse {
  return NextResponse.redirect(new URL(caminho, origemDoPainel(requisicao)), 303)
}

/**
 * O motivo que a tela explica, a partir do status do FastAPI.
 *
 * `422` vira credencial errada, e nao um erro proprio: e o FastAPI recusando
 * um campo vazio ou curto demais, e para quem digita isso e "e-mail ou senha
 * incorretos" do mesmo jeito. `429` e o limitador por IP da TEC-205 -- que,
 * atras deste servidor, conta as tentativas de todo mundo juntas (L2).
 */
export function motivoDoStatus(status: number, recusa: MotivoDoLogin): MotivoDoLogin {
  if (status === 401 || status === 422) {
    return recusa
  }
  if (status === 429) {
    return 'muitas_tentativas'
  }
  return 'indisponivel'
}

/** Um campo do formulario como texto, e nunca como `File`. */
export function campo(dados: FormData, nome: string): string {
  const valor = dados.get(nome)
  return typeof valor === 'string' ? valor : ''
}

/** Os dois tokens de uma resposta de sucesso, ou `null` se ela nao os tiver. */
export function tokensDe(corpo: unknown): { acesso: string; refresh: string } | null {
  if (typeof corpo !== 'object' || corpo === null) {
    return null
  }
  const { access, refresh } = corpo as { access?: unknown; refresh?: unknown }
  return typeof access === 'string' && typeof refresh === 'string'
    ? { acesso: access, refresh }
    : null
}

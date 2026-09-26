import { type NextRequest } from 'next/server'

import { destinoSeguro, urlDoLogin } from '@/lib/destino'
import { chamarApi } from '@/lib/servidor/api'
import {
  campo,
  motivoDoStatus,
  redirecionar,
  tokensDe,
  veioDoPainel,
} from '@/lib/servidor/login'
import {
  COOKIE_DA_SESSAO,
  COOKIE_DO_DESAFIO,
  criarSessao,
  guardarDesafio,
  opcoesDoCookie,
  SEGUNDOS_DA_SESSAO,
  SEGUNDOS_DO_DESAFIO,
} from '@/lib/servidor/sessao'

/**
 * O POST do formulario de e-mail e senha (TEC-309, D4).
 *
 * Tres desfechos, e todos terminam em `303`:
 *
 * - senha certa e sem MFA: nasce a sessao, e o navegador vai ao destino;
 * - senha certa de ADMIN: o desafio fica no servidor (D3), e o navegador vai
 *   a etapa do codigo;
 * - qualquer recusa: volta ao login, com o motivo e o destino preservados.
 *
 * **O navegador nunca ve o corpo do FastAPI.** Os tokens e o desafio sao lidos
 * aqui e guardados no Redis; o que sai daqui e um redirecionamento e um cookie
 * com um id opaco.
 */
export async function POST(requisicao: NextRequest) {
  // Corpo que nao e formulario vale como formulario vazio, e nao como 500.
  const dados = await requisicao.formData().catch(() => new FormData())
  const returnTo = campo(dados, 'returnTo')

  if (!veioDoPainel(requisicao)) {
    // Sem motivo na URL: quem manda um POST de outra origem nao precisa de
    // explicacao, e a vitima de um CSRF so ve a tela de login limpa.
    return redirecionar(requisicao, urlDoLogin({ returnTo }))
  }

  let resposta: Response
  try {
    resposta = await chamarApi('/api/v1/auth/login', {
      metodo: 'POST',
      corpo: JSON.stringify({ email: campo(dados, 'email'), senha: campo(dados, 'senha') }),
      tipoDoCorpo: 'application/json',
    })
  } catch {
    return redirecionar(requisicao, urlDoLogin({ returnTo, erro: 'indisponivel' }))
  }

  if (!resposta.ok) {
    // O `403` do FastAPI neste ponto e um so: ADMIN sem MFA habilitado (D5 da
    // TEC-201). Mapeado aqui, e nao em `motivoDoStatus`, porque em outra rota
    // um 403 quer dizer outra coisa.
    const erro =
      resposta.status === 403 ? 'mfa_obrigatorio' : motivoDoStatus(resposta.status, 'credencial')
    return redirecionar(requisicao, urlDoLogin({ returnTo, erro }))
  }

  const corpo: unknown = await resposta.json().catch(() => null)

  const desafio = (corpo as { mfa_requerido?: unknown; desafio?: unknown } | null)
  if (desafio?.mfa_requerido === true && typeof desafio.desafio === 'string') {
    const id = await guardarDesafio(desafio.desafio).catch(() => null)
    if (!id) {
      return redirecionar(requisicao, urlDoLogin({ returnTo, erro: 'indisponivel' }))
    }
    const saida = redirecionar(requisicao, urlDoLogin({ returnTo, etapa: 'mfa' }))
    // O cookie do desafio so viaja para `/login`: e so la que ele serve.
    saida.cookies.set(COOKIE_DO_DESAFIO, id, opcoesDoCookie(SEGUNDOS_DO_DESAFIO, '/login'))
    return saida
  }

  const tokens = tokensDe(corpo)
  if (!tokens) {
    return redirecionar(requisicao, urlDoLogin({ returnTo, erro: 'indisponivel' }))
  }

  // O Redis fora do ar aqui e o mesmo desfecho da API fora do ar: "tente de
  // novo", e nao uma tela de erro depois de a senha ter conferido.
  const id = await criarSessao(tokens).catch(() => null)
  if (!id) {
    return redirecionar(requisicao, urlDoLogin({ returnTo, erro: 'indisponivel' }))
  }
  const saida = redirecionar(requisicao, destinoSeguro(returnTo))
  saida.cookies.set(COOKIE_DA_SESSAO, id, opcoesDoCookie(SEGUNDOS_DA_SESSAO))
  return saida
}

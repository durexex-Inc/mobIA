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
  apagarDesafio,
  COOKIE_DA_SESSAO,
  COOKIE_DO_DESAFIO,
  criarSessao,
  lerDesafio,
  opcoesDoCookie,
  SEGUNDOS_DA_SESSAO,
} from '@/lib/servidor/sessao'

/**
 * O POST do codigo TOTP (TEC-309, D3 e D4).
 *
 * O desafio vem do Redis, pelo cookie `mobia_mfa` -- o navegador so tem o id.
 *
 * **Codigo errado NAO apaga o desafio.** Quem errou um digito tenta de novo
 * sem redigitar a senha, enquanto os cinco minutos do desafio valerem. So o
 * sucesso o apaga.
 *
 * **Nao ha limite de tentativas por desafio**, nem aqui nem no FastAPI. O que
 * limita e a validade de cinco minutos e o limitador por IP da TEC-205 --
 * que, atras deste servidor, conta as tentativas de todo mundo juntas (L2 do
 * desenho). Contar tentativas por desafio e trabalho do backend, na lacuna L3
 * da TEC-201.
 */
export async function POST(requisicao: NextRequest) {
  // Corpo que nao e formulario vale como formulario vazio, e nao como 500.
  const dados = await requisicao.formData().catch(() => new FormData())
  const returnTo = campo(dados, 'returnTo')

  if (!veioDoPainel(requisicao)) {
    return redirecionar(requisicao, urlDoLogin({ returnTo }))
  }

  const idDoDesafio = requisicao.cookies.get(COOKIE_DO_DESAFIO)?.value
  let desafio: string | null
  try {
    desafio = await lerDesafio(idDoDesafio)
  } catch {
    return redirecionar(
      requisicao,
      urlDoLogin({ returnTo, etapa: 'mfa', erro: 'indisponivel' }),
    )
  }
  if (!desafio) {
    // Expirou, ou nunca houve: a etapa do codigo nao tem o que confirmar, e o
    // caminho e voltar a senha.
    return redirecionar(requisicao, urlDoLogin({ returnTo, erro: 'expirado' }))
  }

  let resposta: Response
  try {
    resposta = await chamarApi('/api/v1/auth/mfa', {
      metodo: 'POST',
      corpo: JSON.stringify({ desafio, codigo: campo(dados, 'codigo').trim() }),
      tipoDoCorpo: 'application/json',
    })
  } catch {
    return redirecionar(
      requisicao,
      urlDoLogin({ returnTo, etapa: 'mfa', erro: 'indisponivel' }),
    )
  }

  const tokens = resposta.ok ? tokensDe(await resposta.json().catch(() => null)) : null
  if (!tokens) {
    // `401` aqui cobre codigo errado E desafio que expirou no FastAPI -- ele
    // nao distingue os dois, de proposito. A tela diz as duas coisas.
    const erro = resposta.ok ? 'indisponivel' : motivoDoStatus(resposta.status, 'codigo')
    return redirecionar(requisicao, urlDoLogin({ returnTo, etapa: 'mfa', erro }))
  }

  const id = await criarSessao(tokens).catch(() => null)
  if (!id) {
    return redirecionar(
      requisicao,
      urlDoLogin({ returnTo, etapa: 'mfa', erro: 'indisponivel' }),
    )
  }
  // O desafio NAO e de uso unico no FastAPI: ele vale ate expirar, e com outro
  // codigo daria outro par de tokens. Apaga-lo daqui tira do painel o caminho
  // de reapresenta-lo. Se o apagar falhar, ele fica no Redis por no maximo
  // cinco minutos e ainda exige um codigo TOTP valido -- nao compensa derrubar
  // por isso o login que acabou de dar certo.
  await apagarDesafio(idDoDesafio).catch(() => undefined)
  const saida = redirecionar(requisicao, destinoSeguro(returnTo))
  saida.cookies.set(COOKIE_DA_SESSAO, id, opcoesDoCookie(SEGUNDOS_DA_SESSAO))
  saida.cookies.set(COOKIE_DO_DESAFIO, '', opcoesDoCookie(0, '/login'))
  return saida
}

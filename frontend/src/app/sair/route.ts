import { type NextRequest } from 'next/server'

import { chamarApi } from '@/lib/servidor/api'
import { redirecionar, veioDoPainel } from '@/lib/servidor/login'
import {
  apagarSessao,
  COOKIE_DA_SESSAO,
  lerSessao,
  opcoesDoCookie,
} from '@/lib/servidor/sessao'

/**
 * "Sair" (TEC-310, D6 e D7).
 *
 * Revoga o refresh no FastAPI, apaga a sessao do Redis e o cookie, e manda ao
 * login com `Clear-Site-Data: "cache"`. POST, e nunca GET: um logout por GET
 * seria disparavel por qualquer `<img>` de outra origem.
 *
 * **Sair nao depende do FastAPI responder.** Se ele estiver fora, a familia de
 * refresh fica viva no banco ate expirar -- mas o unico lugar que tinha aquele
 * refresh era o registro do Redis, que e apagado aqui de qualquer jeito.
 * "Redireciona ao logout do OIDC", da card, nao se aplica: nao ha provedor
 * OIDC (Emenda E-01 a RNF-11).
 */
export async function POST(requisicao: NextRequest) {
  if (!veioDoPainel(requisicao)) {
    // Logout forjado por outra origem e pouco perigoso, mas nao ha razao para
    // aceita-lo -- e a mesma regra do login.
    return redirecionar(requisicao, '/')
  }

  const id = requisicao.cookies.get(COOKIE_DA_SESSAO)?.value
  const sessao = await lerSessao(id).catch(() => null)

  if (sessao) {
    try {
      await chamarApi('/api/v1/auth/logout', {
        metodo: 'POST',
        corpo: JSON.stringify({ refresh: sessao.refresh }),
        tipoDoCorpo: 'application/json',
      })
    } catch {
      // Ver a docstring: segue sem o FastAPI.
    }
  }
  await apagarSessao(id).catch(() => undefined)

  const saida = redirecionar(requisicao, '/login')
  saida.cookies.set(COOKIE_DA_SESSAO, '', opcoesDoCookie(0))
  // O cenario 3 do Gherkin: o "voltar" do navegador nao pode reexibir o
  // painel. A pagina ja sai com `no-store`, entao o cache HTTP nao a guarda;
  // isto limpa o que sobrar do cache da origem -- inclusive, nos navegadores
  // que o implementam, o back/forward cache. Ver a D7 do desenho.
  saida.headers.set('Clear-Site-Data', '"cache"')
  return saida
}

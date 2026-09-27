import { type NextRequest, NextResponse } from 'next/server'

import { veioDoPainel } from '@/lib/servidor/login'
import { COOKIE_DA_SESSAO, obterSessaoValida } from '@/lib/servidor/sessao'

/**
 * O batimento de atividade (TEC-311, D3).
 *
 * O aviso de inatividade chama isto, no maximo uma vez por minuto, enquanto a
 * pessoa interage com a tela sem navegar. Ler a sessao ja marca atividade --
 * e o que `obterSessaoValida` faz --, entao esta rota nao tem logica propria:
 * existe para a interacao que o servidor nao ve chegar ate ele.
 *
 * `204` com sessao; `401` sem ela, e o aviso trata como sessao encerrada.
 * Nunca redireciona: quem chama e um `fetch`.
 */
export async function POST(requisicao: NextRequest) {
  if (!veioDoPainel(requisicao)) {
    return NextResponse.json({ erro: 'origem_nao_permitida' }, { status: 403 })
  }
  let sessao: Awaited<ReturnType<typeof obterSessaoValida>>
  try {
    sessao = await obterSessaoValida(requisicao.cookies.get(COOKIE_DA_SESSAO)?.value)
  } catch {
    return NextResponse.json({ erro: 'sessao_indisponivel' }, { status: 503 })
  }
  if (!sessao) {
    return NextResponse.json({ erro: 'sem_sessao' }, { status: 401 })
  }
  return new NextResponse(null, { status: 204 })
}

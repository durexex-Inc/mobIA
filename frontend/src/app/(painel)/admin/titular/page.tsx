import type { Metadata } from 'next'
import { redirect } from 'next/navigation'

import { ErroDeCarga } from '@/components/estado/ErroDeCarga'
import { Vazio } from '@/components/estado/Vazio'
import { FilaDoTitular } from '@/components/FilaDoTitular'
import { SemPermissao } from '@/components/SemPermissao'
import { urlDoLogin } from '@/lib/destino'
import { paginaInicialDe } from '@/lib/navegacao'
import { exigirPermissao } from '@/lib/servidor/quemSou'
import { apagarSessaoDaRequisicao } from '@/lib/servidor/sessao'
import { buscarFilaDoTitular, ErroDaFilaDoTitular } from '@/lib/servidor/titular'
import type { PedidoDoTitular } from '@/lib/titular'

export const metadata: Metadata = {
  title: 'Pedidos do titular — mobIA',
}

const ENDERECO = '/admin/titular'

/**
 * A fila de pedidos do titular (TEC-340, RF-FE-15): os pedidos ABERTOS de
 * acesso e de eliminacao, com o prazo legal de 15 dias contando (D2 e D3 do
 * desenho).
 *
 * **A guarda e `ATENDER_TITULAR`**, a permissao que a rota do FastAPI exige, e
 * nao o papel (D1): "somente ADMIN" e verdade porque a matriz so da essa
 * permissao a ele. Vem antes de qualquer busca, como em toda pagina do painel
 * (D3 da TEC-312).
 *
 * **Exportar e eliminar sao as cards seguintes** (TEC-341 e TEC-342): esta
 * pagina so mostra o que esta pendente, e o link para o lead leva a quem age.
 */
export default async function PaginaDaFilaDoTitular() {
  const { sessao, quem, permitido } = await exigirPermissao(ENDERECO, (p) => p.has('ATENDER_TITULAR'))
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  let pedidos: PedidoDoTitular[] | null = null
  let erro: ErroDaFilaDoTitular | null = null
  try {
    pedidos = await buscarFilaDoTitular(sessao.acesso)
  } catch (falha) {
    // Backend fora do ar faz o `fetch` LANCAR: sem resposta nao ha status nem
    // codigo para o suporte, como na lista de leads.
    erro = falha instanceof ErroDaFilaDoTitular ? falha : new ErroDaFilaDoTitular(0, 'sem resposta', null)
  }

  // Fora do `try`: `redirect` lanca para interromper o render, e o `catch` o
  // engoliria.
  if (erro?.status === 401) {
    await apagarSessaoDaRequisicao()
    redirect(urlDoLogin({ returnTo: ENDERECO, erro: 'sessao_expirada' }))
  }

  // A recusa do backend vence a permissao que o painel leu (TEC-312, D4).
  if (erro?.status === 403) {
    return <SemPermissao papel={quem.papel} paginaInicial={null} />
  }

  return (
    <main className="painel">
      <h1>Pedidos do titular</h1>
      <p>Pedidos de acesso e de eliminação em aberto. O prazo legal de resposta é de 15 dias.</p>
      {erro ? (
        <ErroDeCarga
          mensagem="Não foi possível carregar a fila de pedidos."
          requestId={erro.requestId}
          urlParaTentarDeNovo={ENDERECO}
        />
      ) : null}
      {pedidos && pedidos.length === 0 ? (
        <p>
          <Vazio texto="Nenhum pedido em aberto." />
        </p>
      ) : null}
      {pedidos && pedidos.length > 0 ? (
        <FilaDoTitular
          pedidos={pedidos}
          agora={new Date()}
          abreLead={quem.permissoes.has('VER_DETALHE_DO_LEAD')}
        />
      ) : null}
    </main>
  )
}

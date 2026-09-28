import {
  dataLegivel,
  destacado,
  diasRestantes,
  origemLegivel,
  type PedidoDoTitular,
  textoDoPrazo,
  tipoLegivel,
} from '@/lib/titular'
import { EliminarDadosDoTitular } from '@/components/EliminarDadosDoTitular'

/**
 * A tabela da fila de pedidos do titular (TEC-340, D3 e D4). Server
 * Component sem estado: recebe `agora`, para o teste fixar o dia.
 *
 * **O destaque esta no texto, e nao so na cor nem no icone.** Com 3 dias ou
 * menos a linha ganha a classe de destaque, o marcador decorativo e "Prazo
 * curto" -- "Prazo vencido" quando passou --, que e o que um leitor de tela
 * anuncia.
 *
 * **A coluna "Acao" decide por tipo** (TEC-341 D1, TEC-342 D4): `ACESSO`
 * mostra "Baixar dados do titular" (a coluna independe de `abreLead` --
 * baixar nao pede `VER_DETALHE_DO_LEAD`, so a permissao que ja guarda a
 * pagina inteira); `ELIMINACAO` com `leadId` mostra o botao de eliminar; sem
 * `leadId` (o apelido sumiu por fora, lacuna da TEC-340) ou qualquer outro
 * tipo, `'-'` -- nao ha como montar a chamada sem o `leadId`.
 */
/** A celula de "Acao": baixar (ACESSO), eliminar (ELIMINACAO com leadId) ou '-' (D4). */
function acaoDoPedido(pedido: PedidoDoTitular) {
  if (pedido.tipo === 'ACESSO') {
    return <a href={`/admin/titular/${pedido.id}/baixar`}>Baixar dados do titular</a>
  }
  if (pedido.tipo === 'ELIMINACAO' && pedido.leadId) {
    return <EliminarDadosDoTitular leadId={pedido.leadId} />
  }
  return '—'
}

export function FilaDoTitular({
  pedidos,
  agora,
  abreLead,
}: {
  pedidos: PedidoDoTitular[]
  agora: Date
  abreLead: boolean
}) {
  return (
    <table className="fila-do-titular">
      <thead>
        <tr>
          <th scope="col">Pedido</th>
          <th scope="col">Origem</th>
          <th scope="col">Aberto em</th>
          <th scope="col">Prazo</th>
          {abreLead ? <th scope="col">Lead</th> : null}
          <th scope="col">Ação</th>
        </tr>
      </thead>
      <tbody>
        {pedidos.map((pedido) => {
          const restante = diasRestantes(pedido.prazoEm, agora)
          const comDestaque = destacado(restante)
          return (
            <tr key={pedido.id} className={comDestaque ? 'fila-do-titular__urgente' : undefined}>
              <td>{tipoLegivel(pedido.tipo)}</td>
              <td>{origemLegivel(pedido.origem)}</td>
              <td>{dataLegivel(pedido.recebidaEm)}</td>
              <td>
                {textoDoPrazo(restante)}
                {comDestaque ? (
                  <span className="fila-do-titular__aviso">
                    {' '}
                    <span aria-hidden="true">⚠</span> {restante < 0 ? 'Prazo vencido' : 'Prazo curto'}
                  </span>
                ) : null}
              </td>
              {abreLead ? (
                <td>{pedido.leadId ? <a href={`/leads/${pedido.leadId}`}>Ver lead</a> : '—'}</td>
              ) : null}
              <td>{acaoDoPedido(pedido)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

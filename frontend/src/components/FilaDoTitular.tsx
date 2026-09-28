import {
  dataLegivel,
  destacado,
  diasRestantes,
  origemLegivel,
  type PedidoDoTitular,
  textoDoPrazo,
  tipoLegivel,
} from '@/lib/titular'

/**
 * A tabela da fila de pedidos do titular (TEC-340, D3 e D4). Server
 * Component sem estado: recebe `agora`, para o teste fixar o dia.
 *
 * **O destaque esta no texto, e nao so na cor nem no icone.** Com 3 dias ou
 * menos a linha ganha a classe de destaque, o marcador decorativo e "Prazo
 * curto" -- "Prazo vencido" quando passou --, que e o que um leitor de tela
 * anuncia.
 *
 * **"Baixar dados do titular" so nas linhas ACESSO** (TEC-341, D1):
 * portabilidade e a exportacao do pedido de acesso, e a coluna independe de
 * `abreLead` -- baixar nao pede `VER_DETALHE_DO_LEAD`, so a permissao que ja
 * guarda a pagina inteira.
 */
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
          <th scope="col">Portabilidade</th>
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
              <td>
                {pedido.tipo === 'ACESSO' ? (
                  <a href={`/admin/titular/${pedido.id}/baixar`}>Baixar dados do titular</a>
                ) : (
                  '—'
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

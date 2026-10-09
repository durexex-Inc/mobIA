import { AcoesDoPedido } from '@/components/AcoesDoPedido'
import { DadoRevelavel } from '@/components/DadoRevelavel'
import { Cartao } from '@/components/ui/Cartao'
import { NAO_INFORMADO } from '@/lib/detalhe'
import { type PedidoDeInteresse, podeRevelarPedido, rotuloDoAtendimento } from '@/lib/interesses'
import { dataAbsoluta } from '@/lib/leads'
import type { QuemSou } from '@/lib/servidor/quemSou'

/**
 * A tabela dos pedidos de interesse (TEC-404, D9 do desenho). Server
 * Component; as acoes da linha sao o unico pedaco de cliente.
 *
 * **A ordem e a da resposta** (`criado_em` decrescente, D8): a tabela nao
 * reordena, pela mesma razao de `TabelaDeLeads`.
 *
 * **A revelacao vai a rota do pedido**, e nao a do lead (D5): o e-mail e por
 * pedido, e o corretor revela so o que e dele. `podeRevelarPedido` decide so
 * se o botao aparece; quem recusa o resto e o backend.
 *
 * **A linha sem corretor leva `pedido--sem-corretor`** (D9): ninguem foi
 * avisado, e e a linha que o admin precisa ver primeiro. O rotulo da situacao
 * diz o mesmo em texto, para quem nao ve a cor.
 *
 * Reusa as classes de `leads-tabela`, com `data-rotulo` em cada celula: o
 * mesmo CSS vira cartoes no celular.
 */
export function TabelaDePedidos({
  itens,
  quem,
  corretores,
}: {
  itens: PedidoDeInteresse[]
  quem: QuemSou
  corretores: ReadonlyArray<{ id: string; nome: string }>
}) {
  const podeAtribuir = quem.permissoes.has('GERIR_CORRETORES')
  const abreNoAdmin = quem.permissoes.has('GERIR_CATALOGO')

  return (
    <Cartao className="leads-tabela-cartao">
      <table className="leads-tabela">
        <thead>
          <tr>
            <th scope="col">Pedido em</th>
            <th scope="col">Imóvel</th>
            <th scope="col">Nome</th>
            <th scope="col">Telefone</th>
            <th scope="col">E-mail</th>
            <th scope="col">Situação</th>
            <th scope="col">Ações</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((pedido) => {
            const podeRevelar = podeRevelarPedido(pedido.atendimento, quem)
            const urlDeRevelar = `/bff/api/v1/interesses/${encodeURIComponent(pedido.id)}/revelar`
            const corretor = pedido.atendimento?.semCorretor ? null : pedido.atendimento?.corretor
            return (
              <tr
                key={pedido.id}
                data-testid="pedido"
                className={pedido.atendimento?.semCorretor ? 'pedido--sem-corretor' : undefined}
              >
                <td data-rotulo="Pedido em">
                  <time dateTime={pedido.criadoEm}>{dataAbsoluta(pedido.criadoEm)}</time>
                </td>
                <td data-rotulo="Imóvel">
                  <a href={`/busca/${encodeURIComponent(pedido.imovel.id)}`}>
                    {pedido.imovel.codigo} — {pedido.imovel.titulo}
                  </a>
                  {abreNoAdmin && (
                    <>
                      {' · '}
                      <a href={`/admin/imoveis/${encodeURIComponent(pedido.imovel.id)}`}>Editar imóvel</a>
                    </>
                  )}
                </td>
                <td data-rotulo="Nome">{pedido.nome ?? NAO_INFORMADO}</td>
                <td data-rotulo="Telefone">
                  <DadoRevelavel
                    leadId={pedido.leadId}
                    campo="telefone"
                    mascarado={pedido.telefoneMascarado}
                    podeRevelar={podeRevelar}
                    url={urlDeRevelar}
                  />
                </td>
                <td data-rotulo="E-mail">
                  <DadoRevelavel
                    leadId={pedido.leadId}
                    campo="email"
                    mascarado={pedido.emailMascarado}
                    podeRevelar={podeRevelar}
                    url={urlDeRevelar}
                  />
                </td>
                <td data-rotulo="Situação" className="leads-celula-destaque">
                  <span className="pedido__situacao">{rotuloDoAtendimento(pedido.atendimento)}</span>
                  {corretor && <> · {corretor.nome}</>}
                </td>
                <td data-rotulo="Ações">
                  {pedido.atendimento && (
                    <AcoesDoPedido
                      atendimento={pedido.atendimento}
                      corretorId={quem.corretorId}
                      podeAtribuir={podeAtribuir}
                      corretores={corretores}
                    />
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Cartao>
  )
}

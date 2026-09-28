import {
  acaoLegivel,
  atorLegivel,
  dataHoraLegivel,
  detalhesLegiveis,
  entidadeLegivel,
  type EventoDaTrilha,
} from '@/lib/auditoria'

/**
 * A trilha (D5 e D6 do desenho). Server Component sem estado.
 *
 * **Nenhuma linha tem acao nenhuma** -- nem escondida atras de permissao: a
 * permissao para editar ou excluir um evento nao existe na matriz. E o
 * cenario 2 da card ("nao ha opcao de editar nem de excluir") garantido por
 * nao existir o botao, nao por ele estar desabilitado.
 */
export function TabelaDeAuditoria({ itens }: { itens: EventoDaTrilha[] }) {
  return (
    <table className="auditoria-trilha">
      <thead>
        <tr>
          <th scope="col">Quando</th>
          <th scope="col">Quem</th>
          <th scope="col">Tipo</th>
          <th scope="col">Entidade</th>
          <th scope="col">Campo</th>
          <th scope="col">Detalhes</th>
        </tr>
      </thead>
      <tbody>
        {itens.map((evento) => (
          <tr key={evento.id}>
            <td>{dataHoraLegivel(evento.criadoEm)}</td>
            <td>{atorLegivel(evento)}</td>
            <td>{acaoLegivel(evento.acao)}</td>
            <td>
              {entidadeLegivel(evento.entidade)}
              {evento.entidadeId ? ` (${evento.entidadeId})` : ''}
            </td>
            <td>{evento.campo ?? '—'}</td>
            <td>{detalhesLegiveis(evento.detalhes) || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

import { Selo } from '@/components/ui/Selo'
import {
  acaoLegivel,
  ATORES,
  categoriaDaAcao,
  dataHoraLegivel,
  detalhesLegiveis,
  entidadeLegivel,
  type EventoDaTrilha,
} from '@/lib/auditoria'

const VARIANTE_DA_CATEGORIA = { risco: 'perigo', alteracao: 'info', neutra: 'neutro' } as const

/**
 * A trilha (D5 e D6 do desenho da TEC-343). Server Component sem estado.
 *
 * **Nenhuma linha tem acao nenhuma** -- nem escondida atras de permissao: a
 * permissao para editar ou excluir um evento nao existe na matriz. E o
 * cenario 2 da card ("nao ha opcao de editar nem de excluir") garantido por
 * nao existir o botao, nao por ele estar desabilitado.
 *
 * O tipo de evento e um selo com cor por categoria (D3 da TEC-399), e o ator
 * mostra a inicial do tipo e o identificador numa segunda linha (D4).
 */
export function TabelaDeAuditoria({ itens }: { itens: EventoDaTrilha[] }) {
  return (
    <div className="auditoria-rolagem">
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
          {itens.map((evento) => {
            const tipoDoAtor = ATORES[evento.atorTipo] ?? evento.atorTipo
            return (
              <tr key={evento.id}>
                <td className="auditoria-trilha__quando">{dataHoraLegivel(evento.criadoEm)}</td>
                <td>
                  <span className="auditoria-ator">
                    <span className="auditoria-ator__inicial" aria-hidden="true">
                      {tipoDoAtor.charAt(0)}
                    </span>
                    <span className="auditoria-ator__texto">
                      <span>{tipoDoAtor}</span>
                      {evento.atorId && (
                        <span className="auditoria-ator__id" title={evento.atorId}>
                          {evento.atorId}
                        </span>
                      )}
                    </span>
                  </span>
                </td>
                <td>
                  <Selo variante={VARIANTE_DA_CATEGORIA[categoriaDaAcao(evento.acao)]}>
                    {acaoLegivel(evento.acao)}
                  </Selo>
                </td>
                <td className="auditoria-trilha__mono">
                  {entidadeLegivel(evento.entidade)}
                  {evento.entidadeId ? ` (${evento.entidadeId})` : ''}
                </td>
                <td className="auditoria-trilha__mono">{evento.campo ?? '—'}</td>
                <td className="auditoria-trilha__detalhes">{detalhesLegiveis(evento.detalhes) || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

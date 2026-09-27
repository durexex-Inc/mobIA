import {
  canalLegivel,
  dataAbsoluta,
  identificacaoDoLead,
  type LeadDaLista,
  type Ordem,
  statusLegivel,
  temperaturaLegivel,
  tempoRelativo,
  urlDaLista,
} from '@/lib/leads'

/**
 * A tabela da lista de leads (TEC-321). Server Component sem estado.
 *
 * **A ordem da tabela e a ordem da resposta**: a tabela nao reordena nada. A
 * ordem e do backend (D4 do desenho), e reordenar aqui mostraria a pagina
 * recebida numa ordem que nao e a da base.
 *
 * Os cabecalhos ordenaveis sao LINKS, e nao botoes: trocar a ordem e trocar
 * de endereco, e isso funciona sem JS.
 */
export function TabelaDeLeads({
  itens,
  ordem,
  busca,
  agora,
}: {
  itens: LeadDaLista[]
  ordem: Ordem
  busca?: string
  agora: Date
}) {
  return (
    <table className="leads-tabela">
      <thead>
        <tr>
          <th scope="col">Lead</th>
          <th scope="col">Temperatura</th>
          <CabecalhoOrdenavel rotulo="Score" esta={ordem} ordem="score_desc" busca={busca} />
          <th scope="col">Status</th>
          <th scope="col">Canal</th>
          <CabecalhoOrdenavel
            rotulo="Última interação"
            esta={ordem}
            ordem="ultima_interacao_desc"
            busca={busca}
          />
        </tr>
      </thead>
      <tbody>
        {itens.map((lead) => (
          <tr key={lead.leadId} data-testid="lead">
            <td>{identificacaoDoLead(lead)}</td>
            <td>{temperaturaLegivel(lead.temperatura)}</td>
            {/* Sem score e travessao, e nao zero: "ainda nao pontuado" nao e
                "pontuou zero" (D4 da TEC-192). */}
            <td className="leads-score">{lead.score ?? '—'}</td>
            <td>{statusLegivel(lead.status)}</td>
            <td>{canalLegivel(lead.channel)}</td>
            <td>
              <time dateTime={lead.ultimaInteracaoEm} title={dataAbsoluta(lead.ultimaInteracaoEm)}>
                {tempoRelativo(lead.ultimaInteracaoEm, agora)}
              </time>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function CabecalhoOrdenavel({
  rotulo,
  esta,
  ordem,
  busca,
}: {
  rotulo: string
  esta: Ordem
  ordem: Ordem
  busca?: string
}) {
  const ativa = esta === ordem
  return (
    <th scope="col" aria-sort={ativa ? 'descending' : undefined}>
      <a href={urlDaLista({ busca, ordem })} aria-current={ativa ? 'true' : undefined}>
        {rotulo}
        {ativa ? ' ↓' : ''}
      </a>
    </th>
  )
}

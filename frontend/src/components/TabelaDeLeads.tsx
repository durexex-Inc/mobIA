import { DadoRevelavel } from '@/components/DadoRevelavel'
import {
  canalLegivel,
  dataAbsoluta,
  type FiltrosDaLista,
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
 *
 * **A primeira celula abre o detalhe, com `<a>` e nao `next/link`** (TEC-323,
 * D2): abrir o detalhe grava um acesso na trilha. O prefetch padrao do
 * `<Link>` para no `loading.tsx` do detalhe e nao chega a gravar, mas passaria
 * a gravar um acesso por linha visivel com `prefetch={true}` ou sem aquele
 * arquivo; o `<a>` nao depende de nenhum dos dois. So para quem tem
 * `VER_DETALHE_DO_LEAD` -- para LEITURA o link terminaria sempre em "Sem
 * permissao".
 *
 * **A mesma celula revela o telefone** para quem tem `VER_DADOS_COMPLETOS`
 * (TEC-330, D4), com o botao FORA do link: botao dentro de `<a>` e HTML
 * invalido, e o clique abriria o detalhe em vez de revelar.
 *
 * **A mesma marcacao vira cartoes abaixo de 768 px** (TEC-322, D4), pelo CSS:
 * cada celula leva o rotulo da coluna em `data-rotulo`. Uma segunda marcacao
 * duplicaria o "Revelar" e o estado dele. Com o "carregar mais", as
 * `quantasAnteriores` primeiras linhas sao das paginas anteriores, e o CSS as
 * esconde a partir de 1024 px, onde a navegacao e numerada (D3).
 */
export function TabelaDeLeads({
  itens,
  ordem,
  busca,
  agora,
  abreDetalhe,
  podeRevelar,
  filtros,
  quantasAnteriores = 0,
}: {
  itens: LeadDaLista[]
  ordem: Ordem
  busca?: string
  agora: Date
  abreDetalhe: boolean
  podeRevelar: boolean
  filtros?: FiltrosDaLista
  quantasAnteriores?: number
}) {
  return (
    <table className="leads-tabela">
      <thead>
        <tr>
          <th scope="col">Lead</th>
          <th scope="col">Temperatura</th>
          <CabecalhoOrdenavel rotulo="Score" esta={ordem} ordem="score_desc" busca={busca} filtros={filtros} />
          <th scope="col">Status</th>
          <th scope="col">Canal</th>
          <CabecalhoOrdenavel
            rotulo="Última interação"
            esta={ordem}
            ordem="ultima_interacao_desc"
            busca={busca}
            filtros={filtros}
          />
        </tr>
      </thead>
      <tbody>
        {itens.map((lead, i) => (
          <tr
            key={lead.leadId}
            data-testid="lead"
            className={i < quantasAnteriores ? 'leads-pagina-anterior' : undefined}
          >
            <td data-rotulo="Lead" className="leads-celula-lead">
              {/* Sem telefone, o texto e o "Visitante do site" ou o
                  "Telefone indisponível" de `identificacaoDoLead`, e sem
                  mascara nao ha o que revelar. */}
              <DadoRevelavel
                leadId={lead.leadId}
                campo="telefone"
                mascarado={lead.telefone}
                vazio={identificacaoDoLead(lead)}
                podeRevelar={podeRevelar}
                href={abreDetalhe ? `/leads/${encodeURIComponent(lead.leadId)}` : undefined}
              />
            </td>
            <td data-rotulo="Temperatura" className="leads-celula-destaque">
              {temperaturaLegivel(lead.temperatura)}
            </td>
            {/* Sem score e travessao, e nao zero: "ainda nao pontuado" nao e
                "pontuou zero" (D4 da TEC-192). */}
            <td data-rotulo="Score" className="leads-score leads-celula-destaque">
              {lead.score ?? '—'}
            </td>
            <td data-rotulo="Status">{statusLegivel(lead.status)}</td>
            <td data-rotulo="Canal">{canalLegivel(lead.channel)}</td>
            <td data-rotulo="Última interação">
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
  filtros,
}: {
  rotulo: string
  esta: Ordem
  ordem: Ordem
  busca?: string
  filtros?: FiltrosDaLista
}) {
  const ativa = esta === ordem
  return (
    <th scope="col" aria-sort={ativa ? 'descending' : undefined}>
      {/* Trocar a ordem mantem busca e filtros, e volta a primeira pagina: o
          cursor e da ordem anterior (D1 da TEC-322). */}
      <a href={urlDaLista({ busca, ordem, filtros })} aria-current={ativa ? 'true' : undefined}>
        {rotulo}
        {ativa ? ' ↓' : ''}
      </a>
    </th>
  )
}

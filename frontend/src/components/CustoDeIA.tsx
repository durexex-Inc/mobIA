import { Vazio } from '@/components/estado/Vazio'
import type { CustoDeIA as CustoDeIATipo, TokensPorModelo } from '@/lib/custo'
import { estadoDe } from '@/lib/estados'
import { moedaMedia, moedaTotal, percentual } from '@/lib/formato'

const INTEIRO = new Intl.NumberFormat('pt-BR')

/**
 * Uma média que pode ser nula (D2 do desenho): nulo é "sem dados no
 * período" (`Vazio`), nunca "Ainda não medido" -- este painel não tem
 * indicador sem fonte, `disponivel` é sempre `true`.
 */
function Media({ valor }: { valor: number | null }) {
  if (estadoDe({ valor, disponivel: true }) === 'vazio') {
    return <Vazio />
  }
  return <>{moedaMedia(valor as number)}</>
}

/**
 * O alerta de orçamento (D3 do desenho), no molde de
 * `Funil.tsx::AvisoDeCoorteIncompleta`: ícone + texto curto sempre visível,
 * e não um tooltip que dependeria do mouse. `orcamento.alerta` já vem
 * calculado do backend (>= 80%, `custo.py`).
 */
function AvisoDeOrcamento({ orcamento }: { orcamento: NonNullable<CustoDeIATipo['orcamento']> }) {
  if (!orcamento.alerta) {
    return null
  }
  return (
    <p role="alert" className="custo-ia-alerta">
      <span aria-hidden="true">⚠</span> Orçamento em {percentual(orcamento.consumidoPct / 100)} do
      período ({moedaTotal(orcamento.consumidoUsd)} de {moedaTotal(orcamento.doPeriodoUsd)})
    </p>
  )
}

function TabelaDeTokens({ tokens }: { tokens: Record<string, TokensPorModelo> }) {
  const modelos = Object.entries(tokens)
  if (modelos.length === 0) {
    return null
  }
  return (
    <table className="custo-ia-tokens">
      <caption>Tokens por modelo</caption>
      <thead>
        <tr>
          <th scope="col">Modelo</th>
          <th scope="col">Entrada</th>
          <th scope="col">Saída</th>
          <th scope="col">Cache (leitura)</th>
          <th scope="col">Cache (escrita)</th>
        </tr>
      </thead>
      <tbody>
        {modelos.map(([modelo, t]) => (
          <tr key={modelo}>
            <th scope="row">{modelo}</th>
            <td>{INTEIRO.format(t.entrada)}</td>
            <td>{INTEIRO.format(t.saida)}</td>
            <td>{INTEIRO.format(t.cacheLeitura)}</td>
            <td>{INTEIRO.format(t.cacheEscrita)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * O painel de custo de IA (TEC-319, RF-FE-06). Server component sem estado --
 * quem busca é a `Pagina`, como o funil.
 */
export function CustoDeIA({ custo }: { custo: CustoDeIATipo }) {
  return (
    <section aria-label="Custo de IA" className="custo-ia">
      <dl className="custo-ia-lista">
        <div className="custo-ia-item" data-testid="custo-total">
          <dt>Custo total</dt>
          <dd>{moedaTotal(custo.custoTotalUsd)}</dd>
        </div>
        <div className="custo-ia-item" data-testid="custo-por-conversa">
          <dt>Custo por conversa</dt>
          <dd>
            <Media valor={custo.custoPorConversaUsd} />
          </dd>
        </div>
        <div className="custo-ia-item" data-testid="custo-por-lead">
          <dt>Custo por lead qualificado</dt>
          <dd>
            <Media valor={custo.custoPorLeadQualificadoUsd} />
            {/* O alvo da RNF-06 fica ao lado do custo por LEAD qualificado --
                é o campo que o backend expõe (`alvoPorLeadQualificadoUsd`),
                não "por conversa qualificada" como a prosa da card escreve
                (D4 do desenho). */}
            {custo.acimaDoAlvo !== null && (
              <span
                className={
                  custo.acimaDoAlvo ? 'custo-ia-acima-do-alvo' : 'custo-ia-dentro-do-alvo'
                }
              >
                {' '}
                {custo.acimaDoAlvo ? 'acima do alvo' : 'dentro do alvo'} (alvo:{' '}
                {moedaMedia(custo.alvoPorLeadQualificadoUsd)})
              </span>
            )}
          </dd>
        </div>
        <div className="custo-ia-item" data-testid="conversas">
          <dt>Conversas</dt>
          <dd>{INTEIRO.format(custo.conversas)}</dd>
        </div>
        <div className="custo-ia-item" data-testid="leads-qualificados">
          <dt>Leads qualificados</dt>
          <dd>{INTEIRO.format(custo.leadsQualificados)}</dd>
        </div>
      </dl>

      {custo.mensagensSemPreco > 0 && (
        <p role="note" className="custo-ia-nota">
          {INTEIRO.format(custo.mensagensSemPreco)} mensagem(ns) sem preço cadastrado não entraram
          neste total.
        </p>
      )}

      <TabelaDeTokens tokens={custo.tokensPorModelo} />

      {custo.orcamento ? (
        <AvisoDeOrcamento orcamento={custo.orcamento} />
      ) : (
        <p className="custo-ia-sem-orcamento">
          Nenhum orçamento mensal configurado. <a href="/admin">Configurar orçamento</a>
        </p>
      )}
    </section>
  )
}

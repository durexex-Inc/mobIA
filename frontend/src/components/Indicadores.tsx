import { percentual } from '@/lib/formato'
import type { Indicadores as IndicadoresTipo } from '@/lib/metricas'

const ROTULOS: Record<string, string> = {
  leadsNovos: 'Leads novos',
  conversasAtivas: 'Conversas ativas',
  taxaQualificacao: 'Taxa de qualificação',
  distribuicaoPorTemperatura: 'Distribuição por temperatura',
  tempoMedioPrimeiraRespostaSeg: 'Tempo médio de primeira resposta',
  tempoMedioQualificacaoSeg: 'Tempo médio de qualificação',
  slaHandoffCumpridoPct: 'Handoff aceito no SLA',
  agendamentosCriados: 'Agendamentos criados',
  agendamentosConfirmados: 'Agendamentos confirmados',
  agendamentosRealizados: 'Agendamentos realizados',
  taxaNoShow: 'Taxa de no-show',
}

const COMO_PERCENTUAL = new Set(['taxaQualificacao', 'slaHandoffCumpridoPct', 'taxaNoShow'])
const COMO_DURACAO = new Set(['tempoMedioPrimeiraRespostaSeg', 'tempoMedioQualificacaoSeg'])

const INTEIRO = new Intl.NumberFormat('pt-BR')
const UM_DECIMAL = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })
const SEM_DECIMAL = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })

function duracao(segundos: number): string {
  if (segundos < 60) {
    return `${UM_DECIMAL.format(segundos)} s`
  }
  return `${SEM_DECIMAL.format(segundos / 60)} min`
}

/**
 * O texto de um indicador.
 *
 * **Sao DUAS ausencias diferentes, e o texto as distingue.** `indisponivel`
 * e "nao existe fonte" -- ninguem registra visita, e e defeito do sistema
 * que a RF-12 conserta. Nulo sem ser indisponivel e "nao houve o que medir"
 * -- a coorte do periodo estava vazia, e isso e fato do negocio. Um texto so
 * para as duas mandaria a gerente procurar um problema que nao existe, ou
 * ignorar um que existe.
 */
function valorLegivel(
  chave: string,
  valor: number | Record<string, number> | null,
  indisponivel: boolean,
): string {
  if (indisponivel) {
    return 'sem fonte de dados'
  }
  if (valor === null) {
    return 'sem dados no período'
  }
  if (typeof valor === 'object') {
    return Object.entries(valor)
      .map(([faixa, quantos]) => `${faixa}: ${quantos}`)
      .join('   ')
  }
  if (COMO_PERCENTUAL.has(chave)) {
    return percentual(valor)
  }
  if (COMO_DURACAO.has(chave)) {
    return duracao(valor)
  }
  return INTEIRO.format(valor)
}

/**
 * Os indicadores da RN-17.1.
 *
 * Os quatro de agendamento saem nulos enquanto RF-11 e RF-12 nao existirem,
 * e a nota no rodape diz isso uma vez -- sem ela, quatro cartoes escritos
 * "sem fonte de dados" parecem defeito do painel, e nao ausencia declarada.
 */
export function Indicadores({
  indicadores,
  indisponiveis,
}: {
  indicadores: IndicadoresTipo
  indisponiveis: string[]
}) {
  const semFonte = new Set(indisponiveis)

  return (
    <section aria-label="Indicadores do período" className="indicadores">
      <dl className="indicadores-lista">
        {Object.entries(indicadores).map(([chave, valor]) => (
          <div key={chave} data-testid={`indicador-${chave}`} className="indicador">
            <dt>{ROTULOS[chave] ?? chave}</dt>
            <dd>{valorLegivel(chave, valor, semFonte.has(chave))}</dd>
          </div>
        ))}
      </dl>
      {indisponiveis.length > 0 && (
        <p role="note" className="indicadores-nota">
          Os indicadores de visita ainda não têm fonte: nenhuma visita é registrada no sistema
          hoje. Eles voltam quando o agendamento existir.
        </p>
      )}
    </section>
  )
}

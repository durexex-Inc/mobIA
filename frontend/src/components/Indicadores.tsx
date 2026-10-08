import { AindaNaoMedido } from '@/components/estado/AindaNaoMedido'
import { Vazio } from '@/components/estado/Vazio'
import { Cartao } from '@/components/ui/Cartao'
import { estadoDe } from '@/lib/estados'
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

/**
 * O motivo que acompanha "Ainda nao medido" nos indicadores de visita.
 *
 * Curto de proposito: ele vai no `title` e no texto que o leitor de tela le
 * junto do rotulo, e a versao longa ja existe na nota de rodape da secao. A
 * nota FICA -- ela e o canal que funciona em toque, onde tooltip nao existe.
 * Ver a D4 do desenho.
 */
const MOTIVO_SEM_FONTE = 'nenhuma visita é registrada no sistema hoje'

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
 * O texto de um indicador que TEM dado.
 *
 * **As duas ausencias sairam daqui na TEC-313.** Quem decide entre "Ainda nao
 * medido" (nao existe fonte -- defeito do sistema, RF-12 conserta) e "sem
 * dados no periodo" (a coorte estava vazia -- fato do negocio) e agora
 * `estadoDe`, em `lib/estados.ts`, e quem desenha sao as pecas de
 * `components/estado/`. A distincao continua valendo e continua sendo a razao
 * da card; o que mudou e que ela vale para TODA tela, e nao so para este
 * cartao.
 */
function valorLegivel(chave: string, valor: number | Record<string, number>): string {
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
 * A peca certa para o estado do indicador (TEC-313).
 *
 * Nao formata ausencia: delega. E o que garante que "Ainda nao medido" tenha
 * UMA grafia no projeto inteiro, e que o motivo chegue por tooltip e por
 * leitor de tela sem este arquivo saber como.
 */
function conteudoDe(
  chave: string,
  valor: number | Record<string, number> | null,
  indisponivel: boolean,
) {
  const estado = estadoDe({ valor, disponivel: !indisponivel })

  if (estado === 'sem_fonte') {
    return <AindaNaoMedido motivo={MOTIVO_SEM_FONTE} />
  }
  if (estado === 'vazio') {
    return <Vazio />
  }
  // `valor` nao e nulo aqui: `estadoDe` ja devolveu `vazio` para nulo.
  return valorLegivel(chave, valor!)
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
          <Cartao key={chave} data-testid={`indicador-${chave}`} className="indicador">
            <dt>{ROTULOS[chave] ?? chave}</dt>
            <dd>{conteudoDe(chave, valor, semFonte.has(chave))}</dd>
          </Cartao>
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

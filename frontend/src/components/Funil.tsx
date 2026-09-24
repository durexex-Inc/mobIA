import { percentual, quantidadeLegivel } from '@/lib/formato'
import type { Etapa } from '@/lib/metricas'

/**
 * As seis etapas da RN-17.2, com a conversao entre consecutivas.
 *
 * A largura da barra sai da MAIOR etapa disponivel, e nao da primeira: a
 * primeira pode ser a que nao tem fonte, e dividir por ela daria NaN. O piso
 * de 1 cobre o periodo em que tudo e zero.
 */
export function Funil({ etapas }: { etapas: Etapa[] }) {
  const maior = Math.max(
    1,
    ...etapas.filter((e) => e.disponivel && e.quantidade !== null).map((e) => e.quantidade ?? 0),
  )

  return (
    <ol aria-label="Funil de leads" className="funil">
      {etapas.map((etapa) => (
        <li key={etapa.nome} data-testid={`etapa-${etapa.nome}`} className="funil-etapa">
          <span className="funil-nome">{etapa.nome}</span>
          <span className="funil-quantidade">{quantidadeLegivel(etapa)}</span>
          <span
            className="funil-conversao"
            aria-label={`conversão da etapa anterior para ${etapa.nome}`}
          >
            {percentual(etapa.conversaoDaAnterior)}
          </span>
          <div
            role="presentation"
            data-testid={`barra-${etapa.nome}`}
            className={etapa.disponivel ? 'funil-barra' : 'funil-barra funil-barra-sem-fonte'}
            style={{
              width:
                etapa.disponivel && etapa.quantidade !== null
                  ? `${(etapa.quantidade / maior) * 100}%`
                  : '0%',
            }}
          />
        </li>
      ))}
    </ol>
  )
}

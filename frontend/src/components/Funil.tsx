import { useId } from 'react'

import { coorteIncompleta, percentual, quantidadeLegivel } from '@/lib/formato'
import type { Etapa } from '@/lib/metricas'

/**
 * A conversao independe do que o backend mandou em `conversaoDaAnterior`
 * quando a etapa ou a anterior nao tem fonte (TEC-315, D1) -- defesa em
 * profundidade na fronteira da API: "um numero plausivel e errado" (D10 do
 * desenho da TEC-190) e o que isto impede, mesmo que o calculo do backend
 * um dia volte a produzi-lo.
 */
function conversaoConfiavel(etapa: Etapa, anterior: Etapa | undefined): number | null {
  if (!etapa.disponivel || (anterior && !anterior.disponivel)) {
    return null
  }
  return etapa.conversaoDaAnterior
}

/** O aviso de coorte incompleta (TEC-315, D3): o texto curto sempre visivel
 * (o que o Gherkin pede), a explicacao nos dois canais de `AindaNaoMedido`
 * (TEC-313, D4) -- `title` para o mouse, `aria-describedby` para quem usa
 * leitor de tela. */
function AvisoDeCoorteIncompleta() {
  const id = useId()
  const explicacao =
    'Uma das etapas foi medida por um período mais curto que a anterior — por exemplo, dado retroativo ainda incompleto —, então a conversão pode passar de 100%.'
  return (
    <span className="funil-conversao-aviso" title={explicacao} aria-describedby={id}>
      {' '}
      <span aria-hidden="true">⚠</span> Coorte incompleta
      <span id={id} className="visually-hidden">
        {explicacao}
      </span>
    </span>
  )
}

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
      {etapas.map((etapa, indice) => {
        const conversao = conversaoConfiavel(etapa, etapas[indice - 1])
        return (
          <li key={etapa.nome} data-testid={`etapa-${etapa.nome}`} className="funil-etapa">
            <span className="funil-nome">{etapa.nome}</span>
            <span className="funil-quantidade">{quantidadeLegivel(etapa)}</span>
            <span className="funil-conversao">
              {/* O aviso fica FORA do `aria-label`: um `aria-label` fixa a
                  nome acessivel do elemento e apagaria "Coorte incompleta"
                  para quem usa leitor de tela -- exatamente o cenario que a
                  card pede para anunciar. */}
              <span aria-label={`conversão da etapa anterior para ${etapa.nome}`}>
                {percentual(conversao)}
              </span>
              {coorteIncompleta(conversao) && <AvisoDeCoorteIncompleta />}
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
        )
      })}
    </ol>
  )
}

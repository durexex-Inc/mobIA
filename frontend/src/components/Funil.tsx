import { useId } from 'react'

import { Cartao } from '@/components/ui/Cartao'
import { coorteIncompleta, percentual, quantidadeLegivel } from '@/lib/formato'
import type { Etapa, Filtros } from '@/lib/metricas'

/**
 * A cor de cada etapa, por classe e nunca por `style` (TEC-393, D4): a CSP de
 * producao bloqueia atributo `style` vindo do HTML. Os nomes espelham
 * `EtapaDoFunil` em `domain/metricas/vocabulario.py`; etapa fora da lista fica
 * com o marcador neutro.
 */
const CLASSE_DA_ETAPA: Record<string, string> = {
  Novo: 'funil-marcador--novo',
  'Em conversa': 'funil-marcador--em-conversa',
  Qualificado: 'funil-marcador--qualificado',
  Recomendado: 'funil-marcador--recomendado',
  Agendado: 'funil-marcador--agendado',
  'Handoff aceito': 'funil-marcador--handoff',
}

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
 * A URL da lista de leads desta etapa, preservando os filtros do funil
 * (TEC-318). Os NOMES dos filtros aqui (`de`, `ate`, `canal`, `intencao`,
 * `temperatura`) sao os mesmos que `GET /api/v1/leads` passou a aceitar --
 * nao ha traducao entre os dois lados. `corretorId` viaja junto por estar em
 * `Filtros`, mas hoje nunca e truthy (o campo esta desabilitado desde a
 * TEC-316).
 */
function urlDaEtapa(filtros: Filtros, etapa: string): string {
  const busca = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor) {
      busca.set(chave, valor)
    }
  }
  busca.set('etapa', etapa)
  return `/leads?${busca.toString()}`
}

/**
 * As seis etapas da RN-17.2, com a conversao entre consecutivas.
 *
 * Sem barra de proporcao desde a TEC-393 (D3): a quantidade esta escrita em
 * cada linha, e a largura vinha de um `style` que a CSP de producao bloqueia.
 */
export function Funil({ etapas, filtros }: { etapas: Etapa[]; filtros: Filtros }) {
  return (
    <Cartao className="funil-cartao">
      <ol aria-label="Funil de leads" className="funil">
        {etapas.map((etapa, indice) => {
          const conversao = conversaoConfiavel(etapa, etapas[indice - 1])
          const conteudo = (
            <>
              <span className="funil-nome">
                <span
                  className={`funil-marcador ${CLASSE_DA_ETAPA[etapa.nome] ?? ''}`.trim()}
                  aria-hidden="true"
                />
                {etapa.nome}
              </span>
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
            </>
          )
          return (
            <li key={etapa.nome} data-testid={`etapa-${etapa.nome}`} className="funil-etapa">
              {etapa.disponivel ? (
                // O `<a>` e a propria linha em grid (TEC-393, D5): com o
                // `display: contents` de antes, o anel de foco nao desenhava.
                <a href={urlDaEtapa(filtros, etapa.nome)} className="funil-linha funil-linha--link">
                  {/* Sem `aria-label` no link, pela mesma razao do `span` de
                      conversao acima: apagaria "Coorte incompleta" para quem
                      usa leitor de tela. O contexto entra como texto oculto. */}
                  <span className="visually-hidden">Ver leads da etapa {etapa.nome}. </span>
                  {conteudo}
                </a>
              ) : (
                // Etapa sem fonte nao e navegavel (Gherkin, cenario 2) -- hoje
                // inatingivel em producao, ja que `montar_funil` sempre marca
                // `disponivel: true` desde a TEC-376.
                <div className="funil-linha">{conteudo}</div>
              )}
            </li>
          )
        })}
      </ol>
    </Cartao>
  )
}

import { useId } from 'react'

import { TEXTO_SEM_FONTE } from '@/lib/estados'

/**
 * A ausencia que e defeito do sistema, nao fato do negocio (RN-FE-04.2).
 *
 * **O motivo chega por DOIS canais, e nao so pelo tooltip que a card pede.**
 * `title` nao existe em toque e e irregular em leitor de tela; a RNF-FE-18
 * (citada pela TEC-315) exige que aviso nao dependa de um canal so. Entao:
 * `title` para o mouse, e o mesmo texto ligado por `aria-describedby` a um
 * elemento visualmente oculto, para quem usa leitor.
 *
 * O terceiro canal -- a nota de rodape da secao -- **permanece** onde ja
 * estava: e o que funciona em toque. Ver a D4 do desenho.
 *
 * **Nunca renderiza numero.** E a razao de o componente existir: o primeiro
 * cenario do Gherkin exige que o digito `0` nao apareca no cartao, e a unica
 * garantia forte disso e nao ter caminho por onde um numero entre.
 */
export function AindaNaoMedido({ motivo }: { motivo?: string }) {
  const id = useId()

  return (
    <span className="estado-sem-fonte" title={motivo} aria-describedby={motivo ? id : undefined}>
      {TEXTO_SEM_FONTE}
      {motivo && (
        <span id={id} className="visually-hidden">
          {motivo}
        </span>
      )}
    </span>
  )
}

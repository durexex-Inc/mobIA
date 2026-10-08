import type { ComponentPropsWithoutRef } from 'react'

/**
 * O `<select>` do painel (TEC-394) -- o "Select" do shadcn, so que nativo: o
 * dele escreve `style` inline, que a CSP de producao bloqueia. O invólucro
 * existe para desenhar a seta, porque `<select>` nao tem `::after`.
 */
export function CampoDeSelecao(props: ComponentPropsWithoutRef<'select'>) {
  return (
    <span className="campo-selecao">
      <select {...props} />
    </span>
  )
}

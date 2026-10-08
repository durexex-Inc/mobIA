import type { ComponentPropsWithoutRef } from 'react'

type PropsDoCartao = ComponentPropsWithoutRef<'div'> & {
  /** `section` quando o cartao e uma regiao com nome proprio. */
  como?: 'div' | 'section'
}

/** A superficie com borda e raio do painel (TEC-393) -- o "Card" do shadcn. */
export function Cartao({ como: Elemento = 'div', className, ...resto }: PropsDoCartao) {
  return <Elemento className={className ? `cartao ${className}` : 'cartao'} {...resto} />
}

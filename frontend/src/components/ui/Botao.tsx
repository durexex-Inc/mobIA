import type { ComponentPropsWithoutRef } from 'react'

type PropsDoBotao = ComponentPropsWithoutRef<'button'> & {
  variante?: 'primario' | 'contorno' | 'fantasma'
  tamanho?: 'padrao' | 'pequeno'
}

/** O botao do painel (TEC-393) -- o "Button" do shadcn, so com classes (CSP). */
export function Botao({
  variante = 'primario',
  tamanho = 'padrao',
  className,
  type = 'button',
  ...resto
}: PropsDoBotao) {
  const classes = ['botao', `botao--${variante}`, `botao--${tamanho}`, className]
    .filter(Boolean)
    .join(' ')
  return <button type={type} className={classes} {...resto} />
}

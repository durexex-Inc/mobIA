import type { ReactNode } from 'react'

/** Uma etiqueta curta de estado (TEC-395) -- o "Badge" do shadcn. */
export function Selo({
  variante = 'neutro',
  children,
}: {
  variante?: 'neutro' | 'sucesso' | 'perigo' | 'info'
  children: ReactNode
}) {
  return <span className={`selo selo--${variante}`}>{children}</span>
}

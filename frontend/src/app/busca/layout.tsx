import { Source_Serif_4 } from 'next/font/google'

/**
 * A serifa dos titulos do portal publico (visual do portal). Via `next/font`,
 * que serve a fonte da propria origem -- a CSP so aceita `font-src 'self'`.
 *
 * Mora no layout de `/busca`, e nao na pagina do detalhe, por dois motivos: o
 * painel nao paga o download de uma fonte que nao usa, e `next/font` so roda
 * dentro do Next -- importado pela pagina, derrubaria o teste dela no vitest.
 */
const serifa = Source_Serif_4({ subsets: ['latin'], variable: '--fonte-do-portal' })

export default function LayoutDoPortal({ children }: { children: React.ReactNode }) {
  return <div className={serifa.variable}>{children}</div>
}

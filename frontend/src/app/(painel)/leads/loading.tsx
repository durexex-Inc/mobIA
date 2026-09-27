import { Skeleton } from '@/components/estado/Skeleton'

/**
 * O carregamento da lista de leads (TEC-321).
 *
 * Existe para a lista nao herdar o do grupo `(painel)`, que e o do funil e
 * mostraria "Funil de leads" no titulo enquanto a lista carrega. O atraso de
 * 300 ms continua sendo do CSS (`.skeleton`), como la.
 */
export default function Carregando() {
  return (
    <main className="painel" aria-busy="true" aria-label="Carregando a lista de leads">
      <h1>Leads</h1>
      <Skeleton linhas={8} />
    </main>
  )
}

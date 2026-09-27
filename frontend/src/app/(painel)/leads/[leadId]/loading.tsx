import Link from 'next/link'

import { Skeleton } from '@/components/estado/Skeleton'

/**
 * O carregamento do detalhe (TEC-323). Sem ele, o detalhe herdaria o da
 * lista, com o titulo "Leads". O atraso de 300 ms e do CSS (`.skeleton`).
 *
 * **Ele tambem e o limite do prefetch.** Numa rota dinamica, o `<Link>`
 * padrao pre-carrega so ate o `loading.tsx` mais proximo (referencia de
 * `link`, Next 16); sem este arquivo, a pagina do detalhe -- que grava na
 * trilha -- ficaria mais perto de ser pre-carregada. Ver a D2 do desenho.
 */
export default function Carregando() {
  return (
    <main className="painel" aria-busy="true" aria-label="Carregando o lead">
      <p>
        <Link href="/leads">← Voltar para a lista</Link>
      </p>
      <Skeleton linhas={10} />
    </main>
  )
}

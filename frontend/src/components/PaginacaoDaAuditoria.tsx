import Link from 'next/link'

import { type FiltrosDaTrilha, posicaoDaProxima, type PosicaoNaTrilha, urlDaLista } from '@/lib/auditoria'

/**
 * Só "Carregar mais" (D2 do desenho): uma trilha se lê como um log, de trás
 * para frente, sem pulo para uma página específica.
 */
export function PaginacaoDaAuditoria({
  filtros,
  posicao,
  proximoCursor,
}: {
  filtros: FiltrosDaTrilha
  posicao: PosicaoNaTrilha
  proximoCursor: string | null
}) {
  if (!proximoCursor) {
    return null
  }
  return (
    <p className="auditoria-carregar-mais">
      <Link href={urlDaLista({ filtros, posicao: posicaoDaProxima(posicao, proximoCursor) })} scroll={false}>
        Carregar mais
      </Link>
    </p>
  )
}

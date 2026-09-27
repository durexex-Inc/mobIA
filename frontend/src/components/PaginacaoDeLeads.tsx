import Link from 'next/link'

import {
  type EstadoDaLista,
  numeroDaPagina,
  type PosicaoNaLista,
  posicaoDaPagina,
  posicaoDaProxima,
  urlDaLista,
} from '@/lib/leads'

/**
 * As duas navegacoes da lista (TEC-322, D2 e D3), as duas no HTML, e o CSS
 * escolhe: o servidor nao sabe a largura da tela.
 *
 * - **A partir de 1024 px, paginas numeradas**: as ja visitadas, a atual e
 *   "Proxima". Sem total nao ha "de 7" nem salto para pagina nao visitada --
 *   o cursor so sabe a proxima (Emenda E-01 da TEC-192).
 * - **Abaixo disso, "Carregar mais"**: o link da proxima pagina com
 *   `acumular`, e o servidor desenha todas ate ela. `scroll={false}` para
 *   quem rolou nao voltar ao topo.
 *
 * Links comuns, sem JS: a URL e o estado inteiro, e e compartilhavel.
 */
export function PaginacaoDeLeads({
  estado,
  posicao,
  proximoCursor,
}: {
  estado: Omit<EstadoDaLista, 'posicao'>
  posicao: PosicaoNaLista
  proximoCursor: string | null
}) {
  const atual = numeroDaPagina(posicao)
  if (atual === 1 && !proximoCursor) {
    return null
  }
  const anteriores = Array.from({ length: atual - 1 }, (_, i) => i + 1)

  return (
    <>
      <nav className="leads-paginas" aria-label="Páginas">
        {anteriores.map((numero) => (
          <a key={numero} href={urlDaLista({ ...estado, posicao: posicaoDaPagina(posicao, numero) })}>
            {numero}
          </a>
        ))}
        <span aria-current="page" className="leads-pagina-atual">
          {atual}
        </span>
        {proximoCursor && (
          <a href={urlDaLista({ ...estado, posicao: posicaoDaProxima(posicao, proximoCursor, false) })}>
            Próxima
          </a>
        )}
      </nav>
      {proximoCursor && (
        <p className="leads-carregar-mais">
          <Link
            href={urlDaLista({ ...estado, posicao: posicaoDaProxima(posicao, proximoCursor, true) })}
            scroll={false}
          >
            Carregar mais
          </Link>
        </p>
      )}
    </>
  )
}

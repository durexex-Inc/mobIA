'use client'

import { useRouter } from 'next/navigation'

import { type FiltrosDoPortal, urlDaBusca } from '@/lib/buscaPublica'
import { ORDEM_PADRAO, ORDENS_DA_VITRINE, type OrdemDaVitrine } from '@/lib/vitrine'

/**
 * "Ordenar por" da vitrine (visual do portal, D7). Trocar a ordem navega na
 * hora e volta para a primeira pagina -- a pagina 3 de "menor preco" nao tem
 * relacao com a pagina 3 de "mais recentes".
 *
 * Sem JS, e um GET com os filtros atuais em campos ocultos e um botao
 * "Ordenar" no `<noscript>`: a URL que ele produz e a mesma que `urlDaBusca`
 * produziria, porque `filtrosDaUrl` le os dois formatos.
 */
export function OrdenacaoDaVitrine({ filtros }: { filtros: FiltrosDoPortal }) {
  const router = useRouter()
  const ocultos = new URLSearchParams(urlDaBusca({ ...filtros, ordem: undefined, pagina: undefined }).split('?')[1])

  return (
    <form className="portal-ordenacao" method="get" action="/busca">
      {[...ocultos.entries()].map(([chave, valor]) => (
        <input key={chave} type="hidden" name={chave} value={valor} />
      ))}
      <label>
        <span>Ordenar por</span>
        <select
          name="ordem"
          defaultValue={filtros.ordem ?? ORDEM_PADRAO}
          onChange={(evento) =>
            router.push(urlDaBusca({ ...filtros, ordem: evento.target.value as OrdemDaVitrine, pagina: undefined }))
          }
        >
          {(Object.keys(ORDENS_DA_VITRINE) as OrdemDaVitrine[]).map((ordem) => (
            <option key={ordem} value={ordem}>
              {ORDENS_DA_VITRINE[ordem]}
            </option>
          ))}
        </select>
      </label>
      <noscript>
        <button type="submit">Ordenar</button>
      </noscript>
    </form>
  )
}

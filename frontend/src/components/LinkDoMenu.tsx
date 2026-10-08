'use client'

import { usePathname } from 'next/navigation'

/**
 * Um item do menu, marcado com `aria-current` quando e a pagina aberta
 * (TEC-393). Cliente porque o layout do App Router nao recebe a rota atual.
 *
 * `/` so e atual em `/`; os demais tambem nas subrotas -- `/leads/123` ainda
 * e "Leads".
 */
export function LinkDoMenu({ href, children }: { href: string; children: string }) {
  const caminho = usePathname()
  const atual = href === '/' ? caminho === '/' : caminho === href || caminho?.startsWith(`${href}/`)

  return (
    <a href={href} className="menu-link" aria-current={atual ? 'page' : undefined}>
      {children}
    </a>
  )
}

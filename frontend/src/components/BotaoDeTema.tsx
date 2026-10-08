'use client'

import { Botao } from '@/components/ui/Botao'
import { COOKIE_DO_TEMA, proximoTema, SEGUNDOS_DO_TEMA, temaDoCookie } from '@/lib/tema'

/**
 * Alterna entre claro e escuro (TEC-393, D2).
 *
 * **O nome acessivel e fixo, e o icone e escolhido pelo CSS.** No servidor nao
 * se sabe o tema do sistema; um rotulo calculado no cliente divergiria do HTML
 * na hidratacao. Os dois icones vao no HTML, e o mesmo seletor que pinta a tela
 * mostra um e esconde o outro.
 */
export function BotaoDeTema() {
  function alternar() {
    const raiz = document.documentElement
    const proximo = proximoTema(
      temaDoCookie(raiz.dataset.tema),
      window.matchMedia('(prefers-color-scheme: dark)').matches,
    )
    raiz.dataset.tema = proximo
    document.cookie = `${COOKIE_DO_TEMA}=${proximo}; path=/; max-age=${SEGUNDOS_DO_TEMA}; samesite=lax`
  }

  return (
    <Botao variante="fantasma" tamanho="pequeno" aria-label="Alternar tema claro/escuro" onClick={alternar}>
      <svg className="icone-tema icone-tema--sol" width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="2" />
        <path
          d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <svg className="icone-tema icone-tema--lua" width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      </svg>
    </Botao>
  )
}

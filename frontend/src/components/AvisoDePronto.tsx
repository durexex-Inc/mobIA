'use client'

import { useEffect } from 'react'

/**
 * Diz ao loader do site que o chat carregou (TEC-344, D7).
 *
 * Um iframe de outra origem nao dispara `onerror` quando a pagina dele falha,
 * entao o loader espera esta mensagem e, sem ela em 10 s, some com o botao.
 *
 * `'*'` como destino, e nao a origem do site: esta pagina nao sabe em que site
 * esta, e a mensagem nao carrega nada alem do proprio aviso. Quem confere
 * origem e o loader, ao receber.
 */
export function AvisoDePronto() {
  useEffect(() => {
    window.parent.postMessage({ tipo: 'mobia:pronto' }, '*')
  }, [])
  return null
}

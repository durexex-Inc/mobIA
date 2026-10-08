'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

/** RN-FE-05.4 (TEC-317): o intervalo de polling com a aba visivel. */
export const INTERVALO_DE_ATUALIZACAO_MS = 30_000

/**
 * Mantem o funil fresco sozinho, sem recarregar a pagina (TEC-317).
 *
 * **Nao busca nada.** Quem busca e a `Pagina`, no servidor -- isto so chama
 * `router.refresh()`, que reexecuta o server component com os MESMOS
 * `searchParams` (os filtros SAO a URL, TEC-190/TEC-316). `revalidarEmSegundos:
 * 30` em `buscarFunil` (`lib/metricas.ts`) e o que faz cada refresh custar no
 * maximo uma chamada ao FastAPI a cada 30s por pessoa -- duas abas da mesma
 * pessoa dividem a mesma entrada do Data Cache, que casa por `Authorization`
 * (TEC-309, D7).
 *
 * **O relogio de reagendamento e proprio (`ultimaTentativa`), e nao o
 * `atualizadoEm` que o servidor manda.** Se o agendamento dependesse de
 * `atualizadoEm` mudar para se rearmar, um `router.refresh()` que falhe em
 * silencio -- rede instavel, aba que o SO suspendeu -- pararia o polling para
 * sempre: a prop nunca mudaria, e nada o reagendaria. Com o relogio proprio, a
 * tentativa seguinte acontece 30s depois de qualquer jeito, sucesso ou nao.
 *
 * **Pausa com a aba oculta** (RN-FE-05.4): `talvezAtualizar` sai cedo quando
 * `document.visibilityState` nao e `'visible'`, sem tocar no relogio. Ao
 * voltar a ficar visivel, o listener de `visibilitychange` dispara a checagem
 * na hora -- sem esperar o proximo segundo cheio --, e como o relogio nunca
 * foi zerado enquanto oculta, uma ausencia de 30s ou mais atualiza uma vez so,
 * imediatamente, nao em rajada.
 */
export function AtualizacaoAutomatica({ atualizadoEm }: { atualizadoEm: string }) {
  const router = useRouter()
  const ultimaTentativa = useRef(new Date(atualizadoEm).getTime())
  // Comeca em 0: o servidor tambem renderiza "ha 0 s" (`atualizadoEm` acabou
  // de ser gravado quando esta pagina foi montada), entao a hidratacao nao
  // diverge. So passa a refletir o tempo real dentro do efeito, que roda
  // exclusivamente no cliente (D5 do desenho).
  const [segundos, setSegundos] = useState(0)

  useEffect(() => {
    function talvezAtualizar() {
      if (document.visibilityState !== 'visible') {
        return
      }
      const agora = Date.now()
      if (agora - ultimaTentativa.current >= INTERVALO_DE_ATUALIZACAO_MS) {
        ultimaTentativa.current = agora
        router.refresh()
      }
      setSegundos(Math.max(0, Math.round((Date.now() - new Date(atualizadoEm).getTime()) / 1000)))
    }

    const relogio = window.setInterval(talvezAtualizar, 1000)
    document.addEventListener('visibilitychange', talvezAtualizar)
    return () => {
      window.clearInterval(relogio)
      document.removeEventListener('visibilitychange', talvezAtualizar)
    }
  }, [atualizadoEm, router])

  return (
    <p className="funil-atualizacao" aria-live="polite">
      <span className="ponto-de-status" aria-hidden="true" />
      Atualizado há {segundos} s
    </p>
  )
}

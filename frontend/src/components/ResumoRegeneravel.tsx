'use client'

import { useEffect, useState } from 'react'

import { dividirResumo, type ResumoDoLead } from '@/lib/detalhe'

/** A trava entre dois resumos, a mesma do backend (TEC-193, D6). */
export const TRAVA_DA_REGENERACAO_MS = 60_000

type Estado = 'pronto' | 'gerando'

/**
 * A secao Resumo do detalhe, com o "Regenerar" (TEC-326).
 *
 * **O novo resumo entra no lugar do antigo pela resposta do `POST`** (D2), e
 * nao relendo o detalhe: `router.refresh()` gravaria mais um acesso na trilha
 * para mostrar um texto que a resposta ja trouxe. Durante a geracao -- a rota
 * e sincrona e espera o modelo --, o anterior fica visivel e a secao diz que
 * esta gerando.
 *
 * **A trava de 60 s conta de `geradoEm`** (D3), como a do backend: a geracao
 * automatica do handoff tambem conta, e o `geradoEm` novo reinicia a trava. O
 * 429 que ainda chegar (relogio adiantado, outra aba) e dito como trava, com o
 * `Retry-After`, e nao como erro.
 */
export function ResumoRegeneravel({
  resumo: inicial,
  podeRegenerar,
}: {
  resumo: ResumoDoLead
  podeRegenerar: boolean
}) {
  const [resumo, setResumo] = useState(inicial)
  const [estado, setEstado] = useState<Estado>('pronto')
  const [aviso, setAviso] = useState('')
  // Ate quando a trava vale, em ms do relogio local. O 429 pode empurra-la.
  const [livreEm, setLivreEm] = useState(() => liberacao(inicial.geradoEm))
  const [agora, setAgora] = useState(() => Date.now())

  const restante = Math.max(0, Math.ceil((livreEm - agora) / 1000))
  const travado = restante > 0

  // O relogio so anda enquanto ha trava a contar.
  useEffect(() => {
    if (!travado) {
      return
    }
    const relogio = setInterval(() => setAgora(Date.now()), 1000)
    return () => clearInterval(relogio)
  }, [travado])

  async function regenerar() {
    setEstado('gerando')
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/handoffs/${encodeURIComponent(resumo.handoffId)}/resumo`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      })
    } catch {
      setEstado('pronto')
      setAviso('Não foi possível gerar o novo resumo. Tente de novo.')
      return
    }

    if (resposta.status === 429) {
      const segundos = Number(resposta.headers.get('retry-after')) || TRAVA_DA_REGENERACAO_MS / 1000
      setLivreEm(Date.now() + segundos * 1000)
      setAgora(Date.now())
      setEstado('pronto')
      setAviso('O resumo foi gerado há menos de um minuto.')
      return
    }
    if (!resposta.ok) {
      setEstado('pronto')
      setAviso(motivoDaRecusa(resposta.status))
      return
    }

    const novo = (await resposta.json()) as {
      resumo: string
      geradoEm: string | null
      modelo: string | null
      resumoFallback: boolean
    }
    setResumo({
      handoffId: resumo.handoffId,
      texto: novo.resumo,
      geradoEm: novo.geradoEm,
      modelo: novo.modelo,
      fallback: novo.resumoFallback,
    })
    setLivreEm(liberacao(novo.geradoEm))
    setAgora(Date.now())
    setEstado('pronto')
  }

  const rotulo = resumo.fallback ? 'Resumo simplificado' : 'Gerado pelo assistente'
  const emBlocos = dividirResumo(resumo.texto, { fallback: resumo.fallback })

  return (
    <section className="detalhe-secao" aria-label="Resumo" aria-busy={estado === 'gerando'}>
      <h2>
        Resumo
        <span className="detalhe-rotulo">{rotulo}</span>
      </h2>
      {emBlocos ? (
        <>
          {emBlocos.preambulo && <p className="detalhe-texto">{emBlocos.preambulo}</p>}
          {emBlocos.blocos.map((bloco) => (
            <div key={bloco.titulo} className="detalhe-bloco">
              <h3>{bloco.titulo}</h3>
              <p className="detalhe-texto">{bloco.corpo}</p>
            </div>
          ))}
        </>
      ) : (
        // Texto que nao se deixa cortar sai inteiro: esconder o resumo seria
        // pior que mostra-lo sem os titulos.
        <p className="detalhe-texto">{resumo.texto}</p>
      )}
      {podeRegenerar && (
        <div className="resumo-regenerar">
          <button type="button" onClick={regenerar} disabled={estado === 'gerando' || travado}>
            Regenerar resumo
          </button>
          <span role="status" className="resumo-estado">
            {estado === 'gerando'
              ? 'Gerando novo resumo…'
              : [aviso, travado ? `Disponível em ${restante} s.` : ''].filter(Boolean).join(' ')}
          </span>
        </div>
      )}
    </section>
  )
}

function liberacao(geradoEm: string | null): number {
  return geradoEm ? Date.parse(geradoEm) + TRAVA_DA_REGENERACAO_MS : 0
}

function motivoDaRecusa(status: number): string {
  if (status === 401) {
    return 'Sua sessão terminou. Recarregue a página para entrar de novo.'
  }
  if (status === 403 || status === 404) {
    return 'Não foi possível regenerar este resumo.'
  }
  return 'Não foi possível gerar o novo resumo. Tente de novo.'
}

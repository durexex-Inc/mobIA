'use client'

import { useEffect, useRef, useState } from 'react'

import { NAO_INFORMADO } from '@/lib/detalhe'

/** Quanto o valor revelado fica na tela (TEC-330, D1). */
export const PRAZO_DA_REVELACAO_MS = 5 * 60 * 1000

export type CampoRevelavel = 'telefone' | 'email'

/**
 * Telefone ou e-mail mascarado, com o "Revelar" para quem pode (TEC-330). Serve
 * o lead e, desde a TEC-404, o pedido de interesse: com `url`, a revelacao vai
 * a rota dada (`/bff/api/v1/interesses/{id}/revelar`, D5 do desenho da
 * TEC-404) e nao a do lead -- o e-mail e por pedido, e a rota do lead o
 * corretor nao abre. Sem `url`, continua sendo
 * `/bff/api/v1/leads/{leadId}/revelar`. Os D1, D2 e D4 abaixo sao da TEC-330.
 *
 * **O valor em claro vive SO no estado deste componente** (D1): some no prazo,
 * no "Ocultar" ou quando o componente desmonta -- sair da tela e voltar comeca
 * mascarado. Nada vai para URL, armazenamento do navegador ou `console`.
 *
 * **O valor so aparece com a resposta 200**, e o backend so responde depois
 * de comitar a linha na trilha (docstring de `revelar` em
 * `api/routes/leads.py`). Nao ha estado em que a tela mostre o numero antes
 * de a auditoria existir. A rota do pedido faz o mesmo
 * (`api/routes/interesses.py::revelar`).
 *
 * Sem mascara nao ha botao (D2): revelar um campo vazio gravaria na trilha a
 * leitura de nada. Com `href`, o texto e um link e o botao fica fora dele --
 * a primeira coluna da lista abre o detalhe (D4).
 */
export function DadoRevelavel({
  leadId,
  campo,
  mascarado,
  podeRevelar,
  href,
  url,
  vazio = NAO_INFORMADO,
}: {
  leadId: string
  campo: CampoRevelavel
  mascarado: string | null
  podeRevelar: boolean
  href?: string
  url?: string
  vazio?: string
}) {
  // `undefined` e "nao revelado"; `null` e "revelado, e o backend disse que
  // nao ha valor" (D2) -- a tela nao volta a mostrar a mascara como se
  // houvesse numero.
  const [revelado, setRevelado] = useState<string | null | undefined>(undefined)
  const [enviando, setEnviando] = useState(false)
  const [aviso, setAviso] = useState('')
  const prazo = useRef<ReturnType<typeof setTimeout> | null>(null)

  function ocultar() {
    if (prazo.current) {
      clearTimeout(prazo.current)
      prazo.current = null
    }
    setRevelado(undefined)
  }

  // Desmontar com o prazo correndo nao deixa o timer vivo.
  useEffect(() => () => {
    if (prazo.current) {
      clearTimeout(prazo.current)
    }
  }, [])

  async function revelar() {
    setEnviando(true)
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(url ?? `/bff/api/v1/leads/${encodeURIComponent(leadId)}/revelar`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ campo }),
        cache: 'no-store',
      })
    } catch {
      setEnviando(false)
      setAviso('Não foi possível revelar. Tente de novo.')
      return
    }

    if (!resposta.ok) {
      setEnviando(false)
      setAviso(motivoDaRecusa(resposta.status, url !== undefined))
      return
    }

    let valor: string | null
    try {
      valor = ((await resposta.json()) as { valor?: string | null }).valor ?? null
    } catch {
      setEnviando(false)
      setAviso('Não foi possível revelar. Tente de novo.')
      return
    }

    setEnviando(false)
    setRevelado(valor)
    prazo.current = setTimeout(() => {
      prazo.current = null
      setRevelado(undefined)
    }, PRAZO_DA_REVELACAO_MS)
  }

  const estaRevelado = revelado !== undefined
  const texto = estaRevelado ? (revelado ?? vazio) : (mascarado ?? vazio)
  const nome = campo === 'telefone' ? 'telefone' : 'e-mail'

  return (
    <span className="dado-revelavel">
      {href ? <a href={href}>{texto}</a> : <span>{texto}</span>}
      {podeRevelar && mascarado !== null && (
        <button
          type="button"
          className="dado-revelavel-acao"
          onClick={estaRevelado ? ocultar : revelar}
          disabled={enviando}
          aria-label={estaRevelado ? `Ocultar ${nome}` : `Revelar ${nome}`}
        >
          {estaRevelado ? 'Ocultar' : 'Revelar'}
        </button>
      )}
      {aviso && (
        <span className="dado-revelavel-aviso" role="alert">
          {aviso}
        </span>
      )}
    </span>
  )
}

/**
 * Com `url` de fora, quem sumiu pode nao ser o lead -- no pedido de interesse
 * e o pedido --, entao o 404 nao nomeia o lead.
 */
function motivoDaRecusa(status: number, urlPropria: boolean): string {
  if (status === 401) {
    return 'Sua sessão terminou. Recarregue a página para entrar de novo.'
  }
  if (status === 403) {
    return 'Você não tem permissão para ver este dado.'
  }
  if (status === 404) {
    return urlPropria ? 'Este registro não existe mais.' : 'Este lead não existe mais.'
  }
  return 'Não foi possível revelar. Tente de novo.'
}

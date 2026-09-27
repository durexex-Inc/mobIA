'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import type { Atendimento } from '@/lib/detalhe'

type Acao = 'assumir' | 'devolver'

/**
 * Assumir e devolver a conversa (TEC-327, D4) -- o quarto componente de
 * cliente do painel, e o primeiro que MUDA estado no backend.
 *
 * **Depois da acao, a tela recarrega do servidor** (`router.refresh()`), e nao
 * muda a faixa por conta propria: quem sabe o estado e o servidor, e mudar sem
 * ler de volta poderia mostrar o controle depois de uma resposta que nao o deu.
 *
 * A acao vai pelo proxy `/bff/*`, que poe o JWT da sessao e recusa mutacao sem
 * `Origin` da propria origem. O corretor em nome de quem se age e o da claim
 * do JWT: nada aqui diz quem e.
 */
export function ControleDaConversa({
  leadId,
  atendimento,
  meuCorretorId,
  confirmar = (pergunta: string) => window.confirm(pergunta),
}: {
  leadId: string
  atendimento: Atendimento | null
  meuCorretorId: string
  confirmar?: (pergunta: string) => boolean
}) {
  const router = useRouter()
  const [enviando, setEnviando] = useState(false)
  const [aviso, setAviso] = useState('')

  const souEuQuemTem = atendimento?.assumidoPor.corretorId === meuCorretorId

  async function agir(acao: Acao) {
    const pergunta =
      acao === 'assumir'
        ? 'Assumir a conversa? O assistente para de responder o lead até você devolver.'
        : 'Devolver a conversa ao assistente? Ele volta a responder o lead.'
    if (!confirmar(pergunta)) {
      return
    }
    setEnviando(true)
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/leads/${encodeURIComponent(leadId)}/${acao}`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      })
    } catch {
      setEnviando(false)
      setAviso('Não foi possível falar com o servidor. Tente de novo.')
      return
    }

    if (resposta.ok) {
      router.refresh()
      setEnviando(false)
      return
    }
    setEnviando(false)
    setAviso(await motivoDaRecusa(resposta))
  }

  return (
    <div className="controle-da-conversa">
      {souEuQuemTem && (
        // A faixa permanente da card: fica enquanto a conversa for de quem ve.
        <p className="controle-faixa" role="status">
          Você está no controle — o agente está em silêncio
        </p>
      )}
      {atendimento && !souEuQuemTem && (
        <p className="controle-de-outro">A conversa está com {atendimento.assumidoPor.nome}.</p>
      )}
      <div className="controle-acoes">
        {!atendimento && (
          <button type="button" onClick={() => agir('assumir')} disabled={enviando}>
            Assumir conversa
          </button>
        )}
        {/* "Devolver" aparece tambem quando outro tem a conversa: o backend
            aceita a devolucao de qualquer corretor, e e o conserto do colega
            que assumiu e saiu de ferias (docstring de `devolver` no
            repositorio do atendimento). */}
        {atendimento && (
          <button type="button" onClick={() => agir('devolver')} disabled={enviando}>
            Devolver ao agente
          </button>
        )}
      </div>
      {aviso && (
        <p className="controle-aviso" role="alert">
          {aviso}
        </p>
      )}
    </div>
  )
}

/**
 * O que dizer quando o backend recusa. O 409 de `assumir` traz quem tem a
 * conversa (TEC-327, D3); sem o nome -- o dono devolveu entre a recusa e a
 * leitura --, a tela manda recarregar em vez de tentar de novo sozinha.
 */
async function motivoDaRecusa(resposta: Response): Promise<string> {
  if (resposta.status === 401) {
    return 'Sua sessão terminou. Recarregue a página para entrar de novo.'
  }
  let detail: unknown
  try {
    detail = ((await resposta.json()) as { detail?: unknown }).detail
  } catch {
    detail = undefined
  }
  if (resposta.status === 409 && typeof detail === 'object' && detail !== null) {
    const dono = (detail as { assumidoPor?: { nome?: string } | null }).assumidoPor
    return dono?.nome
      ? `A conversa já está com ${dono.nome}.`
      : 'A conversa mudou de mãos. Recarregue a página.'
  }
  if (resposta.status === 409) {
    return 'Não foi possível: esta conversa não está no estado esperado. Recarregue a página.'
  }
  return 'Não foi possível concluir. Tente de novo.'
}

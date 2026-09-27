'use client'

import { useEffect, useId, useRef, useState } from 'react'

import {
  contador,
  EXPLICACAO_DA_JANELA,
  janelaFechada,
  LIMITE_DA_RESPOSTA,
  podeEnviar,
  type Recusa,
  recusaDaResposta,
} from '@/lib/resposta'
import type { Fala } from '@/lib/transcricao'

/** De quanto em quanto tempo o relogio da janela e conferido (D3). */
const RELOGIO_MS = 60_000

/**
 * O campo em que o corretor responde o lead (TEC-328, D3 e D4). Mora dentro
 * da conversa: quem o monta e `Transcricao`, que sabe se a conversa e de quem
 * ve a tela e qual e a fala mais recente do lead.
 *
 * **A fala enviada entra na conversa pela resposta do `POST`**, com o `id` e
 * o `em` do servidor: `aoEnviar` a poe no fim da lista, e o polling, que traz a
 * mesma fala depois, nao a duplica -- a lista deduplica por `id`.
 *
 * **O `messageId` e por texto, e nao por clique.** Nasce no primeiro envio e
 * e reusado enquanto o texto nao mudar: se a rede cair depois de a Meta
 * entregar, o reenvio volta como "ja enviada" em vez de chegar duas vezes ao
 * lead (D1). Mudar o texto ou enviar com sucesso gera outro.
 */
export function RespostaDoCorretor({
  leadId,
  conversaMinha,
  janelaFechaEm,
  ultimaFalaDoLeadEm,
  aoEnviar,
}: {
  leadId: string
  conversaMinha: boolean
  janelaFechaEm: string | null
  ultimaFalaDoLeadEm: string | null
  aoEnviar: (fala: Fala) => void
}) {
  const id = useId()
  const [texto, setTexto] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [recusa, setRecusa] = useState<Recusa | null>(null)
  const [agora, setAgora] = useState(() => new Date())
  const messageId = useRef<string | null>(null)

  // O relogio da janela anda com a tela aberta: a janela que fecha durante a
  // leitura desabilita o campo sem recarregar.
  useEffect(() => {
    if (janelaFechaEm === null) {
      return
    }
    const relogio = setInterval(() => setAgora(new Date()), RELOGIO_MS)
    return () => clearInterval(relogio)
  }, [janelaFechaEm])

  const fechada =
    recusa?.bloqueia === 'janela' ||
    janelaFechada({ fechaEm: janelaFechaEm, ultimaFalaDoLeadEm, agora })
  const bloqueio = recusa?.bloqueia === 'optout' || recusa?.bloqueia === 'outro'
  const indisponivel = !conversaMinha || fechada || bloqueio
  const { usados, excesso } = contador(texto)

  function mudar(novo: string) {
    setTexto(novo)
    // Texto novo e outra mensagem: o id da anterior nao serve mais.
    messageId.current = null
    if (recusa?.bloqueia === null) {
      setRecusa(null)
    }
  }

  async function enviar(evento: React.FormEvent) {
    evento.preventDefault()
    if (indisponivel || enviando || !podeEnviar(texto)) {
      return
    }
    messageId.current ??= crypto.randomUUID()
    setEnviando(true)
    setRecusa(null)

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/leads/${encodeURIComponent(leadId)}/mensagens`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ texto, messageId: messageId.current }),
      })
    } catch {
      setEnviando(false)
      setRecusa(recusaDaResposta(502, null))
      return
    }

    let dados: Record<string, unknown> = {}
    try {
      dados = (await resposta.json()) as Record<string, unknown>
    } catch {
      dados = {}
    }
    setEnviando(false)

    if (!resposta.ok) {
      setRecusa(recusaDaResposta(resposta.status, dados.detail))
      return
    }

    aoEnviar({
      id: String(dados.id),
      autor: 'CORRETOR',
      tipo: 'TEXTO',
      // O texto como o servidor o gravou: `strip` das pontas (TEC-194).
      conteudo: texto.trim(),
      retida: false,
      em: String(dados.em),
    })
    setTexto('')
    messageId.current = null
  }

  let motivo: string | null = null
  if (!conversaMinha) {
    motivo = 'Assuma a conversa para responder.'
  } else if (fechada) {
    motivo = EXPLICACAO_DA_JANELA
  }

  return (
    <form className="resposta" onSubmit={enviar}>
      <label htmlFor={id} className="resposta-rotulo">
        Responder ao lead
      </label>
      <textarea
        id={id}
        value={texto}
        onChange={(evento) => mudar(evento.target.value)}
        disabled={indisponivel}
        rows={3}
        aria-describedby={`${id}-contador${motivo ? ` ${id}-motivo` : ''}`}
        aria-invalid={excesso > 0 ? true : undefined}
      />
      <div className="resposta-rodape">
        <span id={`${id}-contador`} className={excesso > 0 ? 'resposta-excesso' : undefined}>
          {usados}/{LIMITE_DA_RESPOSTA}
          {excesso > 0 && ` — ${excesso} ${excesso === 1 ? 'caractere' : 'caracteres'} a mais`}
        </span>
        <button type="submit" disabled={indisponivel || enviando || !podeEnviar(texto)}>
          {enviando ? 'Enviando…' : 'Enviar'}
        </button>
      </div>
      {motivo && (
        <p id={`${id}-motivo`} className="resposta-motivo" role="status">
          {motivo}
        </p>
      )}
      {recusa && recusa.bloqueia !== 'janela' && (
        <p className="resposta-aviso" role="alert">
          {recusa.mensagem}
        </p>
      )}
    </form>
  )
}

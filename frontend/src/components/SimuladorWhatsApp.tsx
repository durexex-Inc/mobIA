'use client'

import { useRef, useState } from 'react'

type Fala = { papel: 'lead' | 'agente'; texto: string; em: string }

type Frame =
  | { tipo: 'sessao'; telefone: string }
  | { tipo: 'historico'; mensagens: Fala[] }
  | { tipo: 'ack'; messageId: string }
  | { tipo: 'mensagem'; texto: string; kind?: string }
  | { tipo: 'imovel'; imovel: unknown; texto: string | null; kind?: string }
  | { tipo: 'imagem'; link: string; legenda: string | null; kind?: string }
  | { tipo: 'erro'; codigo: string; mensagem: string; messageId?: string }

type Estado = { fase: 'telefone' } | { fase: 'conectando' } | { fase: 'conversa' } | { fase: 'erro'; mensagem: string }

/**
 * Simula uma conversa de WhatsApp com o agente, sem a Cloud API da Meta --
 * ferramenta de desenvolvimento. O telefone digitado E a identidade: nao ha
 * login, nao ha sessao de navegador, e reconectar com o mesmo numero retoma
 * a mesma conversa (mesmo protocolo de `Conversa.tsx`, simplificado -- sem
 * consentimento, sem indicador de digitação, sem reconexao automatica).
 */
export function SimuladorWhatsApp({ endereco }: { endereco: string }) {
  const [estado, setEstado] = useState<Estado>({ fase: 'telefone' })
  const [telefone, setTelefone] = useState('')
  const [falas, setFalas] = useState<Fala[]>([])
  const [texto, setTexto] = useState('')
  const socketRef = useRef<WebSocket | null>(null)

  function conectar(telefoneDigitado: string) {
    setEstado({ fase: 'conectando' })
    const socket = new WebSocket(endereco)
    socketRef.current = socket

    socket.onopen = () => {
      socket.send(JSON.stringify({ tipo: 'ola', telefone: telefoneDigitado }))
    }

    socket.onmessage = (evento) => {
      let frame: Frame
      try {
        frame = JSON.parse(String(evento.data)) as Frame
      } catch {
        return
      }
      if (frame.tipo === 'sessao') {
        setEstado({ fase: 'conversa' })
        return
      }
      if (frame.tipo === 'historico') {
        setFalas(frame.mensagens)
        return
      }
      if (frame.tipo === 'mensagem') {
        setFalas((atual) => [...atual, { papel: 'agente', texto: frame.texto, em: new Date().toISOString() }])
        return
      }
      if (frame.tipo === 'imovel') {
        const linha = frame.texto ?? JSON.stringify(frame.imovel)
        setFalas((atual) => [...atual, { papel: 'agente', texto: linha, em: new Date().toISOString() }])
        return
      }
      if (frame.tipo === 'imagem') {
        setFalas((atual) => [
          ...atual,
          { papel: 'agente', texto: `${frame.legenda ?? ''} (${frame.link})`, em: new Date().toISOString() },
        ])
        return
      }
      if (frame.tipo === 'erro') {
        setFalas((atual) => [
          ...atual,
          { papel: 'agente', texto: `[erro: ${frame.mensagem}]`, em: new Date().toISOString() },
        ])
      }
    }

    socket.onclose = () => {
      setEstado((atual) => (atual.fase === 'conversa' ? { fase: 'erro', mensagem: 'Conexão encerrada.' } : atual))
    }

    socket.onerror = () => {
      setEstado({ fase: 'erro', mensagem: 'Não foi possível conectar.' })
    }
  }

  function enviarTelefone(evento: React.FormEvent) {
    evento.preventDefault()
    if (!telefone.trim()) {
      return
    }
    conectar(telefone.trim())
  }

  function enviarMensagem(evento: React.FormEvent) {
    evento.preventDefault()
    const socket = socketRef.current
    const corpo = texto.trim()
    if (!socket || socket.readyState !== WebSocket.OPEN || !corpo) {
      return
    }
    const id = crypto.randomUUID()
    socket.send(JSON.stringify({ tipo: 'mensagem', id, texto: corpo }))
    setFalas((atual) => [...atual, { papel: 'lead', texto: corpo, em: new Date().toISOString() }])
    setTexto('')
  }

  if (estado.fase === 'telefone' || estado.fase === 'conectando') {
    return (
      <form onSubmit={enviarTelefone} className="simulador-whatsapp__identificacao">
        <label>
          Telefone (com DDD)
          <input
            type="tel"
            value={telefone}
            onChange={(evento) => setTelefone(evento.target.value)}
            disabled={estado.fase === 'conectando'}
            required
          />
        </label>
        <button type="submit" disabled={estado.fase === 'conectando'}>
          {estado.fase === 'conectando' ? 'Conectando...' : 'Começar a conversar'}
        </button>
      </form>
    )
  }

  if (estado.fase === 'erro') {
    return (
      <p role="alert" className="simulador-whatsapp__erro">
        {estado.mensagem}
      </p>
    )
  }

  return (
    <div className="simulador-whatsapp__conversa">
      <ul className="simulador-whatsapp__falas" aria-label="Conversa">
        {falas.map((fala, indice) => (
          <li key={indice} className={`simulador-whatsapp__fala simulador-whatsapp__fala--${fala.papel}`}>
            {fala.texto}
          </li>
        ))}
      </ul>
      <form onSubmit={enviarMensagem} className="simulador-whatsapp__envio">
        <label htmlFor="simulador-texto">Mensagem</label>
        <input
          id="simulador-texto"
          type="text"
          value={texto}
          onChange={(evento) => setTexto(evento.target.value)}
        />
        <button type="submit">Enviar</button>
      </form>
    </div>
  )
}

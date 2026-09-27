'use client'

import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useReducer, useRef, useState } from 'react'

import {
  type EstadoDaMensagem,
  INICIAL,
  LIMITE_DE_CARACTERES,
  novoMessageId,
  PRAZO_DO_ACK_MS,
  reduzir,
} from '@/lib/conversa'

const CHAVE_DA_SESSAO = 'mobia:sessao'

const ROTULO_DO_ESTADO: Record<EstadoDaMensagem, string> = {
  enviando: 'Enviando…',
  recebida: 'Recebida',
  falhou: 'Não enviada',
}

// Quanto acima do fim a lista ainda conta como "no fim" para rolar sozinha.
const DISTANCIA_DO_FIM_PX = 40

type Envio = { id: string; texto: string }

function frameDeMensagem({ id, texto }: Envio): string {
  return JSON.stringify({ tipo: 'mensagem', id, texto })
}

/**
 * A conversa do chat embutido (TEC-346): liga o redutor de `lib/conversa`
 * (D3) a um `WebSocket` de verdade e desenha a tela da D5. Todo o I/O mora
 * aqui -- socket, timers do prazo do `ack`, `localStorage` --; decidir o
 * proximo estado e do redutor.
 *
 * **So o socket atual fala com a tela.** Cada listener confere
 * `socketRef.current === socket` antes de despachar: o socket de uma montagem
 * descartada (o StrictMode monta, desmonta e monta de novo) ou o de antes de
 * um reenvio ainda pode entregar `message` e `close`, e um `close` atrasado
 * marcaria como `falhou` o que o socket novo esta enviando.
 *
 * **Mensagem que sai com o socket fechado espera o `open` na fila.** Enviar
 * ou reenviar sem socket aberto abre um novo (a menos que um ja esteja
 * conectando) e a mensagem sai logo depois do `ola`. Reenviar usa o mesmo
 * `messageId` (D3) -- o servidor deduplica dentro da sessao, e por isso a
 * reconexao retoma a sessao em memoria (abaixo) --, e despacha `reenviou`,
 * nunca `enviou`, que duplicaria o balao.
 *
 * **A sessao gravada nao e lida; a da memoria, sim (D4).** O primeiro `ola`
 * de cada montagem vai com `sessao: null` -- retomar pelo UUID do
 * `localStorage` e da TEC-347. Toda conexao seguinte da mesma montagem
 * (reenvio, envio com o socket fechado, fim da espera) manda a sessao que o
 * servidor emitiu nesta montagem, se ja emitiu: sem isso cada queda abriria
 * uma conversa nova, o agente perderia o contexto e a dedup por `messageId`
 * nao valeria entre as duas. O `historico` que o servidor devolve na
 * retomada e ignorado pelo redutor -- os baloes ja estao na tela. A
 * reconexao e so manual (L5) -- reconectar sozinho depois de uma queda e da
 * TEC-348. A unica reabertura automatica e a do fim da espera de
 * `muitas_tentativas` (D5).
 */
export function Conversa({ endereco }: { endereco: string }) {
  const [conversa, despachar] = useReducer(reduzir, INICIAL)
  const [rascunho, setRascunho] = useState('')
  const socketRef = useRef<WebSocket | null>(null)
  // Mensagens que esperam o `open` do socket atual para sair.
  const filaRef = useRef<Envio[]>([])
  const prazosRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  // A sessao que o servidor emitiu NESTA montagem, para o `ola` das
  // reconexoes. Comeca nula e so o frame `sessao` a preenche -- nunca o
  // `localStorage` (D4) --, entao a primeira conexao sempre vai com `null`.
  const sessaoRef = useRef<string | null>(null)

  const conectar = useCallback(() => {
    const socket = new WebSocket(endereco)
    const anterior = socketRef.current
    socketRef.current = socket
    anterior?.close()
    const atual = () => socketRef.current === socket

    socket.addEventListener('open', () => {
      if (!atual()) {
        return
      }
      despachar({ tipo: 'abriu' })
      socket.send(JSON.stringify({ tipo: 'ola', sessao: sessaoRef.current }))
      for (const envio of filaRef.current.splice(0)) {
        socket.send(frameDeMensagem(envio))
      }
    })
    socket.addEventListener('message', (evento: MessageEvent) => {
      if (atual() && typeof evento.data === 'string') {
        despachar({ tipo: 'frame', bruto: evento.data })
      }
    })
    socket.addEventListener('close', () => {
      if (!atual()) {
        return
      }
      // O que estava na fila nunca saiu; o redutor ja o marca como `falhou`.
      filaRef.current = []
      despachar({ tipo: 'fechou' })
    })
  }, [endereco])

  useEffect(() => {
    const prazos = prazosRef.current
    conectar()
    return () => {
      const socket = socketRef.current
      socketRef.current = null
      socket?.close()
      filaRef.current = []
      for (const prazo of prazos.values()) {
        clearTimeout(prazo)
      }
      prazos.clear()
    }
  }, [conectar])

  // Fim da espera de `muitas_tentativas`: `reabrindo` tira a conexao de
  // `aguardando` e um socket novo abre. Sem o `reabrindo`, uma queda desse
  // socket antes do `open` manteria a espera -- o mesmo objeto, sem timer
  // novo -- e o chat ficaria preso nela. `espera` e o proprio objeto da
  // conexao, que o redutor preserva enquanto nada muda -- entao o timer nao
  // reinicia a cada balao que chega.
  const espera = conversa.conexao.tipo === 'aguardando' ? conversa.conexao : null
  useEffect(() => {
    if (!espera) {
      return
    }
    const reabrir = setTimeout(() => {
      despachar({ tipo: 'reabrindo' })
      conectar()
    }, espera.segundos * 1000)
    return () => clearTimeout(reabrir)
  }, [espera, conectar])

  // A mensagem mais nova a vista -- mas so se a visitante ja estava perto do
  // fim, ou se a mensagem nova e dela: quem rolou para cima para reler nao e
  // puxado de volta a cada fala do agente. "Perto do fim" e medido no
  // `scroll`, ANTES de o balao novo crescer a lista; medir depois daria
  // sempre longe. `scrollTop` na propria lista, e nao `scrollIntoView`:
  // dentro do iframe, `scrollIntoView` tambem rola os ancestrais --
  // inclusive a pagina do site da imobiliaria.
  const listaRef = useRef<HTMLOListElement | null>(null)
  const pertoDoFimRef = useRef(true)
  const totalDeMensagens = conversa.mensagens.length
  const autorDaUltima = conversa.mensagens.at(-1)?.autor
  useEffect(() => {
    const lista = listaRef.current
    if (totalDeMensagens > 0 && lista && (pertoDoFimRef.current || autorDaUltima === 'visitante')) {
      lista.scrollTop = lista.scrollHeight
      pertoDoFimRef.current = true
    }
  }, [totalDeMensagens, autorDaUltima])

  function aoRolar() {
    const lista = listaRef.current
    if (lista) {
      pertoDoFimRef.current = lista.scrollHeight - lista.scrollTop - lista.clientHeight <= DISTANCIA_DO_FIM_PX
    }
  }

  useEffect(() => {
    sessaoRef.current = conversa.sessao
    if (!conversa.sessao) {
      return
    }
    try {
      localStorage.setItem(CHAVE_DA_SESSAO, conversa.sessao)
    } catch {
      // Modo privado ou storage bloqueado: a conversa segue sem gravar (D4).
    }
  }, [conversa.sessao])

  // Prazo de mensagem que ja saiu de `enviando` (ack, erro, queda) nao tem
  // mais o que marcar.
  useEffect(() => {
    const prazos = prazosRef.current
    for (const mensagem of conversa.mensagens) {
      if (mensagem.autor === 'visitante' && mensagem.estado !== 'enviando' && prazos.has(mensagem.messageId)) {
        clearTimeout(prazos.get(mensagem.messageId))
        prazos.delete(mensagem.messageId)
      }
    }
  }, [conversa.mensagens])

  function agendarPrazo(id: string) {
    const prazos = prazosRef.current
    // Um reenvio antes do prazo do envio anterior substitui o prazo: senao o
    // antigo venceria no meio do reenvio e o marcaria `falhou` antes da hora.
    clearTimeout(prazos.get(id))
    prazos.set(
      id,
      setTimeout(() => {
        prazos.delete(id)
        despachar({ tipo: 'prazoDoAck', messageId: id })
      }, PRAZO_DO_ACK_MS),
    )
  }

  function transmitir(envio: Envio) {
    agendarPrazo(envio.id)
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(frameDeMensagem(envio))
      return
    }
    filaRef.current.push(envio)
    if (socket?.readyState !== WebSocket.CONNECTING) {
      conectar()
    }
  }

  function enviarRascunho() {
    const texto = rascunho.trim()
    if (!texto) {
      return
    }
    const id = novoMessageId()
    despachar({ tipo: 'enviou', messageId: id, texto })
    transmitir({ id, texto })
    setRascunho('')
  }

  function aoEnviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    enviarRascunho()
  }

  // Enter envia, pelo mesmo caminho do botao; Shift+Enter quebra a linha. O
  // Enter que confirma a composicao de um IME nao e envio.
  function aoTeclar(evento: KeyboardEvent<HTMLTextAreaElement>) {
    if (evento.key === 'Enter' && !evento.shiftKey && !evento.nativeEvent.isComposing) {
      evento.preventDefault()
      enviarRascunho()
    }
  }

  function reenviar(id: string, texto: string) {
    despachar({ tipo: 'reenviou', messageId: id })
    transmitir({ id, texto })
  }

  return (
    <section className="conversa">
      <ol
        ref={listaRef}
        className="conversa__mensagens"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        onScroll={aoRolar}
      >
        {conversa.mensagens.map((mensagem) =>
          mensagem.autor === 'visitante' ? (
            <li key={mensagem.messageId} className="conversa__balao conversa__balao--visitante">
              <p className="conversa__texto">{mensagem.texto}</p>
              <div className="conversa__situacao">
                <span className={`conversa__estado conversa__estado--${mensagem.estado}`}>
                  {ROTULO_DO_ESTADO[mensagem.estado]}
                </span>
                {mensagem.estado === 'falhou' ? (
                  // Durante a espera de `muitas_tentativas` reenviar so
                  // estenderia o bloqueio; o botao volta quando a espera acaba.
                  <button
                    type="button"
                    disabled={espera !== null}
                    onClick={() => reenviar(mensagem.messageId, mensagem.texto)}
                  >
                    Reenviar
                  </button>
                ) : null}
              </div>
            </li>
          ) : (
            <li key={mensagem.chave} className="conversa__balao conversa__balao--agente">
              {mensagem.texto}
            </li>
          ),
        )}
      </ol>
      {espera ? (
        <p className="conversa__espera" role="status">
          {espera.mensagem}
        </p>
      ) : (
        <form className="conversa__formulario" onSubmit={aoEnviar}>
          <textarea
            value={rascunho}
            onChange={(evento) => setRascunho(evento.target.value)}
            onKeyDown={aoTeclar}
            maxLength={LIMITE_DE_CARACTERES}
            placeholder="Escreva sua mensagem"
            aria-label="Mensagem"
            rows={2}
          />
          <div className="conversa__rodape">
            <span className="conversa__contador">{`${rascunho.length}/${LIMITE_DE_CARACTERES}`}</span>
            <button type="submit">Enviar</button>
          </div>
        </form>
      )}
    </section>
  )
}

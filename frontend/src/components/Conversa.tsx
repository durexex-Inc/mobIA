'use client'

import {
  type FocusEvent,
  type FormEvent,
  type KeyboardEvent,
  type RefObject,
  useCallback,
  useEffect,
  useId,
  useReducer,
  useRef,
  useState,
} from 'react'

import { CabecalhoDoChat } from '@/components/CabecalhoDoChat'
import {
  CODIGO_OCIOSA,
  type Conexao,
  type EstadoDaMensagem,
  INICIAL,
  LIMITE_DE_CARACTERES,
  novoMessageId,
  PRAZO_DO_ACK_MS,
  reduzir,
} from '@/lib/conversa'
import { apagarSessao, armazemDoNavegador, gravarSessao, lerSessao } from '@/lib/sessaoGuardada'

const ROTULO_DO_ESTADO: Record<EstadoDaMensagem, string> = {
  enviando: 'Enviando…',
  recebida: 'Recebida',
  falhou: 'Não enviada',
}

// Quanto acima do fim a lista ainda conta como "no fim" para rolar sozinha.
const DISTANCIA_DO_FIM_PX = 40

/** Minimizado sem nenhum frame por este tempo, o socket dorme (TEC-347, D4). */
const PRAZO_DO_SONO_MS = 30 * 60 * 1000

const PERGUNTA_DE_ENCERRAR = 'Encerrar esta conversa? O histórico some desta tela.'

type Envio = { id: string; texto: string }

function frameDeMensagem({ id, texto }: Envio): string {
  return JSON.stringify({ tipo: 'mensagem', id, texto })
}

// O aviso do loader (D4). So o formato exato vale: `aberto` que nao e
// booleano -- `'false'`, por exemplo -- seria lido como verdadeiro.
function comoAvisoDeVisibilidade(dado: unknown): { aberto: boolean } | null {
  if (typeof dado !== 'object' || dado === null) {
    return null
  }
  const { tipo, aberto } = dado as Record<string, unknown>
  return tipo === 'mobia:visibilidade' && typeof aberto === 'boolean' ? { aberto } : null
}

/**
 * O botao "Opções da conversa" do cabecalho e o menu dele (D3). O menu so
 * tem "Encerrar conversa", e escolher nao encerra: pede a confirmacao, que
 * mora em `Conversa`. Escape fecha e devolve o foco ao botao; o foco sair
 * do menu (a visitante tocou no campo, por exemplo) tambem fecha, senao o
 * menu ficaria aberto por cima da lista. `botaoRef` vem de `Conversa`, que
 * devolve o foco ao botao quando a confirmacao e cancelada.
 */
function MenuDaConversa({
  aoEscolherEncerrar,
  botaoRef,
}: {
  aoEscolherEncerrar: () => void
  botaoRef: RefObject<HTMLButtonElement | null>
}) {
  const [aberto, setAberto] = useState(false)
  const idDoMenu = useId()
  const itemRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (aberto) {
      itemRef.current?.focus()
    }
  }, [aberto])

  function aoTeclar(evento: KeyboardEvent<HTMLDivElement>) {
    if (evento.key === 'Escape' && aberto) {
      evento.preventDefault()
      setAberto(false)
      botaoRef.current?.focus()
    }
  }

  // `relatedTarget` e quem recebe o foco; nulo quando o foco vai para lugar
  // nenhum. Foco que passa do item para o botao (ou o contrario) fica dentro.
  function aoPerderFoco(evento: FocusEvent<HTMLDivElement>) {
    if (aberto && !evento.currentTarget.contains(evento.relatedTarget as Node | null)) {
      setAberto(false)
    }
  }

  return (
    <div className="conversa__opcoes" onKeyDown={aoTeclar} onBlur={aoPerderFoco}>
      <button
        ref={botaoRef}
        type="button"
        className="conversa__botao-de-opcoes"
        aria-label="Opções da conversa"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? idDoMenu : undefined}
        onClick={() => setAberto((valor) => !valor)}
      >
        ⋯
      </button>
      {aberto ? (
        <ul id={idDoMenu} className="conversa__menu" role="menu" aria-label="Opções da conversa">
          <li role="none">
            <button
              ref={itemRef}
              type="button"
              role="menuitem"
              onClick={() => {
                setAberto(false)
                aoEscolherEncerrar()
              }}
            >
              Encerrar conversa
            </button>
          </li>
        </ul>
      ) : null}
    </div>
  )
}

/**
 * A conversa do chat embutido (TEC-346; retomada, encerramento e sono da
 * TEC-347): liga o redutor de `lib/conversa` (D3 da TEC-346) a um
 * `WebSocket` de verdade e desenha a tela da D5 da TEC-346, com o cabecalho. Todo o I/O mora aqui --
 * socket, timers do prazo do `ack` e do sono, `localStorage`, o aviso de
 * visibilidade do loader --; decidir o proximo estado e do redutor.
 *
 * **So o socket atual fala com a tela.** Cada listener confere
 * `socketRef.current === socket` antes de despachar: o socket de uma montagem
 * descartada (o StrictMode monta, desmonta e monta de novo), o de antes de
 * um reenvio ou o de antes de um encerramento ainda pode entregar `message`
 * e `close`, e um `close` atrasado marcaria como `falhou` o que o socket novo
 * esta enviando.
 *
 * **Mensagem que sai com o socket fechado espera o `open` na fila.** Enviar
 * ou reenviar sem socket aberto abre um novo (a menos que um ja esteja
 * conectando) e a mensagem sai logo depois do `ola`. Reenviar usa o mesmo
 * `messageId` (D3) -- o servidor deduplica dentro da sessao, e por isso a
 * reconexao retoma a sessao --, e despacha `reenviou`, nunca `enviou`, que
 * duplicaria o balao.
 *
 * **Toda conexao manda a sessao conhecida (TEC-347, D1 e D2).** A primeira
 * de cada montagem leva a que `lerSessao` achar valida no `localStorage` (30
 * dias desde a criacao), ou `null`; as seguintes (reenvio, envio com o
 * socket fechado, fim da espera, despertar do sono) levam a sessao
 * conhecida: a ultima que o servidor emitiu -- mesmo que o storage esteja
 * bloqueado --, ou, se a primeira conexao caiu antes do frame `sessao`, a
 * mesma lida do storage. O `historico` que o servidor
 * devolve ao retomar substitui as falas confirmadas da tela -- e assim que o
 * que o agente disse com o socket fechado aparece --, mantendo o mesmo balao
 * para o que ja estava nela. Gravar e so quando o servidor emite sessao
 * diferente da que este socket mandou no `ola`, isto e, quando cunhou uma
 * nova: retomar nao regrava, entao o prazo nao anda -- nem se outra aba
 * apagou a guardada no meio tempo. A reconexao depois de uma queda continua
 * manual (L5 da TEC-346) -- reconectar sozinho e da TEC-348. As reaberturas
 * automaticas sao o fim da espera de `muitas_tentativas` (D5 da TEC-346) e o
 * despertar do sono (abaixo).
 *
 * **Encerrar (D3) nao avisa o servidor.** Apaga a sessao guardada e a da
 * memoria, zera a tela e troca o socket por um que manda `ola` com `null`
 * -- menos durante a espera de `muitas_tentativas`: ai a conexao nova so
 * abre quando a espera acaba, como abriria de qualquer jeito.
 *
 * **Minimizado, o socket dorme (D4).** O loader avisa por `postMessage`
 * quando o painel abre e fecha; so vale o aviso do proprio pai. Com o
 * painel fechado, 30 minutos sem nenhum frame enviado ou recebido fecham o
 * socket no estado `adormecida`, que a tela nao mostra como falha. Abrir o
 * painel de novo reconecta com a sessao, e o `historico` repoe o que
 * faltou. Antes do primeiro aviso o painel conta como aberto.
 */
export function Conversa({ endereco, nome }: { endereco: string; nome: string | null }) {
  const [conversa, despachar] = useReducer(reduzir, INICIAL)
  const [rascunho, setRascunho] = useState('')
  const [confirmando, setConfirmando] = useState(false)
  const socketRef = useRef<WebSocket | null>(null)
  // Mensagens que esperam o `open` do socket atual para sair.
  const filaRef = useRef<Envio[]>([])
  const prazosRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  // A sessao que vai no `ola` da proxima conexao. A montagem a le do
  // storage (no efeito, nao no render: ler o storage e I/O); depois, so o
  // frame `sessao` a atualiza, e so o encerramento a zera.
  const sessaoRef = useRef<string | null>(null)
  const sessaoLidaRef = useRef(false)
  // A sessao que o `ola` do socket atual levou: o frame `sessao` so e
  // gravado quando difere dela.
  const sessaoDoOlaRef = useRef<string | null>(null)
  // Visibilidade do painel segundo o ultimo aviso do loader, e o timer do sono.
  const abertoRef = useRef(true)
  const sonoRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // A conexao do ultimo render, para o listener do aviso -- que nao
  // reinscreve a cada render.
  const conexaoRef = useRef<Conexao>(INICIAL.conexao)

  // Chamado a cada frame que entra ou sai: com o painel fechado, (re)comeca
  // o prazo do sono; com o painel aberto, so cancela o que houver.
  const reagendarSono = useCallback(() => {
    if (sonoRef.current !== null) {
      clearTimeout(sonoRef.current)
      sonoRef.current = null
    }
    if (abertoRef.current) {
      return
    }
    sonoRef.current = setTimeout(() => {
      sonoRef.current = null
      const socket = socketRef.current
      // Socket ja fechado (queda, `muitas_tentativas`) nao dorme: a tela ja
      // diz o que houve, e `adormecida` apagaria a espera ou reconectaria
      // sozinho ao abrir o painel -- o que e da TEC-348.
      if (!socket || socket.readyState === WebSocket.CLOSING || socket.readyState === WebSocket.CLOSED) {
        return
      }
      despachar({ tipo: 'adormeceu' })
      socket.close()
    }, PRAZO_DO_SONO_MS)
  }, [])

  const conectar = useCallback(() => {
    const socket = new WebSocket(endereco)
    const anterior = socketRef.current
    socketRef.current = socket
    anterior?.close()
    const atual = () => socketRef.current === socket
    const mandar = (dado: string) => {
      socket.send(dado)
      reagendarSono()
    }

    socket.addEventListener('open', () => {
      if (!atual()) {
        return
      }
      despachar({ tipo: 'abriu' })
      sessaoDoOlaRef.current = sessaoRef.current
      mandar(JSON.stringify({ tipo: 'ola', sessao: sessaoRef.current }))
      for (const envio of filaRef.current.splice(0)) {
        mandar(frameDeMensagem(envio))
      }
    })
    socket.addEventListener('message', (evento: MessageEvent) => {
      if (atual() && typeof evento.data === 'string') {
        reagendarSono()
        despachar({ tipo: 'frame', bruto: evento.data })
      }
    })
    socket.addEventListener('close', (evento: CloseEvent) => {
      if (!atual()) {
        return
      }
      // O servidor fechou por ociosidade (TEC-366): o mesmo sono de D4, e nao
      // uma queda. `adormeceu` antes de `fechou`, porque o redutor preserva
      // `adormecida` no `fechou` -- e e desse estado que reabrir o painel
      // reconecta.
      if (evento.code === CODIGO_OCIOSA) {
        despachar({ tipo: 'adormeceu' })
      }
      // O que estava na fila nunca saiu; o redutor ja o marca como `falhou`.
      filaRef.current = []
      despachar({ tipo: 'fechou' })
    })
  }, [endereco, reagendarSono])

  const limparPrazos = useCallback(() => {
    const prazos = prazosRef.current
    for (const prazo of prazos.values()) {
      clearTimeout(prazo)
    }
    prazos.clear()
  }, [])

  useEffect(() => {
    // Uma vez por componente, e nunca de novo: o StrictMode repete este
    // efeito, e reler depois de um encerramento traria de volta o que ele
    // apagou se o storage estivesse bloqueado para `removeItem`.
    if (!sessaoLidaRef.current) {
      sessaoLidaRef.current = true
      sessaoRef.current = lerSessao(armazemDoNavegador(), Date.now())
    }
    conectar()
    return () => {
      const socket = socketRef.current
      socketRef.current = null
      socket?.close()
      filaRef.current = []
      limparPrazos()
    }
  }, [conectar, limparPrazos])

  useEffect(() => {
    conexaoRef.current = conversa.conexao
  }, [conversa.conexao])

  useEffect(() => {
    function aoReceberAviso(evento: MessageEvent) {
      if (evento.source !== window.parent) {
        return
      }
      const aviso = comoAvisoDeVisibilidade(evento.data)
      if (!aviso) {
        return
      }
      abertoRef.current = aviso.aberto
      reagendarSono()
      if (aviso.aberto && conexaoRef.current.tipo === 'adormecida') {
        despachar({ tipo: 'reabrindo' })
        conectar()
      }
    }
    window.addEventListener('message', aoReceberAviso)
    return () => {
      window.removeEventListener('message', aoReceberAviso)
      if (sonoRef.current !== null) {
        clearTimeout(sonoRef.current)
        sonoRef.current = null
      }
    }
  }, [conectar, reagendarSono])

  // Fim da espera de `muitas_tentativas`: `reabrindo` tira a conexao de
  // `aguardando` e um socket novo abre. Sem o `reabrindo`, uma queda desse
  // socket antes do `open` manteria a espera -- o mesmo objeto, sem timer
  // novo -- e o chat ficaria preso nela. `espera` e o proprio objeto da
  // conexao, que o redutor preserva enquanto nada muda -- inclusive no
  // `encerrou` -- entao o timer nao reinicia a cada balao que chega nem
  // quando a visitante encerra no meio da espera.
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
  //
  // "A mensagem nova e dela" quer dizer: a ultima da lista trocou, e a nova
  // ultima e um envio da visitante ainda `enviando`. O `historico` refaz a
  // lista sem ser envio de ninguem: as falas dela vindas dele sao
  // `recebida`, e a pendente que ele mantem no fim continua com o mesmo id
  // -- entao nenhum dos dois casos puxa para o fim, e so a regra do "perto
  // do fim" vale.
  const listaRef = useRef<HTMLOListElement | null>(null)
  const pertoDoFimRef = useRef(true)
  const totalDeMensagens = conversa.mensagens.length
  const ultima = conversa.mensagens.at(-1)
  const chaveDaUltima = ultima ? (ultima.autor === 'visitante' ? ultima.messageId : ultima.chave) : null
  const ultimaEEnvioDaVisitante = ultima?.autor === 'visitante' && ultima.estado === 'enviando'
  const chaveAnteriorRef = useRef<string | null>(null)
  useEffect(() => {
    const lista = listaRef.current
    const enviouAgora = ultimaEEnvioDaVisitante && chaveDaUltima !== chaveAnteriorRef.current
    chaveAnteriorRef.current = chaveDaUltima
    if (totalDeMensagens > 0 && lista && (pertoDoFimRef.current || enviouAgora)) {
      lista.scrollTop = lista.scrollHeight
      pertoDoFimRef.current = true
    }
  }, [totalDeMensagens, chaveDaUltima, ultimaEEnvioDaVisitante])

  function aoRolar() {
    const lista = listaRef.current
    if (lista) {
      pertoDoFimRef.current = lista.scrollHeight - lista.scrollTop - lista.clientHeight <= DISTANCIA_DO_FIM_PX
    }
  }

  // `null` nao vem daqui: o redutor so volta a `null` no `encerrou`, e o
  // encerramento zera `sessaoRef` ele mesmo. Copiar o `null` inicial pisaria
  // na sessao que a montagem leu do storage.
  //
  // Grava so a sessao que o servidor cunhou -- a que difere da que o `ola`
  // levou. Comparar com o storage nao basta: se outra aba o apagou entre o
  // `ola` e o frame, a sessao retomada seria regravada com `criadaEm` de
  // agora, e o prazo de 30 dias recomecaria (D1).
  useEffect(() => {
    if (!conversa.sessao) {
      return
    }
    sessaoRef.current = conversa.sessao
    if (conversa.sessao !== sessaoDoOlaRef.current) {
      gravarSessao(armazemDoNavegador(), conversa.sessao, Date.now())
    }
  }, [conversa.sessao])

  // Prazo de mensagem que nao esta mais `enviando` (ack, erro, queda) -- ou
  // que saiu da lista -- nao tem mais o que marcar. O `historico` nao tira
  // pendente nenhuma: ela continua no fim, com o mesmo id e o mesmo estado,
  // entao o prazo dela segue valendo. E um `historico` igual a tela devolve
  // a mesma lista, e este efeito nem roda.
  useEffect(() => {
    const prazos = prazosRef.current
    const enviando = new Set<string>()
    for (const mensagem of conversa.mensagens) {
      if (mensagem.autor === 'visitante' && mensagem.estado === 'enviando') {
        enviando.add(mensagem.messageId)
      }
    }
    for (const [id, prazo] of prazos) {
      if (!enviando.has(id)) {
        clearTimeout(prazo)
        prazos.delete(id)
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
      reagendarSono()
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

  function encerrar() {
    setConfirmando(false)
    apagarSessao(armazemDoNavegador())
    sessaoRef.current = null
    const aguardando = conversa.conexao.tipo === 'aguardando'
    despachar({ tipo: 'encerrou' })
    // O socket sai de `socketRef` antes de fechar: o `close` dele chega
    // depois, ja como socket antigo, e nao marca nada na tela nova.
    const socket = socketRef.current
    socketRef.current = null
    socket?.close()
    filaRef.current = []
    limparPrazos()
    pertoDoFimRef.current = true
    // O foco vai para onde a conversa nova comeca: o campo. Durante a espera
    // de `muitas_tentativas` nao ha campo, e ele volta ao botao do menu.
    if (aguardando) {
      botaoDeOpcoesRef.current?.focus()
    } else {
      campoRef.current?.focus()
      conectar()
    }
  }

  // A confirmacao sai sem efeito -- "Cancelar" ou Escape -- e o foco volta
  // ao botao que a abriu, e nao ao `body`.
  function cancelarEncerramento() {
    setConfirmando(false)
    botaoDeOpcoesRef.current?.focus()
  }

  function aoTeclarNaConfirmacao(evento: KeyboardEvent<HTMLDivElement>) {
    if (evento.key === 'Escape') {
      evento.preventDefault()
      cancelarEncerramento()
    }
  }

  const botaoDeOpcoesRef = useRef<HTMLButtonElement | null>(null)
  const campoRef = useRef<HTMLTextAreaElement | null>(null)
  const cancelarRef = useRef<HTMLButtonElement | null>(null)
  const idDaPergunta = useId()
  useEffect(() => {
    if (confirmando) {
      cancelarRef.current?.focus()
    }
  }, [confirmando])

  return (
    <>
      <CabecalhoDoChat nome={nome}>
        <MenuDaConversa botaoRef={botaoDeOpcoesRef} aoEscolherEncerrar={() => setConfirmando(true)} />
      </CabecalhoDoChat>
      <section className="conversa">
        {confirmando ? (
          <div
            className="conversa__confirmacao"
            role="alertdialog"
            aria-labelledby={idDaPergunta}
            onKeyDown={aoTeclarNaConfirmacao}
          >
            <p id={idDaPergunta}>{PERGUNTA_DE_ENCERRAR}</p>
            <div className="conversa__confirmacao-acoes">
              <button type="button" className="conversa__confirmar" onClick={encerrar}>
                Encerrar
              </button>
              <button ref={cancelarRef} type="button" onClick={cancelarEncerramento}>
                Cancelar
              </button>
            </div>
          </div>
        ) : null}
        {/* `log` nao e papel permitido num `<ol>`, e tira dele a semantica de
            lista: o papel fica no involucro, e a lista continua lista.
            `additions` anuncia so os baloes novos, nao a troca de estado --
            e o `historico` de cada reconexao mantem o mesmo objeto, e a mesma
            chave, para o balao que ja estava na tela (`aplicarHistorico`):
            chave nova remontaria o `<li>`, e ele seria anunciado de novo. */}
        <div className="conversa__registro" role="log" aria-live="polite" aria-relevant="additions">
          <ol ref={listaRef} className="conversa__mensagens" onScroll={aoRolar}>
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
        </div>
        {espera ? (
          <p className="conversa__espera" role="status">
            {espera.mensagem}
          </p>
        ) : (
          <form className="conversa__formulario" onSubmit={aoEnviar}>
            <textarea
              ref={campoRef}
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
    </>
  )
}

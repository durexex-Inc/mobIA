/**
 * O estado da conversa do chat embutido (TEC-346, D3; `historico`,
 * `encerrou` e `adormeceu` da TEC-347, D2 e D4): mensagens em ordem e o
 * estado da conexao, atualizados por um redutor puro -- sem I/O, sem relogio,
 * sem `localStorage`. Quem abre o socket, dispara os timers e grava a sessao
 * e `components/Conversa.tsx`; este modulo so decide o proximo estado.
 *
 * `reduzir` devolve a MESMA referencia de `Conversa` quando um evento nao
 * muda nada -- frame que nao e JSON, `tipo` desconhecido, `ack` que nao acha
 * mensagem pendente, e assim por diante. Isso deixa quem usa `useReducer`
 * evitar renderizacao a toa, e os testes afirmam a referencia, nao so o
 * conteudo.
 *
 * **`historico` e a verdade do servidor (D2):** troca as mensagens
 * confirmadas (recebida da visitante, baloes do agente) pelas que o servidor
 * mandou, e mantem no fim, na ordem, as pendentes da visitante que ainda nao
 * foram confirmadas.
 *
 * **Frames do servidor que esta card ainda ignora, e quem trata cada um:**
 * `digitando` (TEC-351), `imagem` (TEC-349) e `consentimento_registrado`
 * (TEC-352). `imovel` sem `texto` tambem fica sem balao aqui -- o card do
 * imovel e da TEC-349.
 */

export type EstadoDaMensagem = 'enviando' | 'recebida' | 'falhou'

export type Mensagem =
  | { autor: 'visitante'; messageId: string; texto: string; estado: EstadoDaMensagem }
  | { autor: 'agente'; chave: string; texto: string }

export type Conexao =
  | { tipo: 'conectando' }
  | { tipo: 'aberta' }
  | { tipo: 'fechada' }
  | { tipo: 'aguardando'; mensagem: string; segundos: number }
  // Minimizado sem atividade por 30 min (D4): o socket fechou de proposito,
  // nao e falha nenhuma.
  | { tipo: 'adormecida' }

export type Conversa = { mensagens: Mensagem[]; conexao: Conexao; sessao: string | null }

export type Evento =
  | { tipo: 'abriu' }
  | { tipo: 'enviou'; messageId: string; texto: string }
  | { tipo: 'frame'; bruto: string }
  | { tipo: 'fechou' }
  | { tipo: 'prazoDoAck'; messageId: string }
  | { tipo: 'reenviou'; messageId: string }
  // A espera de `muitas_tentativas` acabou e um socket novo esta abrindo.
  | { tipo: 'reabrindo' }
  // A visitante confirmou "Encerrar conversa" no menu (D3).
  | { tipo: 'encerrou' }
  // 30 min minimizado sem atividade venceram (D4).
  | { tipo: 'adormeceu' }

/** Teto do campo de texto (D5). A rede continua com o teto de 4096 do servidor. */
export const LIMITE_DE_CARACTERES = 1000

/** Quanto tempo sem `ack` marca uma mensagem enviada como `falhou` (D3). */
export const PRAZO_DO_ACK_MS = 10_000

export const INICIAL: Conversa = { mensagens: [], conexao: { tipo: 'conectando' }, sessao: null }

// Um frame decodificado, antes de sabermos se o `tipo` e um dos que esta
// card trata. `unknown` nos campos: o valor vem da rede.
type FrameBruto = Record<string, unknown>

function comoObjeto(valor: unknown): FrameBruto | null {
  return typeof valor === 'object' && valor !== null && !Array.isArray(valor) ? (valor as FrameBruto) : null
}

function segundosValidos(valor: unknown): valor is number {
  return typeof valor === 'number' && Number.isInteger(valor) && valor >= 1
}

function adicionarBalaoDoAgente(estado: Conversa, texto: string): Conversa {
  // A chave e o total de mensagens ANTES de acrescentar esta -- estavel
  // porque mensagem nunca e removida da lista, so acrescentada.
  const chave = `agente-${estado.mensagens.length}`
  return { ...estado, mensagens: [...estado.mensagens, { autor: 'agente', chave, texto }] }
}

/**
 * Aplica `novoEstado` na mensagem da visitante de `messageId` cujo estado
 * atual satisfaz `condicao`. Devolve o MESMO array quando a mensagem nao
 * existe ou a condicao nao bate -- e o que faz `reduzir` devolver a mesma
 * `Conversa` nesses casos.
 */
function atualizarMensagemDaVisitante(
  mensagens: Mensagem[],
  messageId: string,
  condicao: (estado: EstadoDaMensagem) => boolean,
  novoEstado: EstadoDaMensagem,
): Mensagem[] {
  let mudou = false
  const resultado = mensagens.map((mensagem) => {
    if (!mudou && mensagem.autor === 'visitante' && mensagem.messageId === messageId && condicao(mensagem.estado)) {
      mudou = true
      return { ...mensagem, estado: novoEstado }
    }
    return mensagem
  })
  return mudou ? resultado : mensagens
}

function marcarFalhouSeEnviando(estado: Conversa, messageId: string): Conversa {
  const mensagens = atualizarMensagemDaVisitante(estado.mensagens, messageId, (e) => e === 'enviando', 'falhou')
  return mensagens === estado.mensagens ? estado : { ...estado, mensagens }
}

function marcarEnviando(estado: Conversa, messageId: string): Conversa {
  const mensagens = atualizarMensagemDaVisitante(estado.mensagens, messageId, (e) => e === 'falhou', 'enviando')
  return mensagens === estado.mensagens ? estado : { ...estado, mensagens }
}

function aplicarSessao(estado: Conversa, dado: FrameBruto): Conversa {
  return typeof dado.sessao === 'string' && dado.sessao !== '' ? { ...estado, sessao: dado.sessao } : estado
}

function aplicarMensagemDoAgente(estado: Conversa, dado: FrameBruto): Conversa {
  return typeof dado.texto === 'string' ? adicionarBalaoDoAgente(estado, dado.texto) : estado
}

function aplicarImovel(estado: Conversa, dado: FrameBruto): Conversa {
  return typeof dado.texto === 'string' && dado.texto !== '' ? adicionarBalaoDoAgente(estado, dado.texto) : estado
}

function aplicarAck(estado: Conversa, dado: FrameBruto): Conversa {
  if (typeof dado.messageId !== 'string') {
    return estado
  }
  // 'recebida' fica de fora da condicao: um segundo ack para a mesma
  // mensagem (duas abas, ou o mesmo id reenviado) nao muda nada.
  const mensagens = atualizarMensagemDaVisitante(estado.mensagens, dado.messageId, (e) => e !== 'recebida', 'recebida')
  return mensagens === estado.mensagens ? estado : { ...estado, mensagens }
}

function aplicarMuitasTentativas(estado: Conversa, dado: FrameBruto): Conversa {
  const mensagem = typeof dado.mensagem === 'string' ? dado.mensagem : ''
  const segundos = segundosValidos(dado.aguardeSegundos) ? dado.aguardeSegundos : 60
  return { ...estado, conexao: { tipo: 'aguardando', mensagem, segundos } }
}

function mensagemDoHistorico(item: unknown, indiceNoFrame: number, posicaoNaLista: number): Mensagem | null {
  const objeto = comoObjeto(item)
  if (!objeto || typeof objeto.texto !== 'string' || objeto.texto === '') {
    return null
  }
  if (objeto.papel === 'lead') {
    return { autor: 'visitante', messageId: `historico-${indiceNoFrame}`, texto: objeto.texto, estado: 'recebida' }
  }
  if (objeto.papel === 'agente') {
    // `posicaoNaLista` e o mesmo esquema de `adicionarBalaoDoAgente`: o
    // comprimento da lista MONTADA antes desta mensagem -- so os itens
    // validos, sem contar as pendentes que entram depois. A proxima fala do
    // agente, ja fora do historico, usa `estado.mensagens.length` (o
    // comprimento final), que fica 1 acima da maior posicao usada aqui --
    // entao a chave continua unica.
    return { autor: 'agente', chave: `agente-${posicaoNaLista}`, texto: objeto.texto }
  }
  return null
}

/**
 * `historico` e a verdade do servidor (D2): a nova lista de mensagens e o
 * que o servidor mandou, seguido das pendentes da visitante (`enviando` ou
 * `falhou`) na ordem em que estavam -- elas ainda nao foram confirmadas,
 * entao o historico nao as contem. As `recebida` locais e os baloes do
 * agente em memoria saem: o historico os substitui.
 */
function aplicarHistorico(estado: Conversa, dado: FrameBruto): Conversa {
  if (!Array.isArray(dado.mensagens)) {
    return estado
  }
  const doHistorico: Mensagem[] = []
  dado.mensagens.forEach((item, indice) => {
    const mensagem = mensagemDoHistorico(item, indice, doHistorico.length)
    if (mensagem) {
      doHistorico.push(mensagem)
    }
  })
  const pendentes = estado.mensagens.filter(
    (mensagem) => mensagem.autor === 'visitante' && (mensagem.estado === 'enviando' || mensagem.estado === 'falhou'),
  )
  return { ...estado, mensagens: [...doHistorico, ...pendentes] }
}

function aplicarErro(estado: Conversa, dado: FrameBruto): Conversa {
  if (dado.codigo === 'muitas_tentativas') {
    return aplicarMuitasTentativas(estado, dado)
  }
  return typeof dado.messageId === 'string' ? marcarFalhouSeEnviando(estado, dado.messageId) : estado
}

function aplicarFrame(estado: Conversa, bruto: string): Conversa {
  let dado: unknown
  try {
    dado = JSON.parse(bruto)
  } catch {
    return estado
  }
  const objeto = comoObjeto(dado)
  if (!objeto || typeof objeto.tipo !== 'string') {
    return estado
  }
  switch (objeto.tipo) {
    case 'sessao':
      return aplicarSessao(estado, objeto)
    case 'mensagem':
      return aplicarMensagemDoAgente(estado, objeto)
    case 'imovel':
      return aplicarImovel(estado, objeto)
    case 'ack':
      return aplicarAck(estado, objeto)
    case 'erro':
      return aplicarErro(estado, objeto)
    case 'historico':
      return aplicarHistorico(estado, objeto)
    default:
      // digitando, imagem, consentimento_registrado, e qualquer tipo que o
      // servidor venha a mandar e esta tela ainda nao conheca.
      return estado
  }
}

function marcarTodasEnviandoComoFalhou(mensagens: Mensagem[]): Mensagem[] {
  let mudou = false
  const resultado = mensagens.map((mensagem) => {
    if (mensagem.autor === 'visitante' && mensagem.estado === 'enviando') {
      mudou = true
      return { ...mensagem, estado: 'falhou' as const }
    }
    return mensagem
  })
  return mudou ? resultado : mensagens
}

function aplicarFechou(estado: Conversa): Conversa {
  const mensagens = marcarTodasEnviandoComoFalhou(estado.mensagens)
  // 'aguardando' e 'adormecida' sao os dois estados que uma queda de socket
  // nao deve pisar: a espera de 'muitas_tentativas' e a informacao relevante
  // na primeira -- 'fechada' pisaria em cima da contagem regressiva --, e
  // 'adormecida' (D4) ja e um fechamento deliberado, que pode receber outro
  // 'fechou' do mesmo socket sem virar 'fechada'. Quando a espera acaba,
  // `reabrindo` a troca por 'conectando', e uma queda do socket novo antes
  // do `open` vira 'fechada' normalmente.
  const conexao: Conexao =
    estado.conexao.tipo === 'aguardando' || estado.conexao.tipo === 'adormecida'
      ? estado.conexao
      : { tipo: 'fechada' }
  return mensagens === estado.mensagens && conexao === estado.conexao ? estado : { ...estado, mensagens, conexao }
}

export function reduzir(estado: Conversa, evento: Evento): Conversa {
  switch (evento.tipo) {
    case 'abriu':
      return estado.conexao.tipo === 'aberta' ? estado : { ...estado, conexao: { tipo: 'aberta' } }
    case 'enviou':
      return {
        ...estado,
        mensagens: [
          ...estado.mensagens,
          { autor: 'visitante', messageId: evento.messageId, texto: evento.texto, estado: 'enviando' },
        ],
      }
    case 'frame':
      return aplicarFrame(estado, evento.bruto)
    case 'fechou':
      return aplicarFechou(estado)
    case 'prazoDoAck':
      return marcarFalhouSeEnviando(estado, evento.messageId)
    case 'reenviou':
      return marcarEnviando(estado, evento.messageId)
    case 'reabrindo':
      return estado.conexao.tipo === 'conectando' ? estado : { ...estado, conexao: { tipo: 'conectando' } }
    case 'encerrou':
      // D3: a tela zera e a sessao some. A espera de 'muitas_tentativas'
      // continua valendo (Review Focus 5) -- a nova conexao nao pode furar a
      // fila dela; fora disso a proxima conexao comeca 'conectando'.
      return { ...INICIAL, conexao: estado.conexao.tipo === 'aguardando' ? estado.conexao : { tipo: 'conectando' } }
    case 'adormeceu':
      return estado.conexao.tipo === 'adormecida' ? estado : { ...estado, conexao: { tipo: 'adormecida' } }
  }
}

function uuidV4DeReserva(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  // RFC 4122: versao 4 no nibble alto do byte 6, variante 10xx no byte 8.
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** O `messageId` de uma mensagem da visitante -- UUIDv4, com reserva sem `crypto.randomUUID`. */
export function novoMessageId(): string {
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return uuidV4DeReserva()
}

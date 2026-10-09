/**
 * Tipos e regras puras da tela de pedidos de interesse (TEC-404, D5 e D9 do
 * desenho).
 *
 * Sem `server-only`: nada aqui le segredo, e o componente de cliente usa as
 * mesmas funcoes que a pagina. **A regra de revelacao daqui serve so para
 * MOSTRAR o botao**: quem decide se o corretor pode ver o dado e o backend
 * (`interesses.py::revelar`), que recusa o que esta funcao nao esconder.
 */

export type EstadoDosPedidos = 'pendentes' | 'todos'

export type AtendimentoDoPedido = {
  id: string
  status: 'PENDENTE' | 'ACEITO' | 'ESCALADO' | 'CONCLUIDO'
  corretor: { id: string; nome: string } | null
  notificadoEm: string | null
  semCorretor: boolean
}

export type PedidoDeInteresse = {
  id: string
  criadoEm: string
  imovel: { id: string; codigo: string; titulo: string }
  nome: string | null
  telefoneMascarado: string | null
  emailMascarado: string | null
  leadId: string
  atendimento: AtendimentoDoPedido | null
}

export type PaginaDePedidos = { itens: PedidoDeInteresse[]; proximoCursor: string | null }

/** O estado da URL; qualquer valor que nao seja `todos` cai em `pendentes`. */
export function estadoDaUrl(valor: string | string[] | undefined): EstadoDosPedidos {
  const primeiro = Array.isArray(valor) ? valor[0] : valor
  return primeiro === 'todos' ? 'todos' : 'pendentes'
}

/** A URL da tela: `pendentes` sem cursor e a forma limpa, sem query. */
export function urlDosPedidos(estado: EstadoDosPedidos, cursor?: string): string {
  const parametros = new URLSearchParams()
  if (estado !== 'pendentes') {
    parametros.set('estado', estado)
  }
  if (cursor) {
    parametros.set('cursor', cursor)
  }
  const consulta = parametros.toString()
  return consulta ? `/interesses?${consulta}` : '/interesses'
}

const ROTULOS: Record<AtendimentoDoPedido['status'], string> = {
  PENDENTE: 'Pendente',
  ACEITO: 'Assumido',
  ESCALADO: 'Escalado',
  CONCLUIDO: 'Concluído',
}

/** `semCorretor` vence o status: sem dono, o status nao diz a quem cobrar. */
export function rotuloDoAtendimento(atendimento: AtendimentoDoPedido | null): string {
  if (atendimento === null) {
    return 'Sem atendimento'
  }
  if (atendimento.semCorretor) {
    return 'Sem corretor'
  }
  return ROTULOS[atendimento.status]
}

/** Assumir e do corretor dono do atendimento, enquanto ele esta pendente ou escalado. */
export function podeAssumir(
  atendimento: AtendimentoDoPedido | null,
  corretorId: string | null,
): boolean {
  return (
    corretorId !== null &&
    atendimento?.corretor?.id === corretorId &&
    (atendimento.status === 'PENDENTE' || atendimento.status === 'ESCALADO')
  )
}

export function podeRevelarPedido(
  atendimento: AtendimentoDoPedido | null,
  quem: { permissoes: ReadonlySet<string>; corretorId: string | null },
): boolean {
  return (
    quem.permissoes.has('VER_DADOS_COMPLETOS') ||
    (quem.corretorId !== null && atendimento?.corretor?.id === quem.corretorId)
  )
}

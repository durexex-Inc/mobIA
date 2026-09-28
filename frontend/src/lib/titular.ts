/**
 * A fila de pedidos do titular (TEC-340): o formato de
 * `GET /api/v1/titular/solicitacoes` (`src/mobia/api/routes/titular.py`) e a
 * conta do prazo restante. Puro: recebe `agora`, nao le relogio.
 */

export type PedidoDoTitular = {
  id: string
  tipo: string
  origem: string
  status: string
  recebidaEm: string
  prazoEm: string
  atendidaEm: string | null
  motivoDaRecusa: string | null
  leadId: string | null
}

/** Com este tanto de dias ou menos, o pedido fica destacado (regra da card). */
export const DIAS_DO_DESTAQUE = 3

// O fuso unico da POC -- o mesmo `settings.fuso_de_envio` do backend.
const FUSO = 'America/Sao_Paulo'

const DIA_NO_FUSO = new Intl.DateTimeFormat('en-CA', {
  timeZone: FUSO,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

const DATA = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeZone: FUSO })

/** O dia de calendario de `instante` em Sao Paulo, como numero de dias desde 1970. */
function diaEmSaoPaulo(instante: Date): number {
  const [ano, mes, dia] = DIA_NO_FUSO.format(instante).split('-').map(Number)
  return Date.UTC(ano, mes - 1, dia) / 86_400_000
}

/**
 * Dias de calendario do dia de hoje ate o dia do prazo, os dois em Sao Paulo
 * (D3 do desenho). Negativo quando o prazo ja passou. Pela data, e nao pelas
 * horas: aberto ha 2 dias da 13 a qualquer hora do dia, que e o que a pessoa
 * le num prazo.
 */
export function diasRestantes(prazoEm: string, agora: Date): number {
  return diaEmSaoPaulo(new Date(prazoEm)) - diaEmSaoPaulo(agora)
}

/** "13 dias", "1 dia", "Vence hoje", "Vencido há 2 dias". */
export function textoDoPrazo(restante: number): string {
  if (restante === 0) {
    return 'Vence hoje'
  }
  if (restante < 0) {
    const atraso = -restante
    return `Vencido há ${atraso} ${atraso === 1 ? 'dia' : 'dias'}`
  }
  return `${restante} ${restante === 1 ? 'dia' : 'dias'}`
}

/** Com 3 dias ou menos -- inclusive vencido -- o pedido e destacado. */
export function destacado(restante: number): boolean {
  return restante <= DIAS_DO_DESTAQUE
}

/** A data de abertura, `dd/mm/aaaa` em Sao Paulo. */
export function dataLegivel(instante: string): string {
  return DATA.format(new Date(instante))
}

const TIPOS: Record<string, string> = {
  ACESSO: 'Acesso aos dados',
  ELIMINACAO: 'Eliminação dos dados',
}

const ORIGENS: Record<string, string> = {
  WHATSAPP: 'WhatsApp',
  ADMIN: 'Administrativo',
  RETENCAO: 'Retenção',
}

// Valor desconhecido aparece como veio, pela regra de `nomeDoPapel`: e
// anomalia, e o valor cru e a pista.
export function tipoLegivel(tipo: string): string {
  return TIPOS[tipo] ?? tipo
}

export function origemLegivel(origem: string): string {
  return ORIGENS[origem] ?? origem
}

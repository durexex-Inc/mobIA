/**
 * A transcricao do lead, sem I/O (TEC-324).
 *
 * **Modulo puro de proposito**: `components/Transcricao.tsx` e componente de
 * cliente, e nada que ele importe pode arrastar `server-only`. A primeira
 * pagina vem de `lib/servidor/leads.ts`; as anteriores, do proxy `/bff/*`.
 */

/** Uma fala de `GET /api/v1/leads/{leadId}/mensagens` (D5 da TEC-193). */
export type Fala = {
  id: string
  autor: string
  tipo: string
  conteudo: string | null
  retida: boolean
  em: string
}

/**
 * Uma pagina da transcricao. `cursorPosterior` (TEC-327) e o ponto de partida
 * do proximo poll: a fala mais recente da pagina. O servidor devolve o
 * proximo em toda resposta, e a tela nunca monta um cursor.
 */
export type PaginaDaTranscricao = {
  itens: Fala[]
  cursorAnterior: string | null
  cursorPosterior?: string | null
}

/** O intervalo do polling da conversa assumida (RN-FE-09.4). */
export const INTERVALO_DO_POLLING_MS = 5_000

export type Lado = 'lead' | 'equipe' | 'sistema'

/**
 * "Assistente", e nao "Agente": e o nome que o resumo ja usa ("Gerado pelo
 * assistente", TEC-323). Autor desconhecido aparece como veio.
 */
const ROTULOS: Record<string, string> = {
  LEAD: 'Lead',
  AGENTE: 'Assistente',
  CORRETOR: 'Corretor',
  SISTEMA: 'Sistema',
}

export function rotuloDoAutor(autor: string): string {
  return ROTULOS[autor] ?? autor
}

/**
 * O lado da bolha. **Enfeite por cima do rotulo, nunca no lugar dele** (D4):
 * o rotulo textual e o que identifica o autor sem depender de cor nem de
 * posicao.
 */
export function ladoDoAutor(autor: string): Lado {
  if (autor === 'LEAD') {
    return 'lead'
  }
  if (autor === 'AGENTE' || autor === 'CORRETOR') {
    return 'equipe'
  }
  return 'sistema'
}

const SEM_TEXTO: Record<string, string> = {
  AUDIO: 'Áudio sem texto',
  IMAGEM: 'Imagem sem texto',
  DOCUMENTO: 'Documento sem texto',
  DESCONHECIDO: 'Mídia sem texto',
}

/**
 * O que a bolha mostra.
 *
 * A fala retida chega so para ADMIN, e sem conteudo -- quem filtra e o
 * backend. **Mesmo que um conteudo viesse, ele nao seria mostrado**: a
 * checagem de `retida` vem primeiro, e a tela nao depende de o backend nunca
 * errar. Sem conteudo, a bolha diz o tipo: a rota nao entrega midia (L3 da
 * TEC-193), e uma bolha vazia pareceria defeito.
 */
export function textoDaFala(fala: Pick<Fala, 'retida' | 'conteudo' | 'tipo'>): string {
  if (fala.retida) {
    return 'Mensagem retida pela moderação'
  }
  if (fala.conteudo) {
    return fala.conteudo
  }
  return SEM_TEXTO[fala.tipo] ?? 'Mensagem sem texto'
}

/**
 * Onde buscar as falas NOVAS, pelo proxy (TEC-327, D1). O backend so grava o
 * acesso na trilha quando a resposta traz fala.
 */
export function urlDasPosteriores(leadId: string, cursor: string): string {
  return `/bff/api/v1/leads/${encodeURIComponent(leadId)}/mensagens?depois=${encodeURIComponent(cursor)}`
}

/** Onde buscar as falas anteriores: pelo proxy, que poe o JWT da sessao (D2). */
export function urlDasAnteriores(leadId: string, cursor: string): string {
  return `/bff/api/v1/leads/${encodeURIComponent(leadId)}/mensagens?cursor=${encodeURIComponent(cursor)}`
}

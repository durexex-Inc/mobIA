/**
 * A resposta do corretor, sem I/O (TEC-328).
 *
 * O limite, o contador, a janela de 24 h e a leitura das recusas moram aqui
 * pela razao de `lib/qualificacao.ts`: sao regra, e se testam sem montar
 * componente. Quem envia e `components/RespostaDoCorretor.tsx`.
 */

/** O limite da tela (RN-FE-09.3). A API aceita ate 4096, o teto da Meta. */
export const LIMITE_DA_RESPOSTA = 1000

/**
 * A janela de servico da Meta, em milissegundos. E a `JANELA_DE_SERVICO` de
 * `outbound/janela.py`, escrita de novo aqui por uma razao so: a fala nova do
 * lead que chega pelo polling reabre a janela, e reler o detalhe para saber
 * disso gravaria um acesso na trilha (D2 do desenho). Um teste do lado Python
 * (`tests/unit/test_vocabulario_da_tela.py`) reprova se os dois divergirem.
 */
export const JANELA_DE_SERVICO_MS = 86_400_000

export function contador(texto: string): { usados: number; excesso: number } {
  const usados = texto.length
  return { usados, excesso: Math.max(0, usados - LIMITE_DA_RESPOSTA) }
}

export function podeEnviar(texto: string): boolean {
  return texto.trim().length > 0 && contador(texto).excesso === 0
}

/**
 * Se a janela do WhatsApp ja fechou (D2).
 *
 * `fechaEm` vem do detalhe; `ultimaFalaDoLeadEm` e a fala mais recente do lead
 * que a tela tem, e a que chegou pelo polling pode reabrir a janela. Vale o
 * mais tarde dos dois. Sem nenhum -- o site, ou quem nunca falou --, nao ha
 * janela. **A borda e estrita**, como em `dentro_da_janela`: no instante exato
 * do fechamento ja e fechada.
 */
export function janelaFechada({
  fechaEm,
  ultimaFalaDoLeadEm,
  agora,
}: {
  fechaEm: string | null
  ultimaFalaDoLeadEm: string | null
  agora: Date
}): boolean {
  if (fechaEm === null) {
    return false
  }
  const candidatos = [Date.parse(fechaEm)]
  if (ultimaFalaDoLeadEm !== null) {
    candidatos.push(Date.parse(ultimaFalaDoLeadEm) + JANELA_DE_SERVICO_MS)
  }
  return agora.getTime() >= Math.max(...candidatos)
}

export const EXPLICACAO_DA_JANELA =
  'Já se passaram 24 horas desde a última mensagem do lead. Pelo WhatsApp, fora dessa janela só um modelo de mensagem aprovado pode ser enviado, e o painel ainda não envia modelos.'

export type Recusa = {
  mensagem: string
  /**
   * O que a recusa faz com o campo. `janela`, `optout` e `outro` o
   * desabilitam; `null` o deixa como esta, com o mesmo texto -- e o mesmo
   * `messageId`, que e o que torna o reenvio seguro (D3).
   */
  bloqueia: 'janela' | 'optout' | 'outro' | null
}

/** O que dizer quando o backend recusa (D4 do desenho). */
export function recusaDaResposta(status: number, detail: unknown): Recusa {
  if (status === 409) {
    switch (detail) {
      case 'janela_fechada':
        return { mensagem: EXPLICACAO_DA_JANELA, bloqueia: 'janela' }
      case 'lead_em_optout':
        return { mensagem: 'O lead pediu para não receber mensagens.', bloqueia: 'optout' }
      case 'conversa_de_outro':
        return {
          mensagem: 'Outro corretor assumiu esta conversa. Recarregue a página.',
          bloqueia: 'outro',
        }
      case 'fala_em_envio':
        return { mensagem: 'Esta mensagem já está sendo enviada. Aguarde um instante.', bloqueia: null }
    }
  }
  if (status === 502) {
    return { mensagem: 'Não foi possível entregar a mensagem. Tente de novo.', bloqueia: null }
  }
  if (status === 401) {
    return { mensagem: 'Sua sessão terminou. Recarregue a página para entrar de novo.', bloqueia: null }
  }
  return { mensagem: 'Não foi possível enviar. Tente de novo.', bloqueia: null }
}

/**
 * Os tempos e as regras da sessao ociosa (TEC-311).
 *
 * Puro e sem `server-only`: o aviso de inatividade, que e componente de
 * cliente, e a sessao no servidor leem os mesmos numeros daqui. Dois numeros
 * copiados em dois lugares seriam dois limites livres para divergir -- e o do
 * servidor TEM de ser maior que o do cliente (ver `MINUTOS_OCIOSO_NO_SERVIDOR`).
 */

/** Sem interacao por este tempo, o aviso abre (a regra da card). */
export const MINUTOS_ATE_O_AVISO = 30

/** A contagem regressiva do aviso (a regra da card). */
export const SEGUNDOS_DE_CONTAGEM = 60

/**
 * De quanto em quanto tempo, no maximo, a interacao vira um batimento para o
 * servidor (`POST /sessao/atividade`). Sem batimento, quem le o funil por 35
 * minutos mexendo o mouse -- ativo -- seria derrubado pelo servidor, que so ve
 * navegacao. Ver a D3 do desenho.
 */
export const MS_ENTRE_BATIMENTOS = 60_000

/**
 * O limite do SERVIDOR, que tem de ser maior que o do cliente.
 *
 * O cliente encerra aos 30 minutos mais os 60 segundos da contagem, e o
 * batimento chega com ate um minuto de atraso em relacao a interacao real.
 * 32 minutos e o menor limite em que o servidor nunca encerra antes de o
 * cliente ter avisado. Ver a D3 do desenho.
 */
export const MINUTOS_OCIOSO_NO_SERVIDOR = 32

const MS_ATE_O_AVISO = MINUTOS_ATE_O_AVISO * 60_000
const MS_ATE_ENCERRAR = MS_ATE_O_AVISO + SEGUNDOS_DE_CONTAGEM * 1000

export type Fase =
  | { fase: 'ativo' }
  | { fase: 'aviso'; segundosRestantes: number }
  | { fase: 'encerrar' }

/**
 * Em que ponto a sessao esta, a partir de dois horarios.
 *
 * **Horarios, e nao um timer que conta.** Navegador atrasa timer de aba em
 * segundo plano; a aba que acorda depois de 40 minutos precisa saber na hora
 * que ja passou do limite, e so a comparacao de horarios sabe (D1).
 */
export function faseDaInatividade(agora: number, ultimaInteracao: number): Fase {
  const parado = agora - ultimaInteracao
  if (parado >= MS_ATE_ENCERRAR) {
    return { fase: 'encerrar' }
  }
  if (parado >= MS_ATE_O_AVISO) {
    return { fase: 'aviso', segundosRestantes: Math.ceil((MS_ATE_ENCERRAR - parado) / 1000) }
  }
  return { fase: 'ativo' }
}

/**
 * Os formularios com alteracao pendente (D4).
 *
 * Um formulario de edicao chama `registrarAlteracaoNaoSalva('qualificacao',
 * true)` quando fica sujo e `false` quando salva ou descarta. O aviso de
 * inatividade pergunta `haAlteracaoNaoSalva()` e, se houver, diz que ela vai
 * se perder. Hoje nenhum formulario chama isto -- o primeiro e o da
 * qualificacao, na TEC-329.
 */
const alteracoes = new Set<string>()
const ouvintes = new Set<() => void>()

export function registrarAlteracaoNaoSalva(chave: string, pendente: boolean): void {
  if (pendente) {
    alteracoes.add(chave)
  } else {
    alteracoes.delete(chave)
  }
  ouvintes.forEach((ouvinte) => ouvinte())
}

export function haAlteracaoNaoSalva(): boolean {
  return alteracoes.size > 0
}

/** Para o aviso redesenhar quando uma alteracao entra ou sai. Devolve o cancelamento. */
export function ouvirAlteracoes(ouvinte: () => void): () => void {
  ouvintes.add(ouvinte)
  return () => ouvintes.delete(ouvinte)
}

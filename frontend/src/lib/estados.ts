/**
 * Os cinco estados de um componente com dado remoto (TEC-313, RN-FE-04.1 a 04.4).
 *
 * Modulo sem I/O e sem JSX: decide QUAL estado um valor representa, e nada
 * mais. As pecas que desenham cada estado moram em `components/estado/`.
 *
 * **A regra que esta card existe para proteger cabe numa linha:** zero e um
 * numero medido, ausencia nao e. Exibir `0` no lugar de "Ainda nao medido"
 * desfaz o contrato da TEC-190 e faz a gerente ler uma queda do negocio onde
 * ha um defeito do sistema -- que e a decisao mais cara que este painel apoia.
 */

export type EstadoDeDado = 'carregando' | 'vazio' | 'erro' | 'sem_fonte' | 'com_dados'

/**
 * O que o backend manda sobre um valor: ele proprio, e se existe fonte para
 * ele. `disponivel: false` significa "ninguem registra isso ainda" -- hoje, os
 * quatro indicadores de visita, que so terao fonte com a RF-12.
 */
export type ValorRemoto = {
  valor: number | Record<string, number> | null
  disponivel: boolean
}

/**
 * Decide o estado de um valor ja recebido.
 *
 * **A ordem dos testes e a regra, e nao arrumacao.**
 *
 * 1. `disponivel: false` decide PRIMEIRO, e sozinho. Um indicador sem fonte
 *    que viesse com `valor: 0` -- por defeito do backend, por default de
 *    serializacao, por um `COALESCE` que alguem acrescentar um dia -- ainda e
 *    "sem fonte". Testar o valor antes deixaria esse zero virar "com dados",
 *    que e exatamente o defeito que a card nomeia.
 * 2. Nulo e `vazio`: houve o que medir, e nao havia nada. Coorte vazia e fato
 *    do negocio.
 * 3. **Zero e `com_dados`.** Nao e caso de borda, e a razao de a funcao
 *    existir: zero lead qualificado no periodo e uma medicao, e o painel deve
 *    mostra-la como numero.
 *
 * `carregando` e `erro` nao saem daqui: nao sao propriedades do valor, sao da
 * requisicao. Quem os conhece e a pagina.
 */
export function estadoDe({ valor, disponivel }: ValorRemoto): EstadoDeDado {
  if (!disponivel) {
    return 'sem_fonte'
  }
  if (valor === null) {
    return 'vazio'
  }
  // Objeto vazio e a coorte vazia, e nao uma distribuicao de zero faixas --
  // mesma decisao que `Indicadores.valorLegivel` ja tomava, movida para ca
  // para valer em toda tela e nao so naquele cartao.
  if (typeof valor === 'object' && Object.keys(valor).length === 0) {
    return 'vazio'
  }
  return 'com_dados'
}

/**
 * O texto da RN-FE-04.2.
 *
 * **Vive aqui, e nao dentro do componente**, pelo mesmo motivo que
 * `REL_DE_LINK_EXTERNO` (TEC-356) vive em `lib/`: uma segunda tela que precise
 * do mesmo rotulo tem de reusar, nao reescrever. Duas grafias da mesma ausencia
 * na mesma tela e o defeito que a D1 do desenho recusa.
 *
 * Substituiu `"sem fonte de dados"`, que era o texto da TEC-190.
 */
export const TEXTO_SEM_FONTE = 'Ainda não medido'

/** O texto de coorte vazia. Distinto do acima de proposito -- ver `estadoDe`. */
export const TEXTO_VAZIO = 'sem dados no período'

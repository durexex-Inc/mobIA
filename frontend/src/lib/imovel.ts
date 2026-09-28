/**
 * O imovel do frame `imovel` do chat web (TEC-349), no formato que a TEC-364
 * fixou: `src/mobia/domain/agente/apresentacao.py::card_de`. Puro -- so ler o
 * que veio da rede e formatar para a tela.
 *
 * **Quatro campos podem vir nulos, e so quatro:** `condominioCentavos` e
 * `diferencial` (o catalogo os tem vazios de verdade), `foto` (placeholder no
 * lugar, RN-FE-18.2) e `url` (sempre nulo hoje: o catalogo nao guarda a pagina
 * do imovel, L1 da TEC-364). Qualquer outro campo faltando ou com o tipo
 * errado descarta o card inteiro: um card sem preco ou sem bairro afirmaria
 * algo sobre o imovel que o servidor nao disse.
 */

export type ImovelCard = {
  id: string
  titulo: string
  bairro: string
  precoCentavos: number
  condominioCentavos: number | null
  quartos: number
  vagas: number
  areaUtilM2: number
  diferencial: string | null
  foto: string | null
  url: string | null
}

type Bruto = Record<string, unknown>

function inteiroNaoNegativo(valor: unknown): valor is number {
  return typeof valor === 'number' && Number.isInteger(valor) && valor >= 0
}

function textoNaoVazio(valor: unknown): valor is string {
  return typeof valor === 'string' && valor.trim() !== ''
}

/**
 * So `http:` e `https:`. A foto vira `src` e a pagina vira `href`: um
 * `javascript:` vindo da rede, num `href`, rodaria na pagina do chat. O
 * servidor nao manda isso, e esta checagem e o que garante que nunca vai.
 */
export function urlSegura(valor: unknown): string | null {
  if (typeof valor !== 'string') {
    return null
  }
  try {
    const url = new URL(valor)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

export function imovelDe(valor: unknown): ImovelCard | null {
  if (typeof valor !== 'object' || valor === null || Array.isArray(valor)) {
    return null
  }
  const dado = valor as Bruto
  if (
    !textoNaoVazio(dado.id) ||
    !textoNaoVazio(dado.titulo) ||
    !textoNaoVazio(dado.bairro) ||
    !inteiroNaoNegativo(dado.precoCentavos) ||
    !inteiroNaoNegativo(dado.quartos) ||
    !inteiroNaoNegativo(dado.vagas) ||
    !inteiroNaoNegativo(dado.areaUtilM2)
  ) {
    return null
  }
  return {
    id: dado.id,
    titulo: dado.titulo,
    bairro: dado.bairro,
    precoCentavos: dado.precoCentavos,
    condominioCentavos: inteiroNaoNegativo(dado.condominioCentavos) ? dado.condominioCentavos : null,
    quartos: dado.quartos,
    vagas: dado.vagas,
    areaUtilM2: dado.areaUtilM2,
    diferencial: textoNaoVazio(dado.diferencial) ? dado.diferencial : null,
    foto: urlSegura(dado.foto),
    url: urlSegura(dado.url),
  }
}

/**
 * `R$ 516.464` a partir de 51646430 -- o mesmo texto de `reais_de` no
 * servidor, que TRUNCA os centavos e nunca arredonda: arredondar para cima
 * mostraria um preco acima do real.
 */
export function reais(centavos: number): string {
  return `R$ ${Math.floor(centavos / 100).toLocaleString('pt-BR')}`
}

export function contagem(quantidade: number, singular: string, plural: string): string {
  return `${quantidade} ${quantidade === 1 ? singular : plural}`
}

/**
 * As duas primeiras caracteristicas, juntas por " e " -- mesma regra de
 * `apresentacao.py::diferencial_de` (`CARACTERISTICAS_NO_DESTAQUE = 2`), D4 do
 * desenho da TEC-336. `null` quando a lista esta vazia, para `imovelDe`
 * descartar o campo do mesmo jeito que descartaria um `diferencial` vazio
 * vindo da rede.
 */
export function diferencialDe(caracteristicas: string[]): string | null {
  const escolhidas = caracteristicas.slice(0, 2)
  return escolhidas.length > 0 ? escolhidas.join(' e ') : null
}

/** O texto alternativo da foto (RN-FE-18.4): "Foto de {titulo} em {bairro}". */
export function textoAlternativo(imovel: Pick<ImovelCard, 'titulo' | 'bairro'>): string {
  return `Foto de ${imovel.titulo} em ${imovel.bairro}`
}

/** O toque rapido num card (TEC-350): "Gostei" ou "Não é pra mim". */
export type Reacao = 'gostei' | 'nao_e_pra_mim'

/**
 * A mensagem que o toque manda como fala da visitante (TEC-350, D1). Titulo
 * e bairro sao o que `classificador.reagir` le de cada imovel apresentado
 * (`N. {titulo} -- {bairro}`, em `domain/agente/turno.py`): com os dois, o
 * modelo acha o ordinal certo mesmo entre dois cards de titulo igual. O `id`
 * fica de fora -- o modelo nunca o ve (D7 da TEC-163).
 */
export function textoDaReacao(reacao: Reacao, imovel: Pick<ImovelCard, 'titulo' | 'bairro'>): string {
  const nome = `"${imovel.titulo}" (${imovel.bairro})`
  return reacao === 'gostei' ? `Gostei do imóvel ${nome}.` : `O imóvel ${nome} não é pra mim.`
}

/**
 * O detalhe publico de um imovel (TEC-388), do corpo de
 * `GET /portal/imoveis/{id}` (`api/routes/portal.py::payload_do_detalhe`).
 *
 * Tipo proprio, e nao uma extensao de `ImovelCard` (`lib/imovel.ts`): aquele
 * e o resumo da busca, com uma validacao pensada para aquele formato -- o
 * detalhe tem campos a mais (descricao, caracteristicas completas, os dois
 * precos, lista de fotos) que nao fazem sentido num card de listagem.
 *
 * `fotos` sao caminhos RELATIVOS (`/portal/imoveis/{id}/fotos/{fotoId}`), ao
 * contrario de `ImovelCard.foto`, que exige URL absoluta `http(s)` -- aqui a
 * foto e sempre servida por este mesmo backend, nunca por terceiro.
 */

export type ImovelDetalhe = {
  id: string
  codigo: string
  titulo: string
  descricao: string
  tipo: string
  operacao: string
  bairro: string
  cidade: string
  uf: string
  areaUtilM2: number
  quartos: number
  suites: number
  banheiros: number
  vagas: number
  precoVenda: number | null
  precoAluguel: number | null
  condominio: number | null
  iptuMensal: number | null
  caracteristicas: string[]
  fotos: string[]
  /** Ja arredondadas pelo backend (`portal.py::_coordenada_publica`). */
  latitude: number | null
  longitude: number | null
}

type Bruto = Record<string, unknown>

function inteiroNaoNegativo(valor: unknown): valor is number {
  return typeof valor === 'number' && Number.isInteger(valor) && valor >= 0
}

function inteiroOuNulo(valor: unknown): number | null {
  return inteiroNaoNegativo(valor) ? valor : null
}

function textoNaoVazio(valor: unknown): valor is string {
  return typeof valor === 'string' && valor.trim() !== ''
}

function coordenadaOuNula(valor: unknown, limite: number): number | null {
  return typeof valor === 'number' && Number.isFinite(valor) && Math.abs(valor) <= limite ? valor : null
}

function parDeCoordenadas(
  latitude: number | null,
  longitude: number | null,
): Pick<ImovelDetalhe, 'latitude' | 'longitude'> {
  return latitude === null || longitude === null ? { latitude: null, longitude: null } : { latitude, longitude }
}

function listaDeTexto(valor: unknown): string[] {
  return Array.isArray(valor) ? valor.filter((item): item is string => typeof item === 'string') : []
}

export function imovelDetalheDe(valor: unknown): ImovelDetalhe | null {
  if (typeof valor !== 'object' || valor === null || Array.isArray(valor)) {
    return null
  }
  const dado = valor as Bruto
  if (
    !textoNaoVazio(dado.id) ||
    !textoNaoVazio(dado.codigo) ||
    !textoNaoVazio(dado.titulo) ||
    !textoNaoVazio(dado.descricao) ||
    !textoNaoVazio(dado.tipo) ||
    !textoNaoVazio(dado.operacao) ||
    !textoNaoVazio(dado.bairro) ||
    !textoNaoVazio(dado.cidade) ||
    !textoNaoVazio(dado.uf) ||
    !inteiroNaoNegativo(dado.areaUtilM2) ||
    !inteiroNaoNegativo(dado.quartos) ||
    !inteiroNaoNegativo(dado.suites) ||
    !inteiroNaoNegativo(dado.banheiros) ||
    !inteiroNaoNegativo(dado.vagas)
  ) {
    return null
  }
  return {
    id: dado.id,
    codigo: dado.codigo,
    titulo: dado.titulo,
    descricao: dado.descricao,
    tipo: dado.tipo,
    operacao: dado.operacao,
    bairro: dado.bairro,
    cidade: dado.cidade,
    uf: dado.uf,
    areaUtilM2: dado.areaUtilM2,
    quartos: dado.quartos,
    suites: dado.suites,
    banheiros: dado.banheiros,
    vagas: dado.vagas,
    precoVenda: inteiroOuNulo(dado.precoVenda),
    precoAluguel: inteiroOuNulo(dado.precoAluguel),
    condominio: inteiroOuNulo(dado.condominio),
    iptuMensal: inteiroOuNulo(dado.iptuMensal),
    caracteristicas: listaDeTexto(dado.caracteristicas),
    fotos: listaDeTexto(dado.fotos),
    // So o par inteiro vale: meia coordenada nao posiciona mapa nenhum.
    ...parDeCoordenadas(coordenadaOuNula(dado.latitude, 90), coordenadaOuNula(dado.longitude, 180)),
  }
}

/**
 * Enviar, reordenar e remover fotos de imovel, sem I/O (TEC-335).
 *
 * D6 do desenho: `FOTO_TETO_DE_BYTES`/`FOTO_LIMITE_POR_IMOVEL` sao a mesma
 * duplicacao deliberada de `TETO_DE_UPLOAD_EM_BYTES`
 * (`lib/importacaoDeImoveis.ts`) -- o cliente confere ANTES do envio para a
 * resposta ser instantanea, mas a checagem real e a assinatura de bytes do
 * backend (`domain/catalogo/fotos.py::detectar_formato`, D3). Um arquivo
 * `.jpg` que na verdade e outra coisa passa por aqui e e recusado pelo
 * servidor -- essa recusa nao se reimplementa em JavaScript.
 *
 * D4/D5 do desenho: reordenar e remover sao a MESMA operacao do lado do
 * backend -- mandar `fotos: list[str]` numa ordem ou tamanho diferente pelo
 * `PATCH` que a TEC-333 ja abriu. `reordenar`/`remover` so montam a lista
 * nova; quem envia e o componente.
 */

export const FOTO_TETO_DE_BYTES = 5 * 1024 * 1024
export const FOTO_LIMITE_POR_IMOVEL = 15

const EXTENSOES_ACEITAS = ['.jpg', '.jpeg', '.png', '.webp']

/**
 * A recusa client-side, ou `null` quando o arquivo passa na pre-checagem
 * (D6). Nao substitui a validacao do backend -- so evita o round-trip para o
 * erro obvio (tamanho, extensao claramente errada).
 */
export function recusaDoArquivo(arquivo: File): string | null {
  if (arquivo.size > FOTO_TETO_DE_BYTES) {
    const tetoEmMb = FOTO_TETO_DE_BYTES / (1024 * 1024)
    return `A foto passa de ${tetoEmMb} MB.`
  }
  const nome = arquivo.name.toLowerCase()
  if (!EXTENSOES_ACEITAS.some((extensao) => nome.endsWith(extensao))) {
    return 'Envie uma foto em JPEG, PNG ou WebP.'
  }
  return null
}

/** Move o item de `origem` para `destino`, preservando os demais em ordem. */
export function reordenar(fotos: readonly string[], origem: number, destino: number): string[] {
  if (
    origem < 0 ||
    origem >= fotos.length ||
    destino < 0 ||
    destino >= fotos.length ||
    origem === destino
  ) {
    return [...fotos]
  }
  const copia = [...fotos]
  const [movida] = copia.splice(origem, 1)
  copia.splice(destino, 0, movida)
  return copia
}

/** A lista sem a foto no indice dado (D4: sem apagar o arquivo do armazem). */
export function remover(fotos: readonly string[], indice: number): string[] {
  return fotos.filter((_, i) => i !== indice)
}

/** O que dizer quando o backend recusa o upload (D3, D6). */
export function mensagemDeErroDoEnvio(status: number, detail: unknown): string {
  if (status === 401) {
    return 'Sua sessão terminou. Recarregue a página para entrar de novo.'
  }
  if (status === 403) {
    return 'Você não tem permissão para gerir o catálogo.'
  }
  if (status === 404) {
    return 'Este imóvel não existe mais.'
  }
  if (status === 422 && typeof detail === 'string') {
    return detail
  }
  return 'Não foi possível enviar a foto. Tente de novo.'
}

import { TEXTO_VAZIO } from '@/lib/estados'

/**
 * A ausencia que e fato do negocio: houve o que medir e nao havia nada
 * (TEC-313, RN-FE-04.1).
 *
 * Distinto de `AindaNaoMedido` de proposito, e a distincao e a card inteira:
 * la nao existe fonte e o conserto e a RF-12; aqui a coorte estava vazia e nao
 * ha nada a consertar. Um texto so para as duas mandaria a gerente procurar um
 * problema que nao existe -- ou ignorar um que existe.
 */
export function Vazio({ texto = TEXTO_VAZIO }: { texto?: string }) {
  return <span className="estado-vazio">{texto}</span>
}

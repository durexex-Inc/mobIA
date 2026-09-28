'use client'

import { useRef } from 'react'

import { CardDeImovel } from '@/components/CardDeImovel'
import { diferencialDe, imovelDe } from '@/lib/imovel'
import { type Formulario, type Imovel, reaisParaCentavos } from '@/lib/imoveis'

/**
 * Pre-visualizar o card do imovel como o visitante veria no chat web
 * (TEC-336). So a edicao usa isto (D2 do desenho) -- o botao que abre fica
 * desabilitado enquanto `formularioValido(atual)` for falso, entao este
 * componente nunca precisa decidir o que mostrar para um formulario
 * incompleto.
 *
 * **Monta o objeto cru no formato de `card_de` e passa pelo MESMO
 * `imovelDe` que validaria um payload de rede** (D1): nao ha atalho mais
 * tolerante para os dados do formulario. `foto` e `fotos[0] ?? null`, sem
 * caso especial -- se for o caminho relativo que a TEC-335 grava,
 * `urlSegura` recusa e o card cai no placeholder, o mesmo destino que teria
 * no chat de verdade (achado fora do escopo desta card, registrado no
 * desenho). "Fixar" isso aqui faria a pre-visualizacao mentir sobre o que o
 * visitante realmente ve.
 */
export function PreviewDoCard({
  imovel,
  formulario,
  fotos,
  desabilitado = false,
}: {
  imovel: Imovel
  formulario: Formulario
  fotos: string[]
  /** `!formularioValido(atual)` (D2 do desenho): sem isso o botao abriria a
   * pre-visualizacao para um formulario incompleto, que a card nao pede. */
  desabilitado?: boolean
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  function abrir() {
    dialogRef.current?.showModal()
  }

  function fechar() {
    dialogRef.current?.close()
  }

  const cru = {
    id: imovel.id,
    titulo: formulario.titulo,
    bairro: formulario.bairro,
    // D3: sem operacao de busca nenhuma para desempatar `AMBOS`, prioriza o
    // preco de venda e so cai para o de aluguel quando nao houver venda.
    precoCentavos:
      reaisParaCentavos(formulario.precoVenda) ?? reaisParaCentavos(formulario.precoAluguel),
    condominioCentavos: reaisParaCentavos(formulario.condominio),
    quartos: Number(formulario.quartos),
    vagas: Number(formulario.vagas),
    areaUtilM2: Number(formulario.areaUtilM2),
    diferencial: diferencialDe(formulario.caracteristicas),
    foto: fotos[0] ?? null,
    url: null,
  }
  const card = imovelDe(cru)

  return (
    <>
      <button type="button" onClick={abrir} disabled={desabilitado}>
        Pré-visualizar card
      </button>
      <dialog ref={dialogRef} className="preview-do-card">
        <button type="button" onClick={fechar} className="preview-do-card__fechar">
          Fechar
        </button>
        {card ? (
          <CardDeImovel imovel={card} />
        ) : (
          // Nao deveria ser alcancavel com o botao desabilitado ate o
          // formulario ser valido (D2) -- mensagem simples, sem esforco de
          // desenho num caminho que nao se espera exercitar.
          <p>Não foi possível montar a pré-visualização com os dados atuais.</p>
        )}
      </dialog>
    </>
  )
}

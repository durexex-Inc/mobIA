'use client'

import { useState } from 'react'

/**
 * A galeria do detalhe publico (D5 do desenho do visual do portal): foto
 * grande, contador e miniaturas que trocam a foto grande.
 *
 * **So a foto grande tem `alt`.** As miniaturas sao botoes com nome proprio
 * ("Ver foto 2 de 5") e a imagem deles e decorativa -- sem isso, quem usa
 * leitor de tela ouviria o titulo do imovel uma vez por foto.
 */
export function GaleriaDoImovel({ fotos, titulo }: { fotos: string[]; titulo: string }) {
  const [atual, setAtual] = useState(0)

  return (
    <div className="portal-galeria">
      {/* eslint-disable-next-line @next/next/no-img-element -- mesma razao de CardDeImovel: o host nao e conhecido de antemao. */}
      <img className="portal-galeria__principal" src={fotos[atual]} alt={`Foto de ${titulo}`} />
      <span className="portal-galeria__contador" aria-live="polite">
        {atual + 1} / {fotos.length} {fotos.length === 1 ? 'foto' : 'fotos'}
      </span>
      {fotos.length > 1 && (
        <ul className="portal-galeria__miniaturas">
          {fotos.map((foto, indice) => (
            <li key={foto}>
              <button
                type="button"
                className="portal-galeria__miniatura"
                aria-label={`Ver foto ${indice + 1} de ${fotos.length}`}
                aria-current={indice === atual}
                onClick={() => setAtual(indice)}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- idem. */}
                <img src={foto} alt="" loading="lazy" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

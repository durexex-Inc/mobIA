'use client'

import { useEffect, useRef, useState } from 'react'

/** Quantas fotos o mosaico do desktop mostra: uma grande e quatro pequenas. */
const FOTOS_NO_MOSAICO = 5

/**
 * A galeria do detalhe publico (D5 do desenho do visual do portal).
 *
 * **Duas apresentacoes das mesmas fotos, e o CSS escolhe qual aparece.** No
 * celular, foto grande com contador e miniaturas por cima; no desktop, o
 * mosaico de ate cinco fotos da referencia. Qualquer foto do mosaico abre a
 * ampliacao, que percorre todas -- e a unica forma de ver da sexta em diante
 * no desktop.
 *
 * **So a foto grande do celular tem `alt`.** Miniaturas e ladrilhos sao
 * botoes com nome proprio ("Ver foto 2 de 5") e a imagem deles e decorativa
 * -- sem isso, quem usa leitor de tela ouviria o titulo do imovel uma vez
 * por foto.
 */
export function GaleriaDoImovel({ fotos, titulo }: { fotos: string[]; titulo: string }) {
  const [atual, setAtual] = useState(0)
  const [ampliada, setAmpliada] = useState<number | null>(null)
  const temMosaico = fotos.length > 1
  const noMosaico = fotos.slice(0, FOTOS_NO_MOSAICO)

  return (
    <>
      <div className={temMosaico ? 'portal-galeria portal-galeria--com-mosaico' : 'portal-galeria'}>
        {/* eslint-disable-next-line @next/next/no-img-element -- mesma razao de CardDeImovel: o host nao e conhecido de antemao. */}
        <img className="portal-galeria__principal" src={fotos[atual]} alt={`Foto de ${titulo}`} />
        <span className="portal-galeria__contador" aria-live="polite">
          {atual + 1} / {fotos.length} {fotos.length === 1 ? 'foto' : 'fotos'}
        </span>
        {temMosaico && (
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

      {temMosaico && (
        <ul className="portal-mosaico" data-quantidade={noMosaico.length}>
          {noMosaico.map((foto, indice) => {
            const ultimo = indice === noMosaico.length - 1
            return (
              <li key={foto}>
                <button
                  type="button"
                  className="portal-mosaico__foto"
                  aria-label={ultimo ? `Ver as ${fotos.length} fotos` : `Ampliar foto ${indice + 1} de ${fotos.length}`}
                  onClick={() => setAmpliada(indice)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- idem. */}
                  <img src={foto} alt="" loading={indice === 0 ? 'eager' : 'lazy'} />
                  {ultimo && <span className="portal-mosaico__todas">Ver as {fotos.length} fotos</span>}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {ampliada !== null && (
        <Ampliacao fotos={fotos} titulo={titulo} inicial={ampliada} aoFechar={() => setAmpliada(null)} />
      )}
    </>
  )
}

/**
 * As fotos em tela cheia, uma de cada vez. Esc fecha e as setas do teclado
 * navegam; o foco vai para "Fechar" ao abrir, para o teclado nao ficar preso
 * atras da sobreposicao.
 */
function Ampliacao({
  fotos,
  titulo,
  inicial,
  aoFechar,
}: {
  fotos: string[]
  titulo: string
  inicial: number
  aoFechar: () => void
}) {
  const [indice, setIndice] = useState(inicial)
  const fechar = useRef<HTMLButtonElement>(null)
  const anterior = () => setIndice((i) => (i - 1 + fotos.length) % fotos.length)
  const proxima = () => setIndice((i) => (i + 1) % fotos.length)

  useEffect(() => {
    fechar.current?.focus()
  }, [])

  return (
    <div
      className="portal-ampliacao"
      role="dialog"
      aria-modal="true"
      aria-label={`Fotos de ${titulo}`}
      onKeyDown={(evento) => {
        if (evento.key === 'Escape') aoFechar()
        if (evento.key === 'ArrowLeft') anterior()
        if (evento.key === 'ArrowRight') proxima()
      }}
    >
      <div className="portal-ampliacao__topo">
        <span>
          {indice + 1} / {fotos.length}
        </span>
        <button ref={fechar} type="button" className="portal-ampliacao__botao" onClick={aoFechar}>
          Fechar
        </button>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element -- idem. */}
      <img
        className="portal-ampliacao__foto"
        src={fotos[indice]}
        alt={`Foto ${indice + 1} de ${fotos.length} de ${titulo}`}
      />
      <button type="button" className="portal-ampliacao__seta portal-ampliacao__seta--anterior" onClick={anterior}>
        <span aria-hidden="true">‹</span>
        <span className="visually-hidden">Foto anterior</span>
      </button>
      <button type="button" className="portal-ampliacao__seta portal-ampliacao__seta--proxima" onClick={proxima}>
        <span aria-hidden="true">›</span>
        <span className="visually-hidden">Próxima foto</span>
      </button>
    </div>
  )
}

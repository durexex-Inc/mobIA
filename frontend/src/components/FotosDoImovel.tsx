'use client'

import { type ChangeEvent, type DragEvent, useId, useRef, useState } from 'react'

import {
  FOTO_LIMITE_POR_IMOVEL,
  mensagemDeErroDoEnvio,
  recusaDoArquivo,
  remover,
  reordenar,
} from '@/lib/fotos'

/**
 * Miniaturas, upload, reordenacao e remocao das fotos de um imovel. TEC-335,
 * D5/D6/D7.
 *
 * **So aparece na edicao** (o `imovel_id` e obrigatorio para o upload) -- quem
 * decide isso e o chamador (`FormularioDeImovel`), nao este componente.
 *
 * **A miniatura e um `<img>` de mesma origem** (`/bff/api/v1/.../fotos/{id}`,
 * D7): o cookie de sessao acompanha, sem tratamento especial.
 *
 * **Reordenar e remover sao o MESMO `PATCH`** (D4/D5): monta a lista inteira
 * na nova ordem/tamanho e manda de uma vez, aguardando a resposta antes de
 * deixar mover de novo -- evita duas reordenacoes em voo pisando uma na
 * outra.
 *
 * **Os botoes "mover para cima"/"mover para baixo" sao `<button>` reais**,
 * acionaveis por Enter/Espaco sem depender do arraste -- e o que o Gherkin
 * "usando apenas o teclado" exige. O arraste HTML5 nativo (`draggable`) e um
 * adicional, sem biblioteca nova (D5).
 */
export function FotosDoImovel({
  imovelId,
  fotos,
  onFotosMudaram,
}: {
  imovelId: string
  fotos: string[]
  onFotosMudaram: (fotos: string[]) => void
}) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [arrastando, setArrastando] = useState<number | null>(null)

  async function aplicarPatch(novaLista: string[]): Promise<boolean> {
    setEnviando(true)
    setErro(null)
    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/imoveis/${encodeURIComponent(imovelId)}`, {
        method: 'PATCH',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ fotos: novaLista }),
      })
    } catch {
      setEnviando(false)
      setErro('Não foi possível falar com o servidor. Tente de novo.')
      return false
    }
    setEnviando(false)
    if (!resposta.ok) {
      let detail: unknown
      try {
        detail = ((await resposta.json()) as { detail?: unknown }).detail
      } catch {
        detail = undefined
      }
      setErro(mensagemDeErroDoEnvio(resposta.status, detail))
      return false
    }
    onFotosMudaram(novaLista)
    return true
  }

  async function mover(indice: number, direcao: -1 | 1) {
    if (enviando) {
      return
    }
    const destino = indice + direcao
    await aplicarPatch(reordenar(fotos, indice, destino))
  }

  async function removerFoto(indice: number) {
    if (enviando) {
      return
    }
    await aplicarPatch(remover(fotos, indice))
  }

  async function enviarArquivo(arquivo: File) {
    const recusa = recusaDoArquivo(arquivo)
    if (recusa) {
      setErro(recusa)
      return
    }

    setEnviando(true)
    setErro(null)

    const corpo = new FormData()
    corpo.append('arquivo', arquivo)

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/imoveis/${encodeURIComponent(imovelId)}/fotos`, {
        method: 'POST',
        body: corpo,
      })
    } catch {
      setEnviando(false)
      setErro('Não foi possível falar com o servidor. Tente de novo.')
      return
    }

    setEnviando(false)
    if (!resposta.ok) {
      let detail: unknown
      try {
        detail = ((await resposta.json()) as { detail?: unknown }).detail
      } catch {
        detail = undefined
      }
      setErro(mensagemDeErroDoEnvio(resposta.status, detail))
      return
    }

    const dados = (await resposta.json()) as { fotos: string[] }
    onFotosMudaram(dados.fotos)
    if (inputRef.current) {
      inputRef.current.value = ''
    }
  }

  async function selecionar(evento: ChangeEvent<HTMLInputElement>) {
    const arquivo = evento.target.files?.[0]
    if (arquivo) {
      await enviarArquivo(arquivo)
    }
  }

  function arrastarInicio(indice: number) {
    return (evento: DragEvent<HTMLLIElement>) => {
      evento.dataTransfer.effectAllowed = 'move'
      evento.dataTransfer.setData('text/plain', String(indice))
      setArrastando(indice)
    }
  }

  function arrastarSobre(evento: DragEvent<HTMLLIElement>) {
    evento.preventDefault()
    evento.dataTransfer.dropEffect = 'move'
  }

  function soltar(indice: number) {
    return async (evento: DragEvent<HTMLLIElement>) => {
      evento.preventDefault()
      const origem = arrastando
      setArrastando(null)
      if (origem === null || origem === indice || enviando) {
        return
      }
      await aplicarPatch(reordenar(fotos, origem, indice))
    }
  }

  return (
    <div className="fotos-do-imovel">
      <h3>Fotos</h3>

      {erro && (
        <p className="fotos-do-imovel__aviso" role="alert">
          {erro}
        </p>
      )}

      {fotos.length > 0 && (
        <ul className="fotos-do-imovel__lista">
          {fotos.map((url, indice) => (
            <li
              key={url}
              draggable
              onDragStart={arrastarInicio(indice)}
              onDragOver={arrastarSobre}
              onDrop={soltar(indice)}
              className="fotos-do-imovel__item"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/bff${url}`} alt={`Foto ${indice + 1} do imóvel`} />
              <div className="fotos-do-imovel__acoes">
                <button
                  type="button"
                  onClick={() => mover(indice, -1)}
                  disabled={enviando || indice === 0}
                  aria-label={`Mover foto ${indice + 1} para cima`}
                >
                  Mover para cima
                </button>
                <button
                  type="button"
                  onClick={() => mover(indice, 1)}
                  disabled={enviando || indice === fotos.length - 1}
                  aria-label={`Mover foto ${indice + 1} para baixo`}
                >
                  Mover para baixo
                </button>
                <button
                  type="button"
                  onClick={() => removerFoto(indice)}
                  disabled={enviando}
                  aria-label={`Remover foto ${indice + 1}`}
                >
                  Remover
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {fotos.length >= FOTO_LIMITE_POR_IMOVEL ? (
        <p className="fotos-do-imovel__aviso" role="status">
          O imóvel já tem o limite de {FOTO_LIMITE_POR_IMOVEL} fotos.
        </p>
      ) : (
        <div className="fotos-do-imovel__campo">
          <label htmlFor={inputId}>Adicionar foto</label>
          <input
            id={inputId}
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={selecionar}
            disabled={enviando}
          />
        </div>
      )}
    </div>
  )
}

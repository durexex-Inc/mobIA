'use client'

import { type ChangeEvent, type DragEvent, useId, useRef, useState } from 'react'

import {
  FOTO_LIMITE_POR_IMOVEL,
  FOTO_TETO_DE_BYTES,
  mensagemDeErroDoEnvio,
  recusaDoArquivo,
  remover,
  reordenar,
} from '@/lib/fotos'

import { Botao } from '@/components/ui/Botao'

/**
 * Miniaturas, upload, reordenacao e remocao das fotos de um imovel. TEC-335,
 * D5/D6/D7.
 *
 * **So aparece na edicao** (o `imovel_id` e obrigatorio para o upload) -- quem
 * decide isso e o chamador (`EdicaoDeImovel`, TEC-400), nao este componente.
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
  const [sobreACaixa, setSobreACaixa] = useState(false)
  const [progresso, setProgresso] = useState<{ atual: number; total: number } | null>(null)

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

  /** Envia um arquivo; devolve a mensagem de recusa, ou `null` se entrou. */
  async function enviarArquivo(arquivo: File): Promise<string | null> {
    const recusa = recusaDoArquivo(arquivo)
    if (recusa) {
      return recusa
    }

    const corpo = new FormData()
    corpo.append('arquivo', arquivo)

    let resposta: Response
    try {
      resposta = await fetch(`/bff/api/v1/imoveis/${encodeURIComponent(imovelId)}/fotos`, {
        method: 'POST',
        body: corpo,
      })
    } catch {
      return 'Não foi possível falar com o servidor. Tente de novo.'
    }

    if (!resposta.ok) {
      let detail: unknown
      try {
        detail = ((await resposta.json()) as { detail?: unknown }).detail
      } catch {
        detail = undefined
      }
      return mensagemDeErroDoEnvio(resposta.status, detail)
    }

    const dados = (await resposta.json()) as { fotos: string[] }
    onFotosMudaram(dados.fotos)
    return null
  }

  /**
   * Envia varios arquivos, UM POST POR VEZ: o endpoint recebe um arquivo so,
   * e em sequencia cada resposta traz a lista inteira ja com a foto anterior
   * -- em paralelo, a ultima resposta a chegar ganharia e esconderia fotos
   * que o servidor guardou. Um arquivo recusado nao interrompe os outros.
   *
   * O que passa das vagas restantes nem e enviado: o backend recusaria do
   * mesmo jeito, so que depois de subir os bytes.
   */
  async function enviarArquivos(arquivos: File[]) {
    if (enviando || arquivos.length === 0) {
      return
    }
    const vagas = Math.max(FOTO_LIMITE_POR_IMOVEL - fotos.length, 0)
    const aceitos = arquivos.slice(0, vagas)
    const recusas: string[] = []
    if (arquivos.length > vagas) {
      const fora = arquivos.length - vagas
      recusas.push(
        `Só cabem mais ${vagas} foto(s) neste imóvel; ${fora} arquivo(s) ficaram de fora.`,
      )
    }

    setEnviando(true)
    setErro(null)
    for (const [indice, arquivo] of aceitos.entries()) {
      setProgresso({ atual: indice + 1, total: aceitos.length })
      const recusa = await enviarArquivo(arquivo)
      if (recusa) {
        recusas.push(arquivos.length > 1 ? `${arquivo.name}: ${recusa}` : recusa)
      }
    }
    setProgresso(null)
    setEnviando(false)
    if (recusas.length > 0) {
      setErro(recusas.join(' '))
    }
    if (inputRef.current) {
      inputRef.current.value = ''
    }
  }

  async function selecionar(evento: ChangeEvent<HTMLInputElement>) {
    await enviarArquivos(Array.from(evento.target.files ?? []))
  }

  // So arraste que traz arquivo acende a caixa: arrastar uma miniatura por
  // cima dela nao e upload.
  function arquivoSobre(evento: DragEvent<HTMLDivElement>) {
    if (!evento.dataTransfer.types.includes('Files')) {
      return
    }
    evento.preventDefault()
    evento.dataTransfer.dropEffect = enviando ? 'none' : 'copy'
    setSobreACaixa(true)
  }

  function arquivoSaiu(evento: DragEvent<HTMLDivElement>) {
    // `dragleave` dispara tambem ao passar para um filho; so apaga ao sair
    // da caixa de verdade.
    if (!evento.currentTarget.contains(evento.relatedTarget as Node | null)) {
      setSobreACaixa(false)
    }
  }

  // O `preventDefault` aqui cancela o soltar nativo no `<input>`, que so
  // aceitaria o que o navegador decidisse; o caminho e um so, este.
  async function soltarArquivos(evento: DragEvent<HTMLDivElement>) {
    evento.preventDefault()
    setSobreACaixa(false)
    await enviarArquivos(Array.from(evento.dataTransfer.files))
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
      <div className="fotos-do-imovel__cabecalho">
        <h2>Galeria de fotos</h2>
        <p>
          {fotos.length} de {FOTO_LIMITE_POR_IMOVEL} fotos. Arraste uma miniatura, ou use as setas, para mudar a
          ordem.
        </p>
      </div>

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
              <span className="fotos-do-imovel__numero" aria-hidden="true">
                Foto {indice + 1}
              </span>
              <div className="fotos-do-imovel__acoes">
                <Botao
                  variante="fantasma"
                  tamanho="pequeno"
                  onClick={() => mover(indice, -1)}
                  disabled={enviando || indice === 0}
                  aria-label={`Mover foto ${indice + 1} para cima`}
                >
                  <span aria-hidden="true">←</span>
                </Botao>
                <Botao
                  variante="fantasma"
                  tamanho="pequeno"
                  onClick={() => mover(indice, 1)}
                  disabled={enviando || indice === fotos.length - 1}
                  aria-label={`Mover foto ${indice + 1} para baixo`}
                >
                  <span aria-hidden="true">→</span>
                </Botao>
                <Botao
                  variante="fantasma"
                  tamanho="pequeno"
                  onClick={() => removerFoto(indice)}
                  disabled={enviando}
                  aria-label={`Remover foto ${indice + 1}`}
                >
                  Remover
                </Botao>
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
        // O `<input type="file">` fica esticado por cima da caixa tracejada,
        // invisivel, para o clique em qualquer ponto abrir o seletor (TEC-400).
        // O soltar, porem, e tratado na caixa (`soltarArquivos`), nao no input.
        <div
          className={`fotos-do-imovel__campo${sobreACaixa ? ' fotos-do-imovel__campo--sobre' : ''}`}
          onDragEnter={arquivoSobre}
          onDragOver={arquivoSobre}
          onDragLeave={arquivoSaiu}
          onDrop={soltarArquivos}
        >
          <input
            id={inputId}
            ref={inputRef}
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp"
            onChange={selecionar}
            disabled={enviando}
            aria-describedby={`${inputId}-ajuda`}
          />
          <label htmlFor={inputId}>Adicionar fotos</label>
          <span id={`${inputId}-ajuda`} className="fotos-do-imovel__ajuda" aria-live="polite">
            {progresso
              ? `Enviando ${progresso.atual} de ${progresso.total}…`
              : `Solte uma ou mais fotos aqui, ou clique para escolher. JPG, PNG ou WEBP, até ${FOTO_TETO_DE_BYTES / (1024 * 1024)} MB cada.`}
          </span>
        </div>
      )}
    </div>
  )
}

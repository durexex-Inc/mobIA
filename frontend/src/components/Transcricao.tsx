'use client'

import { useLayoutEffect, useRef, useState } from 'react'

import { urlDoLogin } from '@/lib/destino'
import { dataAbsoluta } from '@/lib/leads'
import {
  type Fala,
  ladoDoAutor,
  type PaginaDaTranscricao,
  rotuloDoAutor,
  textoDaFala,
  urlDasAnteriores,
} from '@/lib/transcricao'

type Estado = 'ocioso' | 'carregando' | 'erro' | 'sessao'

/**
 * A conversa do lead (TEC-324) -- o terceiro componente de cliente do painel,
 * depois do aviso de inatividade e da busca da lista. A razao e a D2 do
 * desenho: inserir 100 falas acima sem perder a posicao de leitura exige medir
 * a altura antes e depois, e isso nao existe sem JS.
 *
 * **Recebe a primeira pagina do servidor** (D1) e busca as anteriores pelo
 * proxy `/bff/*`, que poe o JWT da sessao. So importa modulos puros: nenhum
 * token passa por aqui.
 *
 * **Cada "carregar anteriores" grava um acesso na trilha** (D3 da TEC-193), e
 * por isso so o clique pede a pagina -- nada de carregar ao rolar.
 */
export function Transcricao({ leadId, inicial }: { leadId: string; inicial: PaginaDaTranscricao }) {
  const [falas, setFalas] = useState<Fala[]>(inicial.itens)
  const [cursor, setCursor] = useState(inicial.cursorAnterior)
  const [estado, setEstado] = useState<Estado>('ocioso')
  const [aviso, setAviso] = useState('')
  const caixa = useRef<HTMLDivElement>(null)
  // A distancia entre o ponto de leitura e o fim do conteudo, guardada antes
  // de inserir as anteriores (D3). Nulo quando nao ha insercao pendente.
  const distanciaDoFim = useRef<number | null>(null)

  // Comeca na fala mais recente. A caixa tem rolagem propria: rolar a pagina
  // inteira ate o fim esconderia o resumo, que e a primeira secao.
  useLayoutEffect(() => {
    const elemento = caixa.current
    if (elemento) {
      elemento.scrollTop = elemento.scrollHeight
    }
  }, [])

  // Depois de inserir as anteriores, recoloca a rolagem a mesma distancia do
  // fim -- e o que mantem na tela a fala que a pessoa estava lendo.
  useLayoutEffect(() => {
    const elemento = caixa.current
    if (elemento && distanciaDoFim.current !== null) {
      elemento.scrollTop = elemento.scrollHeight - distanciaDoFim.current
      distanciaDoFim.current = null
    }
  }, [falas])

  async function carregarAnteriores() {
    if (!cursor || estado === 'carregando') {
      return
    }
    setEstado('carregando')
    setAviso('')

    let resposta: Response
    try {
      resposta = await fetch(urlDasAnteriores(leadId, cursor), {
        headers: { Accept: 'application/json' },
      })
    } catch {
      setEstado('erro')
      setAviso('Não foi possível carregar as falas anteriores.')
      return
    }

    if (resposta.status === 401) {
      setEstado('sessao')
      setAviso('Sua sessão terminou.')
      return
    }
    if (!resposta.ok) {
      setEstado('erro')
      setAviso('Não foi possível carregar as falas anteriores.')
      return
    }

    const pagina = (await resposta.json()) as PaginaDaTranscricao
    const elemento = caixa.current
    if (elemento) {
      distanciaDoFim.current = elemento.scrollHeight - elemento.scrollTop
    }
    setFalas((atuais) => [...pagina.itens, ...atuais])
    setCursor(pagina.cursorAnterior)
    setEstado('ocioso')
    setAviso(
      pagina.itens.length === 1
        ? '1 fala anterior carregada.'
        : `${pagina.itens.length} falas anteriores carregadas.`,
    )
  }

  return (
    <div className="transcricao">
      {/* `tabIndex` para a caixa rolar pelo teclado. Sem `role="log"`: ele
          seria regiao viva implicita, e anunciar 100 falas antigas de uma vez
          seria ruido, e nao "mensagem nova" (D5). */}
      <div ref={caixa} className="transcricao-caixa" tabIndex={0} aria-label="Falas da conversa">
        {cursor ? (
          <button
            type="button"
            className="transcricao-anteriores"
            onClick={carregarAnteriores}
            disabled={estado === 'carregando'}
          >
            {estado === 'carregando' ? 'Carregando…' : 'Carregar anteriores'}
          </button>
        ) : (
          <p className="transcricao-inicio">Início da conversa</p>
        )}
        {falas.length === 0 ? (
          <p className="transcricao-inicio">Nenhuma fala nesta conversa.</p>
        ) : (
          falas.map((fala) => (
            <article key={fala.id} className={`fala fala-${ladoDoAutor(fala.autor)}`} data-testid="fala">
              <header>
                <strong>{rotuloDoAutor(fala.autor)}</strong>{' '}
                <time dateTime={fala.em}>{dataAbsoluta(fala.em)}</time>
              </header>
              <p className={fala.retida || !fala.conteudo ? 'fala-sem-texto' : undefined}>
                {textoDaFala(fala)}
              </p>
            </article>
          ))
        )}
      </div>
      {/* A unica regiao viva: anuncia o que mudou com a tela aberta, que e o
          carregamento das anteriores (D5). */}
      <p role="status" aria-live="polite" className="transcricao-aviso">
        {aviso}
        {estado === 'sessao' && (
          <>
            {' '}
            <a href={urlDoLogin({ returnTo: `/leads/${encodeURIComponent(leadId)}`, erro: 'sessao_expirada' })}>
              Entrar de novo
            </a>
          </>
        )}
      </p>
    </div>
  )
}

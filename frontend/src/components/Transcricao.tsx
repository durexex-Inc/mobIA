'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { RespostaDoCorretor } from '@/components/RespostaDoCorretor'
import { urlDoLogin } from '@/lib/destino'
import { dataAbsoluta } from '@/lib/leads'
import {
  type Fala,
  INTERVALO_DO_POLLING_MS,
  ladoDoAutor,
  type PaginaDaTranscricao,
  rotuloDoAutor,
  textoDaFala,
  urlDasAnteriores,
  urlDasPosteriores,
} from '@/lib/transcricao'

// Quantos pixels do fim ainda contam como "estava no fim" (TEC-327, D5): a
// rolagem de quem le a ultima fala raramente para no pixel exato.
const FOLGA_DO_FIM_PX = 40

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
 *
 * **Com `acompanhar`, busca as falas novas a cada 5 s** (TEC-327, D5): so
 * quando a conversa e de quem ve a tela, e so com a aba visivel. O backend so
 * grava o poll na trilha quando ele traz fala (D1 de la).
 *
 * **Com `resposta`, o campo em que o corretor responde fica embaixo** (TEC-328,
 * D3): habilitado so quando a conversa e de quem ve a tela -- o mesmo
 * `acompanhar` do polling. A fala enviada entra no fim da lista, e o polling
 * nao a duplica.
 */
export function Transcricao({
  leadId,
  inicial,
  acompanhar = false,
  resposta,
}: {
  leadId: string
  inicial: PaginaDaTranscricao
  acompanhar?: boolean
  /** So para quem pode responder (TEC-328). `janelaFechaEm` vem do detalhe. */
  resposta?: { janelaFechaEm: string | null }
}) {
  const [falas, setFalas] = useState<Fala[]>(inicial.itens)
  const [cursor, setCursor] = useState(inicial.cursorAnterior)
  const [estado, setEstado] = useState<Estado>('ocioso')
  const [aviso, setAviso] = useState('')
  const caixa = useRef<HTMLDivElement>(null)
  // A distancia entre o ponto de leitura e o fim do conteudo, guardada antes
  // de inserir as anteriores (D3). Nulo quando nao ha insercao pendente.
  const distanciaDoFim = useRef<number | null>(null)
  // O ponto de partida do proximo poll. Ref, e nao estado: trocar o cursor
  // nao deve reiniciar o intervalo.
  const posterior = useRef(inicial.cursorPosterior ?? null)
  // Se a pessoa estava no fim quando chegou fala nova (D5): so entao a
  // rolagem acompanha.
  const colarNoFim = useRef(false)

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
    if (elemento && colarNoFim.current) {
      elemento.scrollTop = elemento.scrollHeight
      colarNoFim.current = false
    }
  }, [falas])

  // O polling (TEC-327, D5). Falha comum tenta de novo no proximo ciclo, sem
  // aviso a cada 5 s; o 401 para, porque tentar de novo nao adianta.
  useEffect(() => {
    if (!acompanhar) {
      return
    }
    let parado = false
    let emVoo = false

    async function consultar() {
      const cursor = posterior.current
      if (parado || emVoo || !cursor || document.visibilityState !== 'visible') {
        return
      }
      emVoo = true
      try {
        const resposta = await fetch(urlDasPosteriores(leadId, cursor), {
          headers: { Accept: 'application/json' },
        })
        if (resposta.status === 401) {
          parar()
          setEstado('sessao')
          setAviso('Sua sessão terminou.')
          return
        }
        if (!resposta.ok || parado) {
          return
        }
        const pagina = (await resposta.json()) as PaginaDaTranscricao
        posterior.current = pagina.cursorPosterior ?? cursor
        if (pagina.itens.length === 0) {
          return
        }
        const elemento = caixa.current
        colarNoFim.current =
          !!elemento &&
          elemento.scrollHeight - elemento.scrollTop - elemento.clientHeight <= FOLGA_DO_FIM_PX
        setFalas((atuais) => {
          const vistas = new Set(atuais.map((fala) => fala.id))
          return [...atuais, ...pagina.itens.filter((fala) => !vistas.has(fala.id))]
        })
        setAviso(
          pagina.itens.length === 1
            ? '1 mensagem nova.'
            : `${pagina.itens.length} mensagens novas.`,
        )
      } catch {
        // Rede fora: o proximo ciclo tenta de novo.
      } finally {
        emVoo = false
      }
    }

    const intervalo = setInterval(consultar, INTERVALO_DO_POLLING_MS)
    // Voltando a ficar visivel, pergunta na hora: a aba pode ter passado
    // minutos escondida.
    const aoMudarVisibilidade = () => {
      if (document.visibilityState === 'visible') {
        void consultar()
      }
    }
    document.addEventListener('visibilitychange', aoMudarVisibilidade)

    function parar() {
      parado = true
      clearInterval(intervalo)
      document.removeEventListener('visibilitychange', aoMudarVisibilidade)
    }
    return parar
  }, [acompanhar, leadId])

  // A fala mais recente do lead que a tela tem: a que chega pelo polling
  // reabre a janela do WhatsApp (D2 da TEC-328).
  const ultimaFalaDoLeadEm = falas.findLast((fala) => fala.autor === 'LEAD')?.em ?? null

  function incluirEnviada(fala: Fala) {
    colarNoFim.current = true
    setFalas((atuais) => (atuais.some((f) => f.id === fala.id) ? atuais : [...atuais, fala]))
  }

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
      {/* A unica regiao viva: anuncia o que mudou com a tela aberta -- o
          carregamento das anteriores (D5 da TEC-324) e, com a conversa
          assumida, a mensagem nova (D5 da TEC-327). */}
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
      {resposta && (
        <RespostaDoCorretor
          leadId={leadId}
          conversaMinha={acompanhar}
          janelaFechaEm={resposta.janelaFechaEm}
          ultimaFalaDoLeadEm={ultimaFalaDoLeadEm}
          aoEnviar={incluirEnviada}
        />
      )}
    </div>
  )
}

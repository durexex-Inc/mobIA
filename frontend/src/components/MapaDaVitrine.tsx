'use client'

import 'leaflet/dist/leaflet.css'

import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

import { reais } from '@/lib/imovel'
import { ORIGEM_DOS_TILES } from '@/lib/mapa'
import { precoCurto } from '@/lib/vitrine'

export type PontoDoMapa = {
  id: string
  titulo: string
  bairro: string
  latitude: number
  longitude: number
  preco: number
}

const ZOOM_DE_UM_PONTO = 15

/**
 * O mapa da vitrine com o preco de cada imovel da pagina (visual do portal,
 * D8). Leaflet sobre os tiles do OpenStreetMap -- a CSP do portal libera
 * `ORIGEM_DOS_TILES` em `img-src` (`proxy.ts`).
 *
 * **Leaflet por `import()` dentro do efeito, e nao no topo do modulo**: ele
 * le `window` ao ser carregado, e o modulo tambem roda no servidor para o
 * HTML inicial. No servidor o mapa e so a caixa vazia; o Leaflet chega no
 * navegador.
 *
 * **O pino e montado como elemento, com `textContent`**, e nao como string de
 * HTML no `divIcon`: o preco e numero formatado, mas `html: string` e
 * `innerHTML`, e este componente nao vai depender de o valor ser inofensivo.
 * Nenhum `style=` tambem -- o Leaflet posiciona pelo CSSOM, que a CSP nao
 * bloqueia; a aparencia do pino e toda de `.portal-pino` no `globals.css`.
 *
 * Clicar num pino seleciona o imovel: o pino fica marcado, um resumo aparece
 * sobre o mapa e o card correspondente na lista ganha destaque e rola ate a
 * vista.
 */
export function MapaDaVitrine({ pontos }: { pontos: PontoDoMapa[] }) {
  const caixa = useRef<HTMLDivElement>(null)
  const [selecionado, setSelecionado] = useState<string | null>(null)
  const chave = pontos.map((ponto) => ponto.id).join(',')

  useEffect(() => {
    if (!caixa.current || pontos.length === 0) {
      return
    }
    let mapa: import('leaflet').Map | null = null
    let cancelado = false

    void import('leaflet').then((L) => {
      if (cancelado || !caixa.current) {
        return
      }
      mapa = L.map(caixa.current, { scrollWheelZoom: false })
      L.tileLayer(`${ORIGEM_DOS_TILES}/{z}/{x}/{y}.png`, {
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(mapa)

      // A vista ANTES dos marcadores: sem vista, o Leaflet adia a montagem de
      // cada camada, e `getElement()` logo abaixo devolveria `undefined` -- o
      // pino ficaria sem `data-ponto` e o destaque do escolhido nao o acharia.
      if (pontos.length === 1) {
        mapa.setView([pontos[0].latitude, pontos[0].longitude], ZOOM_DE_UM_PONTO)
      } else {
        mapa.fitBounds(
          L.latLngBounds(pontos.map((ponto) => [ponto.latitude, ponto.longitude] as [number, number])),
          { padding: [40, 40] },
        )
      }

      for (const ponto of pontos) {
        const rotulo = document.createElement('span')
        rotulo.className = 'portal-pino__rotulo'
        rotulo.textContent = precoCurto(ponto.preco)
        const marcador = L.marker([ponto.latitude, ponto.longitude], {
          icon: L.divIcon({ className: 'portal-pino', html: rotulo, iconSize: undefined }),
          title: ponto.titulo,
          keyboard: true,
        }).addTo(mapa)
        marcador.on('click', () => setSelecionado(ponto.id))
        marcador.getElement()?.setAttribute('data-ponto', ponto.id)
      }
    })

    return () => {
      cancelado = true
      mapa?.remove()
    }
    // `chave` resume `pontos`: a lista chega nova a cada render do servidor,
    // e refazer o mapa so faz sentido quando os imoveis mudam.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave])

  // O destaque no pino e no card e so classe: os dois elementos nao sao
  // deste componente (um e do Leaflet, o outro do Server Component da lista).
  useEffect(() => {
    document.querySelectorAll('[data-ponto].portal-pino--ativo, .portal-card--ativo').forEach((elemento) => {
      elemento.classList.remove('portal-pino--ativo', 'portal-card--ativo')
    })
    if (!selecionado) {
      return
    }
    document.querySelector(`[data-ponto="${CSS.escape(selecionado)}"]`)?.classList.add('portal-pino--ativo')
    const card = document.getElementById(`imovel-${selecionado}`)
    card?.classList.add('portal-card--ativo')
    card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [selecionado])

  if (pontos.length === 0) {
    return (
      <div className="portal-mapa-vitrine portal-mapa-vitrine--vazio">
        <p>Nenhum imóvel desta página tem localização cadastrada.</p>
      </div>
    )
  }

  const escolhido = pontos.find((ponto) => ponto.id === selecionado)
  return (
    <div className="portal-mapa-vitrine">
      <div ref={caixa} className="portal-mapa-vitrine__mapa" role="region" aria-label="Mapa dos imóveis desta página" />
      {escolhido && (
        <div className="portal-mapa-vitrine__resumo">
          <div>
            <strong>{reais(escolhido.preco)}</strong>
            <span>{escolhido.titulo}</span>
            <span className="portal-mapa-vitrine__bairro">{escolhido.bairro}</span>
          </div>
          <Link href={`/busca/${escolhido.id}`} className="portal-botao portal-botao--primario">
            Ver imóvel
          </Link>
          <button
            type="button"
            className="portal-mapa-vitrine__fechar"
            aria-label="Fechar resumo"
            onClick={() => setSelecionado(null)}
          >
            ×
          </button>
        </div>
      )}
      <p className="portal-nota portal-mapa-vitrine__nota">Posições aproximadas, para indicar a vizinhança.</p>
    </div>
  )
}

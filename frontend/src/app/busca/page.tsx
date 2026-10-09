import type { Metadata } from 'next'
import Link from 'next/link'

import { CardDaVitrine } from '@/components/CardDaVitrine'
import { FormularioDeBuscaPublica } from '@/components/FormularioDeBuscaPublica'
import { MapaDaVitrine, type PontoDoMapa } from '@/components/MapaDaVitrine'
import { OrdenacaoDaVitrine } from '@/components/OrdenacaoDaVitrine'
import { filtrosDaUrl, type FiltrosDoPortal, urlDaBusca } from '@/lib/buscaPublica'
import { reais } from '@/lib/imovel'
import { TIPOS_DE_IMOVEL } from '@/lib/imoveis'
import { buscarVitrine } from '@/lib/servidor/vitrinePublica'
import { paginasVisiveis, totalDePaginas } from '@/lib/vitrine'

export const metadata: Metadata = {
  title: 'Buscar imóveis',
  description: 'Filtre o catálogo de imóveis disponíveis.',
}

/**
 * O portal publico de busca (TEC-387), no visual de vitrine do portal (D7 e
 * D8 do desenho): barra de filtros, lista paginada de cards e, no desktop, o
 * mapa com o preco de cada imovel da pagina. Pagina publica, fora de
 * `(painel)` e de `embed/`: sem `exigirPermissao` nem `quemSou`.
 *
 * **Os filtros vivem na URL** (D5 da TEC-387), agora com ordem e pagina: a
 * tela e Server Component, le `searchParams`, busca no servidor e desenha o
 * resultado. Estado de cliente, so o do formulario, o da ordenacao e o do
 * mapa.
 *
 * **CA-03.** Sem item nenhum, a mensagem substitui a lista -- nunca uma lista
 * vazia muda. **CA-04** ja esta garantido pelo backend (RN-08.4): so chega
 * aqui o que esta `DISPONIVEL`.
 */
export default async function BuscaPublica({ searchParams }: PageProps<'/busca'>) {
  const filtros = filtrosDaUrl(await searchParams)
  const vitrine = await buscarVitrine(filtros)
  const aluguel = filtros.operacao === 'ALUGUEL'
  const ultima = totalDePaginas(vitrine.total, vitrine.porPagina)
  const primeiroDaPagina = (vitrine.pagina - 1) * vitrine.porPagina + 1
  const pontos: PontoDoMapa[] = vitrine.itens.flatMap((imovel) =>
    imovel.latitude !== null && imovel.longitude !== null
      ? [
          {
            id: imovel.id,
            titulo: imovel.titulo,
            bairro: imovel.bairro,
            latitude: imovel.latitude,
            longitude: imovel.longitude,
            preco: imovel.preco,
          },
        ]
      : [],
  )

  return (
    <main className="portal portal--vitrine">
      <header className="portal-topo">
        <div className="portal-topo__conteudo">
          <span className="portal-topo__marca">Imóveis</span>
        </div>
      </header>

      <section className="portal-barra-de-filtros" aria-label="Filtros">
        <div className="portal-barra-de-filtros__conteudo">
          <FormularioDeBuscaPublica filtros={filtros} />
        </div>
      </section>

      <div className="portal-pagina portal-vitrine">
        <div className="portal-vitrine__cabecalho">
          <div>
            <h1 className="portal-titulo">{tituloDaBusca(filtros)}</h1>
            <p className="portal-nota" role="status">
              {vitrine.total === 1
                ? '1 imóvel disponível'
                : `${vitrine.total.toLocaleString('pt-BR')} imóveis disponíveis`}
            </p>
          </div>
          <OrdenacaoDaVitrine filtros={filtros} />
        </div>

        <FiltrosAplicados filtros={filtros} />

        <div className="portal-vitrine__corpo">
          <div className="portal-vitrine__lista">
            {vitrine.itens.length > 0 ? (
              <>
                {vitrine.itens.map((imovel) => (
                  <CardDaVitrine key={imovel.id} imovel={imovel} aluguel={aluguel} />
                ))}
                <nav className="portal-paginacao" aria-label="Paginação">
                  <p>
                    Mostrando {primeiroDaPagina}–{primeiroDaPagina + vitrine.itens.length - 1} de{' '}
                    {vitrine.total.toLocaleString('pt-BR')}
                  </p>
                  {ultima > 1 && (
                    <ol>
                      {paginasVisiveis(vitrine.pagina, ultima).map((pagina, indice) =>
                        pagina === null ? (
                          <li key={`salto-${indice}`} aria-hidden="true">
                            …
                          </li>
                        ) : (
                          <li key={pagina}>
                            <Link
                              href={urlDaBusca({ ...filtros, pagina })}
                              aria-current={pagina === vitrine.pagina ? 'page' : undefined}
                              aria-label={`Página ${pagina}`}
                            >
                              {pagina}
                            </Link>
                          </li>
                        ),
                      )}
                    </ol>
                  )}
                </nav>
              </>
            ) : vitrine.total > 0 ? (
              <div className="portal-cartao portal-vitrine__vazio" role="status">
                <p>Esta página não existe mais: a lista tem {ultima} página(s).</p>
                <Link className="portal-link" href={urlDaBusca({ ...filtros, pagina: undefined })}>
                  Ir para a primeira página
                </Link>
              </div>
            ) : (
              <div className="portal-cartao portal-vitrine__vazio" role="status">
                <p>Nenhum imóvel encontrado com esses filtros.</p>
                <Link className="portal-link" href={urlDaBusca({ operacao: filtros.operacao })}>
                  Limpar os filtros
                </Link>
              </div>
            )}
          </div>

          {vitrine.itens.length > 0 && (
            <aside className="portal-vitrine__mapa" aria-label="Mapa">
              <MapaDaVitrine pontos={pontos} />
            </aside>
          )}
        </div>
      </div>
    </main>
  )
}

function tituloDaBusca(filtros: FiltrosDoPortal): string {
  const base = filtros.operacao === 'ALUGUEL' ? 'Imóveis para alugar' : 'Imóveis à venda'
  return filtros.regioes && filtros.regioes.length > 0 ? `${base} em ${filtros.regioes.join(', ')}` : base
}

/**
 * Os filtros em uso, cada um com o link que o tira -- a referencia mostra
 * etiquetas removiveis acima da lista. Sao links, e nao botoes: tirar um
 * filtro e so outra URL, e funciona sem JS.
 */
function FiltrosAplicados({ filtros }: { filtros: FiltrosDoPortal }) {
  const semPagina = { ...filtros, pagina: undefined }
  const aplicados: { rotulo: string; sem: FiltrosDoPortal }[] = []
  if (filtros.tipo) {
    aplicados.push({ rotulo: TIPOS_DE_IMOVEL[filtros.tipo], sem: { ...semPagina, tipo: undefined } })
  }
  if (filtros.precoMinCentavos !== undefined || filtros.precoMaxCentavos !== undefined) {
    const minimo = filtros.precoMinCentavos !== undefined ? reais(filtros.precoMinCentavos) : null
    const maximo = filtros.precoMaxCentavos !== undefined ? reais(filtros.precoMaxCentavos) : null
    aplicados.push({
      rotulo: minimo && maximo ? `${minimo} a ${maximo}` : minimo ? `A partir de ${minimo}` : `Até ${maximo}`,
      sem: { ...semPagina, precoMinCentavos: undefined, precoMaxCentavos: undefined },
    })
  }
  if (filtros.quartosMin !== undefined) {
    aplicados.push({ rotulo: `${filtros.quartosMin}+ quartos`, sem: { ...semPagina, quartosMin: undefined } })
  }
  if (filtros.vagasMin !== undefined) {
    aplicados.push({ rotulo: `${filtros.vagasMin}+ vagas`, sem: { ...semPagina, vagasMin: undefined } })
  }
  for (const regiao of filtros.regioes ?? []) {
    aplicados.push({
      rotulo: regiao,
      sem: { ...semPagina, regioes: filtros.regioes?.filter((outra) => outra !== regiao) },
    })
  }
  if (aplicados.length === 0) {
    return null
  }
  return (
    <div className="portal-aplicados">
      <span>Filtros aplicados:</span>
      <ul>
        {aplicados.map(({ rotulo, sem }) => (
          <li key={rotulo}>
            <Link href={urlDaBusca(sem)} aria-label={`Remover o filtro ${rotulo}`}>
              {rotulo}
              <span aria-hidden="true"> ×</span>
            </Link>
          </li>
        ))}
      </ul>
      <Link className="portal-link" href={urlDaBusca({ operacao: filtros.operacao, ordem: filtros.ordem })}>
        Limpar filtros
      </Link>
    </div>
  )
}

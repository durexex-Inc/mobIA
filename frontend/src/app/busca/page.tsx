import type { Metadata } from 'next'

import { CardDeImovel } from '@/components/CardDeImovel'
import { FormularioDeBuscaPublica } from '@/components/FormularioDeBuscaPublica'
import { filtrosDaUrl } from '@/lib/buscaPublica'
import { buscarVitrinePublica } from '@/lib/servidor/vitrinePublica'

export const metadata: Metadata = {
  title: 'Buscar imóveis',
  description: 'Filtre o catálogo de imóveis disponíveis.',
}

/**
 * O portal publico de busca (TEC-387). Pagina publica, fora de `(painel)` e
 * de `embed/`, no molde de `embed/chat/page.tsx`: sem `exigirPermissao` nem
 * `quemSou`, busca anonima.
 *
 * **Os filtros vivem na URL** (D5 do desenho): a tela e Server Component, lê
 * `searchParams`, busca no servidor e desenha o resultado -- sem estado de
 * cliente nenhum alem do formulario, que so navega.
 *
 * **CA-03.** Sem item nenhum, a mensagem substitui a grade -- nunca uma grade
 * vazia muda. **CA-04** já está garantido pelo backend (RN-08.4): só chega
 * aqui o que está `DISPONIVEL`.
 */
export default async function BuscaPublica({ searchParams }: PageProps<'/busca'>) {
  const parametros = await searchParams
  const filtros = filtrosDaUrl(parametros)
  const resultado = await buscarVitrinePublica(filtros)

  return (
    <main className="busca-publica">
      <h1>Buscar imóveis</h1>
      <FormularioDeBuscaPublica filtros={filtros} />
      {resultado.itens.length === 0 ? (
        <p className="busca-publica__vazio" role="status">
          Nenhum imóvel encontrado com esses filtros.
        </p>
      ) : (
        <>
          {resultado.totalCandidatos > resultado.itens.length ? (
            <p className="busca-publica__nota" role="status">
              Mostrando os {resultado.itens.length} mais relevantes de {resultado.totalCandidatos}.
            </p>
          ) : null}
          <div className="busca-publica__grade">
            {resultado.itens.map((imovel) => (
              <CardDeImovel key={imovel.id} imovel={imovel} />
            ))}
          </div>
        </>
      )}
    </main>
  )
}

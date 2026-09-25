import { Skeleton } from '@/components/estado/Skeleton'

/**
 * O estado "carregando" da rota (TEC-313, RN-FE-04.1).
 *
 * Ate esta card o painel nao tinha carregamento nenhum: `page.tsx` e Server
 * Component e faz `await buscarFunil(...)` antes de renderizar, entao o que
 * existia no lugar era a tela ANTERIOR, parada, ate a nova chegar.
 *
 * **O atraso de 300 ms e do CSS, nao deste arquivo.** Ver `.skeleton` em
 * `globals.css` e a D2 do desenho -- o Next mostra este componente
 * instantaneamente, e e a animacao que o mantem invisivel enquanto a resposta
 * ainda pode chegar rapido.
 *
 * `aria-busy` aqui e nao no `Skeleton`: quem esta ocupada e a regiao, e o
 * esqueleto e so o desenho dela. O `aria-hidden` do esqueleto e o outro lado
 * do mesmo par -- sem conteudo a anunciar, ele nao deve ser lido.
 */
export default function Carregando() {
  return (
    <main className="painel" aria-busy="true" aria-label="Carregando o painel de funil">
      <h1>Funil de leads</h1>
      <Skeleton linhas={6} />
    </main>
  )
}

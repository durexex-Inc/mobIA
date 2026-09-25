/**
 * O esqueleto de carregamento (TEC-313, RN-FE-04.1).
 *
 * **Ele fica invisivel pelos primeiros 300 ms, e quem faz isso e o CSS.** A
 * regra da card e "skeleton a partir de 300 ms", e o `loading.tsx` do Next
 * mostra a UI de carregamento INSTANTANEAMENTE -- e o que a referencia
 * empacotada chama de *instant loading state*. Atrasar com JS exigiria
 * `'use client'`, `useState` e `setTimeout`: hidratacao inteira para NAO
 * mostrar uma coisa.
 *
 * Com `animation-delay` (ver `.skeleton` em `globals.css`) o elemento existe no
 * HTML desde o primeiro byte e so fica visivel aos 300 ms. Resposta em 120 ms
 * nao produz flash nenhum -- que e a razao de a regra existir. Ver a D2.
 *
 * `aria-hidden` porque o esqueleto nao tem conteudo a anunciar; quem avisa o
 * leitor de tela e o `aria-busy` de quem o contem.
 */
export function Skeleton({ linhas = 3 }: { linhas?: number }) {
  return (
    <div className="skeleton" aria-hidden="true" data-testid="skeleton">
      {Array.from({ length: linhas }, (_, indice) => (
        <div key={indice} className="skeleton-linha" />
      ))}
    </div>
  )
}

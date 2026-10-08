/**
 * A trilha de navegacao (TEC-395) -- o "Breadcrumb" do shadcn. O ultimo item
 * e a pagina atual: sem link, com `aria-current`.
 */
export function Trilha({ itens }: { itens: Array<{ rotulo: string; href?: string }> }) {
  return (
    <nav aria-label="Trilha" className="trilha">
      <ol>
        {itens.map((item, indice) => {
          const atual = indice === itens.length - 1
          return (
            <li key={item.rotulo}>
              {atual || !item.href ? (
                <span aria-current={atual ? 'page' : undefined}>{item.rotulo}</span>
              ) : (
                <a href={item.href}>{item.rotulo}</a>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

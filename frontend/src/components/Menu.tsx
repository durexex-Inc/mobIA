import { itensDoMenu, nomeDoPapel } from '@/lib/navegacao'
import type { QuemSou } from '@/lib/servidor/quemSou'

/**
 * O menu do painel (TEC-312, D1).
 *
 * **Esconder item e conveniencia, nao seguranca** (RN-FE-03.3). Quem digita o
 * endereco de uma area escondida chega a pagina, e e a pagina que confere a
 * permissao (`exigirPermissao`). O menu so poupa a pessoa de tropecar numa
 * tela que ela nao pode usar.
 *
 * Recebe `QuemSou` e nao o busca: e Server Component sem estado, e quem busca
 * e o layout -- assim o teste o renderiza com qualquer papel sem dublar rede.
 */
export function Menu({ quem }: { quem: QuemSou }) {
  const itens = itensDoMenu(quem.permissoes)
  return (
    <header className="menu">
      <nav aria-label="Menu principal">
        <ul>
          {itens.map((item) => (
            <li key={item.href}>
              <a href={item.href}>{item.rotulo}</a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="menu-conta">
        <p className="menu-papel">{nomeDoPapel(quem.papel)}</p>
        {/* Formulario, e nao link: sair e POST (TEC-310, D6). Sem JavaScript --
            o painel so tem JS de cliente onde nao ha alternativa: o aviso de
            inatividade (TEC-311), a busca da lista de leads (TEC-321) e a
            conversa do lead (TEC-324). */}
        <form method="post" action="/sair">
          <button type="submit">Sair</button>
        </form>
      </div>
    </header>
  )
}

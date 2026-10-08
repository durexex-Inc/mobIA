import { BotaoDeTema } from '@/components/BotaoDeTema'
import { LinkDoMenu } from '@/components/LinkDoMenu'
import { Botao } from '@/components/ui/Botao'
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
      <div className="menu-conteudo">
        <nav aria-label="Menu principal">
          <ul>
            {itens.map((item) => (
              <li key={item.href}>
                <LinkDoMenu href={item.href}>{item.rotulo}</LinkDoMenu>
              </li>
            ))}
          </ul>
        </nav>
        <div className="menu-conta">
          <p className="menu-papel">
            <span className="ponto-de-status" aria-hidden="true" />
            {nomeDoPapel(quem.papel)}
          </p>
          <BotaoDeTema />
          {/* Formulario, e nao link: sair e POST (TEC-310, D6). Sem JavaScript --
              o painel so tem JS de cliente onde nao ha alternativa: o aviso de
              inatividade (TEC-311), a busca da lista de leads (TEC-321), a
              conversa do lead (TEC-324) e o controle dela (TEC-327), o item
              ativo do menu e o botao de tema (TEC-393). */}
          <form method="post" action="/sair">
            <Botao type="submit" variante="contorno" tamanho="pequeno">
              Sair
            </Botao>
          </form>
        </div>
      </div>
    </header>
  )
}

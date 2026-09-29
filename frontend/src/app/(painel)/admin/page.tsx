import type { Metadata } from 'next'

import { SemPermissao } from '@/components/SemPermissao'
import { paginaInicialDe, podeVerAdmin } from '@/lib/navegacao'
import { exigirPermissao } from '@/lib/servidor/quemSou'

export const metadata: Metadata = {
  title: 'Administração — mobIA',
}

/**
 * As secoes previstas da area de administracao, e a card de cada uma.
 *
 * **A que ainda nao existe diz isso** (D5 do desenho, decisao de
 * 26/09/2026); a primeira a existir foi a fila do titular (TEC-340). A pagina
 * e so de navegacao: nao busca dado nenhum. Quando a tela de uma secao chega,
 * a linha dela ganha o `href`, e a pagina da secao chama `exigirPermissao` com
 * a permissao que ela exerce -- a guarda desta pagina NAO a protege (D3).
 */
const SECOES: ReadonlyArray<{ nome: string; card: string; href?: string }> = [
  { nome: 'Prompts do agente', card: 'TEC-338', href: '/admin/prompts' },
  { nome: 'Configuração do agente', card: 'TEC-337', href: '/admin/configuracao' },
  { nome: 'Corretores', card: 'TEC-332', href: '/admin/corretores' },
  { nome: 'Imóveis', card: 'TEC-333', href: '/admin/imoveis' },
  { nome: 'Trilha de auditoria', card: 'TEC-343', href: '/admin/auditoria' },
  { nome: 'Pedidos do titular', card: 'TEC-340', href: '/admin/titular' },
]

export default async function PaginaDeAdministracao() {
  // A guarda vem antes de tudo: e o cenario 2 do Gherkin ("nenhum dado
  // administrativo e carregado"). Hoje a pagina nao carrega dado nenhum, e a
  // guarda esta aqui mesmo assim -- e a primeira pagina da area, e as proximas
  // copiam o molde dela.
  const { quem, permitido } = await exigirPermissao('/admin', podeVerAdmin)
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe(quem.permissoes)} />
  }

  return (
    <main className="painel">
      <h1>Administração</h1>
      <ul className="admin-secoes">
        {SECOES.map((secao) => (
          <li key={secao.nome}>
            {secao.href ? (
              <a href={secao.href}>{secao.nome}</a>
            ) : (
              <>
                <span>{secao.nome}</span> <span className="admin-em-breve">ainda não disponível</span>
              </>
            )}
          </li>
        ))}
      </ul>
    </main>
  )
}

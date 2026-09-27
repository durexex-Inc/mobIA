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
 * **Nenhuma existe ainda, e a pagina diz isso** (D5 do desenho, decisao de
 * 26/09/2026). Ela e so de navegacao: nao busca dado nenhum. Quando a tela de
 * uma secao chegar, a linha dela ganha o `href`, e a pagina da secao chama
 * `exigirPermissao` com a permissao que ela exerce -- a guarda desta pagina
 * NAO a protege (D3).
 */
const SECOES: ReadonlyArray<{ nome: string; card: string; href?: string }> = [
  { nome: 'Prompts do agente', card: 'TEC-338' },
  { nome: 'Configuração do agente', card: 'TEC-337' },
  { nome: 'Corretores', card: 'TEC-332' },
  { nome: 'Imóveis', card: 'TEC-333' },
  { nome: 'Trilha de auditoria', card: 'TEC-343' },
]

export default async function PaginaDeAdministracao() {
  // A guarda vem antes de tudo: e o cenario 2 do Gherkin ("nenhum dado
  // administrativo e carregado"). Hoje a pagina nao carrega dado nenhum, e a
  // guarda esta aqui mesmo assim -- e a primeira pagina da area, e as proximas
  // copiam o molde dela.
  const { quem, permitido } = await exigirPermissao('/admin', podeVerAdmin)
  if (!permitido) {
    return <SemPermissao papel={quem.papel} paginaInicial={paginaInicialDe()} />
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

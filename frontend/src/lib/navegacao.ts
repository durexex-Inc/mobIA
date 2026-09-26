/**
 * O menu do painel, decidido pelas permissoes de quem esta logado (TEC-312).
 *
 * Funcao pura e sem `server-only`: nao le segredo nenhum. As permissoes chegam
 * de `GET /auth/me` (ver `lib/servidor/quemSou.ts`); nada aqui decodifica JWT.
 */

/**
 * As permissoes que abrem a area de administracao.
 *
 * "Qualquer uma de", e nao todas: a area agrupa telas de permissoes diferentes
 * -- prompts e configuracao pedem `CONFIGURAR_AGENTE`, a trilha pede
 * `VER_AUDITORIA`. Hoje as cinco sao so do ADMIN pela matriz da TEC-202, entao
 * ninguem ganha o item por acidente.
 */
export const PERMISSOES_DE_ADMIN = [
  'CONFIGURAR_AGENTE',
  'GERIR_CATALOGO',
  'GERIR_CORRETORES',
  'VER_AUDITORIA',
  'OPERAR_FILA',
] as const

export type ItemDoMenu = { rotulo: string; href: string }

/**
 * Os itens, cada um com a permissao que o torna visivel (D1 do desenho).
 *
 * **Pergunta pela permissao, e nunca pelo papel.** Um `papel === 'ADMIN'`
 * aqui seria uma segunda copia da matriz de `domain/usuarios/permissoes.py`,
 * livre para divergir dela. Perguntando pela permissao, o menu muda sozinho
 * quando a matriz mudar.
 */
const ITENS: ReadonlyArray<ItemDoMenu & { visivel: (permissoes: ReadonlySet<string>) => boolean }> =
  [
    { rotulo: 'Funil', href: '/', visivel: (p) => p.has('VER_FUNIL') },
    { rotulo: 'Administração', href: '/admin', visivel: podeVerAdmin },
  ]

export function podeVerAdmin(permissoes: ReadonlySet<string>): boolean {
  return PERMISSOES_DE_ADMIN.some((permissao) => permissoes.has(permissao))
}

export function itensDoMenu(permissoes: ReadonlySet<string>): ItemDoMenu[] {
  return ITENS.filter((item) => item.visivel(permissoes)).map(({ rotulo, href }) => ({
    rotulo,
    href,
  }))
}

/**
 * O nome do papel para quem le a tela.
 *
 * `CORRETOR` e identificador de sistema; a pessoa se reconhece em "Corretor".
 * Papel desconhecido aparece como veio, e nao como "desconhecido": e anomalia
 * que alguem vai precisar investigar, e o valor cru e a pista.
 */
const NOMES_DOS_PAPEIS: Record<string, string> = {
  ADMIN: 'Administrador',
  GERENTE: 'Gerente',
  CORRETOR: 'Corretor',
  LEITURA: 'Leitura',
}

export function nomeDoPapel(papel: string): string {
  return NOMES_DOS_PAPEIS[papel] ?? papel
}

/**
 * A pagina inicial. `/` para todos os papeis, por enquanto (D6 do desenho).
 *
 * Para o CORRETOR, `/` mostra "Sem permissao": a tela dele e a lista de leads
 * (TEC-321), que ainda nao existe. Quando existir, esta funcao passa a receber
 * o papel e a devolver a tela de cada um -- e os chamadores ja estao todos
 * aqui, em vez de um `'/'` literal espalhado por pagina.
 */
export function paginaInicialDe(): string {
  return '/'
}

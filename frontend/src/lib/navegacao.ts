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
 * `VER_AUDITORIA`, a fila do titular pede `ATENDER_TITULAR` (TEC-340). Hoje as
 * seis sao so do ADMIN pela matriz da TEC-202, entao ninguem ganha o item por
 * acidente.
 */
export const PERMISSOES_DE_ADMIN = [
  'CONFIGURAR_AGENTE',
  'GERIR_CATALOGO',
  'GERIR_CORRETORES',
  'VER_AUDITORIA',
  'OPERAR_FILA',
  'ATENDER_TITULAR',
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
    { rotulo: 'Leads', href: '/leads', visivel: (p) => p.has('VER_LEADS') },
    // Mesma permissao da rota (TEC-404): `GET /api/v1/interesses` exige `VER_LEADS`.
    { rotulo: 'Pedidos de interesse', href: '/interesses', visivel: (p) => p.has('VER_LEADS') },
    // Mesma permissao do funil (TEC-319): a rota de custo tambem exige
    // `VER_FUNIL` (`metricas.py::custo_de_ia`).
    { rotulo: 'Custo de IA', href: '/custo-ia', visivel: (p) => p.has('VER_FUNIL') },
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
 * A pagina inicial de quem tem estas permissoes (TEC-321, D2).
 *
 * O funil para quem o ve; a lista de leads para quem so ve a lista -- hoje, o
 * CORRETOR. Sem nenhuma das duas, `/`, que mostra "Sem permissao".
 *
 * **O login nao usa esta funcao**: ele redireciona antes de ler `/auth/me`, e
 * manda todo mundo para `PAGINA_INICIAL` (`lib/destino.ts`). Quem leva o
 * CORRETOR do `/` para `/leads` e a pagina do funil, com esta mesma regra.
 */
export function paginaInicialDe(permissoes: ReadonlySet<string>): string {
  if (!permissoes.has('VER_FUNIL') && permissoes.has('VER_LEADS')) {
    return '/leads'
  }
  return '/'
}

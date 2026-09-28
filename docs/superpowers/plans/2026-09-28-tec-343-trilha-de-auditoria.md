# TEC-343 — Plano: consultar a trilha de auditoria

Desenho: `docs/superpowers/specs/2026-09-28-tec-343-trilha-de-auditoria-design.md`. Só frontend: `GET /api/v1/auditoria` já existe (TEC-206).

## Passos

- [x] **`lib/auditoria.ts`**: tipos (`EventoDaTrilha`, `FiltrosDaTrilha`, `PosicaoNaTrilha`), `ACOES`/`ENTIDADES` legíveis, `filtrosDaUrl`/`urlDaLista`, `inicioDoDia`/`fimDoDia`, `posicaoDaUrl`/`posicaoDaProxima`, formatação de data.
- [x] **`lib/servidor/auditoria.ts`**: `buscarTrilha` (uma página) e `buscarPaginas` (acumula em paralelo), no molde de `lib/servidor/leads.ts`.
- [x] **`components/FiltrosDeAuditoria.tsx`**: form GET (ator, tipo, de, até), aplica no `onChange`.
- [x] **`components/TabelaDeAuditoria.tsx`**: a lista, sem nenhuma ação por linha.
- [x] **`components/PaginacaoDaAuditoria.tsx`**: só "Carregar mais".
- [x] **`app/(painel)/admin/auditoria/page.tsx`**: guarda `VER_AUDITORIA`, busca, filtros + tabela + paginação, 401/403/erro.
- [x] **`admin/page.tsx`**: `href: '/admin/auditoria'` na seção "Trilha de auditoria"; atualizado `admin/page.test.tsx` (contagem de "ainda não disponível" e o novo link).
- [x] **Testes**: os módulos puros; a página (guarda, filtro por ator, filtro por `ACESSO_NEGADO`, sem ação por linha, "Carregar mais", 401, erro).
- [x] **Gates**: os três do Python, `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: sessão ADMIN, `/admin/auditoria` com dados reais, filtro por tipo (`ACESSO_NEGADO` gerado de verdade) e por autor, link em `/admin`.

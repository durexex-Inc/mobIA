# TEC-322 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-322-filtrar-e-paginar-design.md`. Só frontend, mais o teste de vocabulário. Node 24 (ver o plano da TEC-309).

1. `lib/leads.ts`: `EstadoDaLista`, `estadoDaUrl`, `urlDaLista` com o estado inteiro, URLs de página (próxima, anterior k, acumulada) e os mapas de status, temperatura e canal exportados. Unitários primeiro.
2. `tests/unit/test_vocabulario_da_tela.py`: `STATUS`, `TEMPERATURAS` e `CANAIS` contra o backend.
3. `lib/servidor/leads.ts`: `buscarLeads` com filtros e cursor; `buscarPaginas`, para o acumulado em paralelo; `buscarCorretores`.
4. `components/FiltrosDeLeads.tsx` e `components/PaginacaoDeLeads.tsx`; `TabelaDeLeads` com `data-rotulo` e as linhas de páginas anteriores marcadas; CSS das duas larguras (D2 a D5).
5. A página junta tudo; a busca e os cabeçalhos preservam o estado.
6. Testes das páginas e dos componentes; README; gates dos dois lados; ponta a ponta com mais de 25 leads.
7. Commit, push, PR, comentário na card e "Em análise".

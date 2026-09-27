# TEC-321 — plano

Desenho: `docs/superpowers/specs/2026-09-26-tec-321-lista-de-leads-design.md`. Node 24 (ver o plano da TEC-309).

1. Backend: `Ordem` e o cursor com a ordem em `domain/leads/consulta.py`, unitários primeiro (D4).
2. Backend: a segunda ordem e o keyset dela em `domain/leads/repositorio.py`; `ordenar` na rota; integração (ordem, paginação, cursor trocado).
3. Emenda E-02 à seção 6.2 do SRS.
4. `lib/leads.ts`: `buscarLeads` (no-store), os rótulos e o tempo relativo (D6, D7).
5. `lib/navegacao.ts`: item "Leads" e `paginaInicialDe(permissoes)` (D1, D2).
6. `components/BuscaDeLeads.tsx`, com debounce e mínimo de 2 caracteres (D5).
7. `app/(painel)/leads/page.tsx` e os estados (D3, D8); o funil redireciona o CORRETOR (D2).
8. Gates: Python (ruff, format, mypy, suíte), frontend (test, lint, build, verificar:bundle), `comentarios_tocados.py --checar`.
9. Commit, push, PR, comentário na card e "Em análise".

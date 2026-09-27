# TEC-312 — plano

Desenho: `docs/superpowers/specs/2026-09-26-tec-312-menu-por-papel-design.md`. Node 24 (ver o plano da TEC-309). Linha de base: 208 testes no frontend.

1. `lib/navegacao.ts` — itens do menu por permissão, `podeVerAdmin`, nomes dos papéis, `paginaInicialDe` (D1, D6). Função pura, com um teste por linha da tabela do Gherkin.
2. `lib/servidor/quemSou.ts` — `GET /api/v1/auth/me` com o JWT da sessão, sob o `cache` do React; `exigirPermissao` (D2, D3).
3. `components/SemPermissao.tsx` e `components/Menu.tsx` (D4).
4. Grupo `app/(painel)/`: mover `page.tsx`, `page.test.tsx` e `loading.tsx`; `layout.tsx` com o menu (D7).
5. O funil: sem `VER_FUNIL`, `SemPermissao` antes de buscar; o 403 do backend vira `SemPermissao` (D4, D6).
6. `app/(painel)/admin/page.tsx` — o índice (D5).
7. Gates do frontend, suíte do Python (nada muda lá, mas é a regra), ponta a ponta com um usuário por papel.
8. Commit, push, PR, comentário na card e "Em análise".

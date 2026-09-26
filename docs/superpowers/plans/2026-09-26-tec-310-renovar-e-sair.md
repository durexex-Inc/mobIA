# TEC-310 — plano

Desenho: `docs/superpowers/specs/2026-09-26-tec-310-renovar-e-sair-design.md`. Node 24. Linha de base: 231 testes no frontend.

1. `armazem.ts`: `gravarSeAusente` (`SET NX EX`); o armazém em memória também.
2. `sessao.ts`: `acessoExpiraEm` a partir da claim `exp`; `obterSessaoValida` com a renovação e o lock (D1, D2, D3), sob o `cache` do React; a gravação da renovação conserva a validade desde o login (D4); `exigirSessao` passa a usá-la.
3. `quemSou.ts` e `/bff/*` passam a usar `obterSessaoValida`; `401` do FastAPI apaga a sessão (D5) — na página do funil e no `exigirPermissao`.
4. `app/sair/route.ts` (D6), `proxy.ts` deixando `/sair` passar, e o botão no `Menu`.
5. Testes de cada ramo; gates; ponta a ponta com `JWT_MINUTOS=1` no uvicorn, para a renovação acontecer em toda navegação.
6. Commit, push, PR, comentário e "Em análise".

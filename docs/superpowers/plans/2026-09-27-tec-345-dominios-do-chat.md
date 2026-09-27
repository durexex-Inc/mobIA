# TEC-345 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-345-dominios-do-chat-design.md`. Backend e frontend; Node 24 pelo fnm.

1. `vigente.py`: `dominios_do_chat` e a validação (D1). Unitários primeiro.
2. Migration `0065`, modelo, `repositorio.py`, rota `/agente` (D1). Feature de `GET`/`PATCH`.
3. `/widget/aparencia` com `dominios` (D2).
4. Next, `lib/dominios.ts`: formato, `hostDoOrigin` e as fontes da CSP. Testes.
5. `/embed/aparencia` e `buscarAparencia` com os domínios, 404 fora deles, `Vary: Origin` (D3).
6. Proxy `async`: busca memorizada, `frame-ancestors` e `connect-src` do embed (D4, D5). Testes com relógio falso.
7. `.env.example`, README do frontend, gates do backend e do frontend, testes, `comentarios_tocados.py --checar`.
8. Commit, push, PR, comentário na card e "Em análise".

# TEC-365 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-365-origem-no-handshake-design.md`. Só backend.

1. `Settings`: `origens_do_widget`, o validador de formato e a propriedade `origens_permitidas_do_widget` (D2). Testes unitários primeiro.
2. `widget.py`: `origem_permitida` e a recusa com `403` depois do limite por IP, com o log `widget.origem_recusada` (D3, D4). Testes unitários da função.
3. `tests/conftest.py`: `ClienteWebSocket` manda `Origin`; `app_do_widget` configura a lista.
4. Integração: aceita, recusa `copia-do-site.com` com log, sem `Origin`, lista vazia.
5. `.env.example` e o README do frontend (L4).
6. Gates (ruff check, ruff format, mypy), `tests/unit`, `tests/integration` por blocos, `comentarios_tocados.py --checar`.
7. Commit, push, PR, comentário na card e "Em análise".

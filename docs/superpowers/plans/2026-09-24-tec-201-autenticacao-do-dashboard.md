# TEC-201 — Autenticação do dashboard — plano

Desenho: `docs/superpowers/specs/2026-09-24-tec-201-autenticacao-do-dashboard-design.md`
Branch: `feat/tec-201-autenticacao-do-dashboard`

## Task 1 — Dependências e configuração

- `argon2-cffi`, `pyjwt`, `pyotp` no `pyproject.toml`, cada um com o porquê (D7).
- `app/config.py`: segredo do JWT (recusado em produção se for o de desenvolvimento, no molde da chave de cifra), `jwt_minutos` (60) e `refresh_dias` (7).

## Task 2 — Modelo e migration

- `usuarios`: id, nome, email (UNIQUE, em claro — D6), papel, corretor_id opcional, senha_hash, totp_segredo (cifrado), mfa_habilitado, ativo, carimbos.
- `sessoes_de_refresh`: id, usuario_id, familia, digest (SHA-256), expira_em, usado_em, revogado_em.
- Migration `0044`, sobre a `0043`.

## Task 3 — As peças de domínio

- `senha.py`: Argon2id — `gerar_hash`, `confere`.
- `totp.py`: semente cifrada com AAD do usuário; `confere_codigo` com janela.
- `tokens.py`: `emitir` e `validar` JWT (HS256, `alg` fixado na validação — D7).
- `sessoes.py`: emitir, rotacionar, revogar família (D4).

## Task 4 — As rotas

`POST /api/v1/auth/login`, `/auth/mfa`, `/auth/refresh`, `/auth/logout`.

Login de ADMIN com MFA devolve **desafio**, não tokens (D5).

## Task 5 — `exigir_admin` aceita os dois (D2)

JWT válido com papel ADMIN **ou** o `X-Admin-Token` compartilhado, com `warning` quando o segundo for usado.

## Task 6 — Testes e gates

- Unitários (senha, TOTP, JWT — inclusive `alg: none` e chave trocada).
- Integração: os cinco cenários do Gherkin, mais o reuso de refresh e a coexistência.
- Os três gates de Python, `comentarios_tocados.py --checar`, e a suíte inteira uma vez com `-n 8 --dist loadfile`.

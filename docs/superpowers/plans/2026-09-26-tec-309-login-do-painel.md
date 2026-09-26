# TEC-309 — plano

Desenho: `docs/superpowers/specs/2026-09-26-tec-309-login-do-painel-design.md`.

O Node precisa ser o 24: `export PATH="$APPDATA/fnm/node-versions/v24.21.0/installation:$PATH"`. A linha de base na `main` era 128 testes passando.

## Backend

1. `scripts/criar_usuario.py` (D8), com a função `criar_usuario(session, ...)` separada do `main`. Teste de integração em `tests/integration/test_criar_usuario.py`: ADMIN nasce com semente e `mfa_habilitado`, e consegue passar por `/auth/login` + `/auth/mfa` com um código gerado da URI; GERENTE nasce sem MFA; e-mail repetido é recusado.
2. O comentário em `api/autorizacao.py` que atribui a remoção do `X-Admin-Token` à TEC-309 passa a apontar para a TEC-382 (L1).

## Frontend

3. `lib/destino.ts` — `destinoSeguro` (D6), função pura, com um teste por forma de ataque.
4. `lib/servidor/armazem.ts` — a interface de três operações e o cliente `redis` atrás dela (D2). O `npm install redis`.
5. `lib/servidor/sessao.ts` — criar, ler e apagar a sessão; guardar, ler e apagar o desafio; nomes e opções dos cookies. Testes com o armazém em memória.
6. `lib/servidor/api.ts` — sai o `X-Admin-Token`, entra `acesso` → `Authorization: Bearer` (D7). Os testes existentes são ajustados.
7. `app/login/page.tsx` — as duas etapas e as mensagens de erro.
8. `app/login/entrar/route.ts` e `app/login/mfa/route.ts` (D4), com testes que seguem cada ramo: sucesso sem MFA, desafio, `401`, `403` de ADMIN sem MFA, API fora do ar, `Origin` estrangeira, `returnTo` externo.
9. `proxy.ts` — o redirecionamento sem cookie (D5), com os testes das rotas públicas.
10. `app/page.tsx` e `lib/metricas.ts` — o funil com o access da sessão; `401` manda ao login, e o aviso do `403` é reescrito (D7).
11. `app/bff/[...rota]/route.ts` — `401` sem sessão; repassa o access.
12. `scripts/verificar-bundle.mjs`, o job `Frontend` do CI e o README — `MOBIA_REDIS_URL` como sentinela (D9).

## Verificação

13. `npm run lint`, `npm test`, `npm run build` e `npm run verificar:bundle`, com a sentinela.
14. Os três gates do Python, `comentarios_tocados.py --checar`, e a suíte do Python com `-n 8`.
15. De ponta a ponta, com `docker compose`, o FastAPI e o `next dev`: criar um ADMIN pelo script, entrar com o código do TOTP, conferir o cookie no navegador, tentar um `returnTo` externo e um GERENTE sem MFA.
16. Commit, push, PR, o comentário na TEC-309 e a card em "Em análise".

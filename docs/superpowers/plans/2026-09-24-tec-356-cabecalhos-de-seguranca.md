# TEC-356 — Cabeçalhos de segurança nas rotas do dashboard — plano

Desenho: `docs/superpowers/specs/2026-09-24-tec-356-cabecalhos-de-seguranca-design.md`
Branch: `feat/tec-356-cabecalhos-de-seguranca`

## Task 1 — `frontend/src/proxy.ts`

- `export function proxy(request: NextRequest)` — **`proxy`, não `middleware`** (D1).
- Nonce por requisição; CSP montada com a forma de dev e a de produção (D5).
- `x-nonce` na requisição repassada, para o render; CSP também na resposta.
- `config.matcher` excluindo `_next/static`, `_next/image`, `favicon.ico`, `/bff` e os prefetches (D7).
- Comentário dizendo por que o arquivo se chama `proxy` e citando a referência empacotada.

## Task 2 — `frontend/next.config.ts`

- `headers()` com `X-Content-Type-Options`, `Referrer-Policy` e `Strict-Transport-Security` sobre `/(.*)` (D2).
- Comentário explicando a divisão com o proxy e o alcance a `_next/static`.

## Task 3 — `frontend/src/lib/autolink.ts`

- Função pura: só `http`/`https` viram link, com `rel="noopener noreferrer nofollow"`.
- Escapa o texto ao redor; esquema perigoso fica texto simples (D8).
- Docstring dizendo que nada a chama ainda e que a TEC-324 é quem vai chamar.

## Task 4 — Testes

- `proxy.test.ts` e `autolink.test.ts`, no molde de `route.test.ts` (instanciar `NextRequest` e chamar a função).
- A asserta do conjunto inteiro sobre a mesma resposta (D2).
- Nonce diferente entre duas requisições.

## Task 5 — Gates e verificação no app

```bash
cd frontend
npm run lint
npm test
npm run build
npm run verificar:bundle
```

- Subir o app (`npm start`) e conferir os cabeçalhos na resposta real **e** que a página renderiza com estilo — o `next/font` injeta `<style>` inline e é o que uma CSP malfeita quebraria sem nenhum teste acusar.
- `scripts/comentarios_tocados.py` e `--checar` na raiz.
- Os três gates de Python não olham para `frontend/`, mas rodo mesmo assim porque a branch toca `docs/`.

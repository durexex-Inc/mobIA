# TEC-335 — Plano: enviar e reordenar as fotos do imóvel

Desenho: `docs/superpowers/specs/2026-09-28-tec-335-fotos-do-imovel-design.md`. **Full-stack** — ao contrário das TEC-332/333/334, esta card constrói backend E frontend.

## Backend

- [ ] **`alembic/versions/0069_fotos_do_imovel_com_teto.py`** (novo): `CheckConstraint("cardinality(fotos) <= 15", name="ck_imoveis_fotos_teto")`.
- [ ] **`domain/catalogo/fotos.py`** (novo): `FOTO_TETO_DE_BYTES = 5 * 1024 * 1024`, `FOTO_LIMITE_POR_IMOVEL = 15`, `detectar_formato` (assinatura de bytes JPEG/PNG/WebP — D3), `PREFIXO_DO_ARMAZEM = "fotos-de-imoveis"`.
- [ ] **`api/routes/imoveis.py`**: `POST /api/v1/imoveis/{imovel_id}/fotos` e `GET /api/v1/imoveis/{imovel_id}/fotos/{foto_id}` (ambas `GERIR_CATALOGO`, D2/D3) — usa `armazem_da_config` (D1) para gravar/ler, sem cifra.
- [ ] **Testes de backend**: assinatura de cada formato aceita/recusa (os 4 exemplos do Gherkin), teto de 5 MB, teto de 15 fotos (`422` e o `CHECK` da migration), a rota de leitura devolvendo o `Content-Type` certo, reordenação via `PATCH` existente sem rota nova.
- [ ] **Gates do Python**: `ruff check`, `ruff format --check`, `mypy` (escopo `src tests alembic evals scripts`), `pytest` (suíte inteira, ver `-n 8 --dist loadfile` no `CLAUDE.md`).

## Frontend

- [ ] **`lib/fotos.ts`** (novo): `FOTO_TETO_DE_BYTES`, `FOTO_LIMITE_POR_IMOVEL` (mesmos valores do backend, D6), checagem client-side de tamanho/extensão antes do envio, `reordenar`/`remover` (montam a nova lista completa de URLs para o `PATCH` existente).
- [ ] **`components/FotosDoImovel.tsx`** (novo): miniaturas na ordem de `imovel.fotos`, upload (`POST /bff/api/v1/imoveis/{id}/fotos`), reordenar por arraste (HTML5 drag nativo) e por botões "mover para cima"/"mover para baixo" acessíveis por teclado (D5), remover (monta a lista sem aquele item e faz `PATCH`).
- [ ] **`app/(painel)/admin/imoveis/page.tsx`** ou `FormularioDeImovel.tsx`: monta `FotosDoImovel` na edição de um imóvel existente (upload exige um `imovel_id`, então não aparece no formulário de criação).
- [ ] **`lib/servidor/bff.ts`**: duas entradas novas — `POST api/v1/imoveis/*/fotos`, `GET api/v1/imoveis/*/fotos/*` (D7 — a leitura também é autenticada, D2).
- [ ] **Testes de frontend**: `lib/fotos.test.ts`, `components/FotosDoImovel.test.tsx` (upload, reordenar por botão e por teclado, remover, recusa de tamanho/tipo antes do envio), mais caso em `lib/servidor/bff.test.ts`.
- [ ] **Gates do frontend**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [ ] **Navegador**: Edge headless por CDP, ADMIN — enviar um JPEG válido e ver a miniatura aparecer; tentar um GIF disfarçado de `.jpg` (assinatura errada) e ver a recusa; reordenar só com o teclado e confirmar que a lista PATCH'd bate; atingir 15 fotos e ver a recusa do 16º envio.
- [ ] **Jira**: comentar as decisões de armazenamento (D1/D2, sem bucket público, sem cifra), a lacuna de arquivo órfão ao remover (D4), e o link do PR; mover para "Em análise".

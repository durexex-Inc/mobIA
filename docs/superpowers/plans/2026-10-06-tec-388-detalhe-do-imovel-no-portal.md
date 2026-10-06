# TEC-388 — Plano: detalhe e fotos de um imóvel no portal

Desenho: `docs/superpowers/specs/2026-10-06-tec-388-detalhe-do-imovel-no-portal-design.md`.

## Backend

- [x] `src/mobia/domain/catalogo/fotos.py`: `ler_bytes(armazem, imovel_id, foto_id) -> tuple[bytes, str] | None`, extraído de `imoveis.py::ler_foto`.
- [x] `src/mobia/api/routes/imoveis.py`: `ler_foto` passa a usar `ler_bytes` (sem mudar o contrato da rota admin).
- [ ] `src/mobia/api/routes/portal.py`: `GET /portal/imoveis/{imovel_id}` (`payload_do_detalhe`, lista explícita de campos, D2) e `GET /portal/imoveis/{imovel_id}/fotos/{foto_id}`, os dois com o mesmo 404 uniforme de D3.
- [ ] `src/mobia/api/autorizacao.py`: as duas rotas novas em `ROTAS_PUBLICAS`.
- [ ] `tests/integration/test_portal_detalhe_endpoint.py` (novo): CA-01 a CA-03, imóvel inexistente e cada status não-`DISPONIVEL`, foto existente/inexistente, id malformado (422).
- [ ] Gates: `ruff check`, `ruff format --check`, `mypy`.

## Frontend

- [ ] `frontend/src/lib/imovelDetalhe.ts` (novo): tipo `ImovelDetalhe` e parser `imovelDetalheDe`.
- [ ] `frontend/src/lib/servidor/vitrinePublica.ts`: `buscarDetalheDoImovel(id)`, sem `acesso`.
- [ ] `frontend/src/components/CardDeImovel.tsx`: distingue link interno (`/`) de externo — `next/link` sem `target="_blank"` para interno; D5.
- [ ] `frontend/src/lib/servidor/vitrinePublica.ts` (ou `buscaPublica.ts`): a listagem passa a preencher `url: "/busca/" + id` em cada item.
- [ ] `frontend/src/app/busca/[id]/page.tsx` (novo): Server Component pública, trata 404/422 (tela "Imóvel não encontrado") no molde de `leads/[leadId]/page.tsx`; galeria de fotos; estado vazio sem foto (CA-02).
- [ ] Testes: `imovelDetalhe.test.ts`, `CardDeImovel.test.tsx` (ajuste para link interno), `busca/[id]/page.test.tsx` (CA-01 a CA-03).
- [ ] Gates: `npm test`, `npm run lint`, `npm run build`.

## Fechamento

- [ ] Suíte completa do backend (por blocos se o Postgres cair) e do frontend.
- [ ] `scripts/comentarios_tocados.py --checar`.
- [ ] Push + PR contra `main`.
- [ ] Comentário na card TEC-388 (campos públicos decididos, lacunas L1/L2) + mover para "Em análise".

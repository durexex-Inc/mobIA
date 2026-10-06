# TEC-387 — Plano: portal público de busca de imóveis

Desenho: `docs/superpowers/specs/2026-10-05-tec-387-portal-publico-de-busca-design.md`.

## Backend

- [ ] `src/mobia/api/routes/imoveis.py`: extrair `payload_da_busca(resultado: ResultadoDaBusca) -> dict[str, object]` do corpo de `busca()`, sem mudar o retorno existente. Teste já cobre `/busca`; conferir que a suíde continua verde.
- [ ] `src/mobia/api/routes/portal.py` (novo): `GET /portal/imoveis`, público, query params (`operacao` obrigatório, `precoMin`, `precoMax`, `tipo`, `quartosMin`, `vagasMin`, `regioes`), valida `operacao` contra `COLUNA_DE_PRECO` (422 se `AMBOS`), monta `FiltroDeBusca`, chama `buscar_com_relaxamento` com `consulta_texto=None`, devolve `payload_da_busca(resultado)`.
- [ ] `src/mobia/app/main.py`: registrar `portal_router`, comentário dizendo por que é público (D1).
- [ ] `src/mobia/api/autorizacao.py`: entrada em `ROTAS_PUBLICAS` para `/portal/imoveis`.
- [ ] `tests/integration/test_portal_endpoint.py` (novo, molde de `test_busca_endpoint.py`): CA-01 a CA-04, 422 para `operacao=AMBOS` e para `operacao` ausente, sem header de autorização nenhum (confirma que é público).
- [ ] `tests/unit/test_autorizacao_em_toda_rota.py`: nenhuma mudança esperada em `PERMISSAO_ESPERADA` (a rota não tem `Exige`); conferir que `test_toda_rota_declara_autorizacao` e `test_rotas_publicas_nao_lista_rota_que_nao_existe` passam com a entrada nova.
- [ ] Gates: `ruff check`, `ruff format --check`, `mypy` (escopo `src tests alembic evals scripts`).

## Frontend

- [ ] `frontend/src/lib/servidor/vitrinePublica.ts` (novo): `buscarVitrinePublica(filtros)` via `chamarApi('/portal/imoveis', { busca, revalidarEmSegundos: N })`, sem `acesso`; mapeia a resposta (`preco` → `precoCentavos`, campos ausentes → `null`) e valida com `imovelDe`.
- [ ] `frontend/src/app/busca/page.tsx` (novo): Server Component pública, lê `searchParams`, operação padrão `VENDA` quando ausente, desenha `FormularioDeBuscaPublica` + grade de `CardDeImovel`, mensagem de "nenhum resultado" quando `itens.length === 0`, nota de "mostrando os mais relevantes" quando `totalCandidatos > itens.length`.
- [ ] `frontend/src/components/FormularioDeBuscaPublica.tsx` (novo, client component): os seis filtros, atualiza a query string via `router.push`.
- [ ] Testes: `vitrinePublica.test.ts` (mapeamento e chamada sem `acesso`), `busca/page.test.tsx` (CA-01 a CA-03), `FormularioDeBuscaPublica.test.tsx`.
- [ ] Gates: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.

## Fechamento

- [ ] Rodar a suíte inteira do backend (bloco a bloco se o `-n 8` derrubar o Postgres, ver CLAUDE.md) e a suíte do frontend.
- [ ] `scripts/comentarios_tocados.py --checar` antes do PR.
- [ ] Push + PR contra `main`.
- [ ] Comentário na card TEC-387 (divergências, CA não exercitado, lacunas L1-L4) + mover para "Em análise".

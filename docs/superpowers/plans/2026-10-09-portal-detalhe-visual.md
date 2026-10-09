# Plano — detalhe do imóvel no portal com visual de vitrine

Desenho: `docs/superpowers/specs/2026-10-09-portal-detalhe-visual-design.md`.

1. **Backend** — `api/routes/portal.py::payload_do_detalhe` acrescenta `codigo`, `latitude` e `longitude` (D1, D2). Teste de integração primeiro: `codigo` presente, coordenadas arredondadas a 3 casas, `null` sem coordenada.
2. **Tipo** — `lib/imovelDetalhe.ts` lê os três campos novos; teste unitário de coordenada ausente e inválida.
3. **CSP** — `proxy.ts::politicaDeSeguranca` aceita `portal` e emite `frame-src` do OSM (D3); teste de que só o portal a recebe.
4. **Página** — `app/busca/[id]/page.tsx` reescrita nas seções da referência; `GaleriaDoImovel` como Client Component (D5); `FormularioDeInteresse` em cartão, mantendo os nomes acessíveis que os testes usam.
5. **Estilo** — bloco `portal-*` no `globals.css`, claro e escuro (D4).
6. Gates: `npm run lint`, `npx tsc --noEmit`, `vitest --pool=threads`, `ruff`/`mypy` e o teste de integração do portal.

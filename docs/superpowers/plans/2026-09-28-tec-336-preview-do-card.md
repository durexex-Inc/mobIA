# TEC-336 — Plano: pré-visualizar o card do imóvel como aparece no chat web

Desenho: `docs/superpowers/specs/2026-09-28-tec-336-preview-do-card-design.md`. Só frontend, e reusa componentes já existentes (`CardDeImovel`, TEC-349) — a menor das cards de imóveis até aqui.

## Passos

- [ ] **`lib/imovel.ts`**: `diferencialDe` (novo, D4 — mesma regra de `apresentacao.py::diferencial_de`, `CARACTERISTICAS_NO_DESTAQUE = 2`).
- [ ] **`components/PreviewDoCard.tsx`** (novo): monta o objeto cru no formato de `card_de` a partir de `Formulario`/`fotos` (D1, D3, D5), passa por `imovelDe`, abre um `<dialog>` com `<CardDeImovel imovel={...} />` sem `aoReagir`.
- [ ] **`FormularioDeImovel.tsx`**: botão "Pré-visualizar card", habilitado só com `formularioValido(atual)` (D2), abre `PreviewDoCard`.
- [ ] **Testes**: `lib/imovel.test.ts` (casos de `diferencialDe`), `components/PreviewDoCard.test.tsx` (os dois cenários do Gherkin, incluindo a foto relativa da TEC-335 caindo no placeholder — D1), mais casos em `FormularioDeImovel.test.tsx` para o botão habilitado/desabilitado.
- [ ] **Gates**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`. Sem mudança de backend nesta card.
- [ ] **Navegador**: Edge headless por CDP, ADMIN — abrir um imóvel existente, mudar o título sem salvar, abrir a pré-visualização e confirmar o novo título com o layout do card; abrir a pré-visualização de um imóvel sem foto e confirmar o placeholder com o bairro.
- [ ] **Jira**: comentar o achado sobre a foto da TEC-335 não aparecer no card real (fora do escopo desta card, candidato a card própria) e o link do PR; mover para "Em análise".

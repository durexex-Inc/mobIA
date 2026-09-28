# TEC-336 — Plano: pré-visualizar o card do imóvel como aparece no chat web

Desenho: `docs/superpowers/specs/2026-09-28-tec-336-preview-do-card-design.md`. Só frontend, e reusa componentes já existentes (`CardDeImovel`, TEC-349) — a menor das cards de imóveis até aqui.

## Passos

- [x] **`lib/imovel.ts`**: `diferencialDe` (novo, D4 — mesma regra de `apresentacao.py::diferencial_de`, `CARACTERISTICAS_NO_DESTAQUE = 2`).
- [x] **`components/PreviewDoCard.tsx`** (novo): monta o objeto cru no formato de `card_de` a partir de `Formulario`/`fotos` (D1, D3, D5), passa por `imovelDe`, abre um `<dialog>` com `<CardDeImovel imovel={...} />` sem `aoReagir`. `lib/imoveis.ts::reaisParaCentavos` passou a ser exportada para D3/condominio reusarem a mesma conversao numerica.
- [x] **`FormularioDeImovel.tsx`**: botão "Pré-visualizar card", habilitado só com `formularioValido(atual)` (D2), abre `PreviewDoCard`. So renderiza com `imovel !== null` (edicao).
- [x] **Testes**: `lib/imovel.test.ts` (4 casos de `diferencialDe`), `components/PreviewDoCard.test.tsx` (os dois cenários do Gherkin, a foto relativa da TEC-335 caindo no placeholder — D1 —, o desempate de preço D3 nos dois sentidos, e o `diferencial` D4 fim a fim), mais 3 casos em `FormularioDeImovel.test.tsx` para o botão ausente/habilitado/desabilitado. 1217 testes passando no total.
- [x] **Gates**: `npm test` (1217 passed), `npm run lint` (limpo), `tsc --noEmit` (limpo), `npm run build` (compilou). Sem mudança de backend nesta card.
- [x] **Navegador**: Edge headless por CDP, ADMIN (usuário de verificação criado e removido depois) — abriu o único imóvel existente (que já tinha 3 fotos da TEC-335, caminho relativo), mudou o título sem salvar, abriu a pré-visualização: o `<dialog>` mostrou o título **não salvo**, com o layout real de `CardDeImovel`, e **sem `<img>`** — confirmando ao vivo que o caminho relativo da TEC-335 cai no placeholder (D1), não numa foto quebrada. Placeholder mostrou o bairro ("Centro"), confirmando o cenário 2 do Gherkin. Ambientes (uvicorn, `next dev`, Edge headless) e o usuário de verificação foram encerrados/removidos ao final.
- [x] **Jira**: comentar o achado sobre a foto da TEC-335 não aparecer no card real (fora do escopo desta card, candidato a card própria) e o link do PR; mover para "Em análise".

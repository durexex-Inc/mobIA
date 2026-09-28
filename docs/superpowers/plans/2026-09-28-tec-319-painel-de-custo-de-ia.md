# TEC-319 — Plano: painel de custo de IA

Desenho: `docs/superpowers/specs/2026-09-28-tec-319-painel-de-custo-de-ia-design.md`. Só frontend — o backend (TEC-191) já existe.

## Passos

- [x] **`lib/formato.ts`**: `moedaTotal`/`moedaMedia` (US$ com 2/4 casas, pt-BR).
- [x] **`lib/custo.ts`** (novo): tipos (`CustoDeIA`, `TokensPorModelo`, `Orcamento`) e `buscarCusto`, reaproveitando `chamarApi`/`detalheDe`/`ErroDeMetricas` de `lib/metricas.ts`.
- [x] **`components/CustoDeIA.tsx`** (novo): custo total, as duas médias (com `estadoDe`/`Vazio` quando nulas), tokens por modelo, alerta de orçamento (ou link para `/admin` sem orçamento).
- [x] **`app/(painel)/custo-ia/page.tsx`** (novo): mesmo molde de `app/(painel)/page.tsx` (guarda, filtros, erro 401/403/422/5xx).
- [x] **`lib/navegacao.ts`**: item de menu "Custo de IA" → `/custo-ia`, visível com `VER_FUNIL`.
- [x] **`app/globals.css`**: estilos do painel (lista de indicadores, tabela de tokens, alerta, aviso sem orçamento).
- [x] **Testes**: `lib/custo.test.ts` (7), `components/CustoDeIA.test.tsx` (12), `app/(painel)/custo-ia/page.test.tsx` (8), mais 2 em `navegacao.test.ts`.
- [x] **Gates**: `npm test` (1010 verdes), `npm run lint`, `tsc --noEmit`, `npm run build`. Sem mudança de backend nesta card — gates do Python não re-executados (nada em `src/tests/alembic/evals/scripts` mudou).
- [x] **Navegador**: Edge headless por CDP, GERENTE, `message_telemetry`/`lead_qualification`/orçamento semeados de verdade. Confirmado: custo total US$0,84, médias corretas, tokens por modelo; alerta "⚠ Orçamento em 84,5% do período (US$ 0,84 de US$ 1,00)" com orçamento de US$1; sem orçamento, link "Configurar orçamento" → `/admin`; período sem conversas mostra "US$ 0,00" e "sem dados no período", nunca "Ainda não medido".
- [x] **Jira**: comentário na card com o que a verificação confirmou e a decisão sobre o link de orçamento; mover para "Em análise".

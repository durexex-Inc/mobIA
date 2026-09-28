# TEC-319 — Plano: painel de custo de IA

Desenho: `docs/superpowers/specs/2026-09-28-tec-319-painel-de-custo-de-ia-design.md`. Só frontend — o backend (TEC-191) já existe.

## Passos

- [ ] **`lib/formato.ts`**: `moedaTotal`/`moedaMedia` (US$ com 2/4 casas, pt-BR).
- [ ] **`lib/custo.ts`** (novo): tipos (`CustoDeIA`, `TokensPorModelo`, `Orcamento`) e `buscarCusto`, reaproveitando `chamarApi`/`detalheDe`/`ErroDeMetricas` de `lib/metricas.ts`.
- [ ] **`components/CustoDeIA.tsx`** (novo): custo total, as duas médias (com `estadoDe`/`Vazio` quando nulas), tokens por modelo, alerta de orçamento (ou link para `/admin` sem orçamento).
- [ ] **`app/(painel)/custo-ia/page.tsx`** (novo): mesmo molde de `app/(painel)/page.tsx` (guarda, filtros, erro 401/403/422/5xx).
- [ ] **`lib/navegacao.ts`**: item de menu "Custo de IA" → `/custo-ia`, visível com `VER_FUNIL`.
- [ ] **`app/globals.css`**: estilos do painel (lista de indicadores, tabela de tokens, alerta, aviso sem orçamento).
- [ ] **Testes**: `lib/custo.test.ts`, `components/CustoDeIA.test.tsx`, `app/(painel)/custo-ia/page.test.tsx`.
- [ ] **Gates**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [ ] **Navegador**: semear `message_telemetry` real, abrir `/custo-ia`, confirmar custo total/médias/tokens/alerta (com e sem orçamento configurado).
- [ ] **Jira**: comentário na card com o que a verificação confirmou e a decisão sobre o link de orçamento; mover para "Em análise".

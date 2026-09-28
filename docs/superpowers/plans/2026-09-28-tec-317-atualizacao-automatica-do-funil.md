# TEC-317 — Plano: atualização automática do funil

Desenho: `docs/superpowers/specs/2026-09-28-tec-317-atualizacao-automatica-do-funil-design.md`.

## Passos

- [x] **`lib/metricas.ts`**: `revalidarEmSegundos` de `buscarFunil` de `60` para `30`; comentário da TEC-309/D7 corrigido para o número novo.
- [x] **`lib/metricas.test.ts`**: as duas asserções `revalidate: 60` → `30`.
- [x] **`components/AtualizacaoAutomatica.tsx`** (novo): componente de cliente com o polling (D1, D3, D4, D5).
- [x] **`components/AtualizacaoAutomatica.test.tsx`** (novo): os cenários do Gherkin com `vi.useFakeTimers`.
- [x] **`app/(painel)/page.tsx`**: grava `atualizadoEm` quando `buscarFunil` retorna com sucesso; renderiza `<AtualizacaoAutomatica>` dentro do bloco `{funil ? ... : null}` (D6).
- [x] **`app/(painel)/page.test.tsx`**: mock de `next/navigation` ganha `useRouter`; teste novo para o texto "Atualizado há" aparecer/não aparecer.
- [x] **`app/globals.css`**: `.funil-atualizacao`, no molde das classes já existentes ao lado do funil.
- [x] **Gates**: `npm test` (969 verdes), `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: Edge headless por CDP, GERENTE sem MFA, `next dev`/`uvicorn` locais. Confirmado: incrementos no log do backend em ~30s e ~61s após a carga (cache dedupando o resto); 0 chamadas em 80s com a aba oculta (`document.visibilityState` forçado); 1 chamada imediata ao voltar a ficar visível, sem repetir 5s depois; `?canal=web` presente na chamada do ciclo seguinte, confirmando que o filtro sobrevive ao refresh.
- [x] **Jira**: comentário na card com o que a verificação no navegador confirmou; mover para "Em análise".

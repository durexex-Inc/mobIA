# TEC-317 — Plano: atualização automática do funil

Desenho: `docs/superpowers/specs/2026-09-28-tec-317-atualizacao-automatica-do-funil-design.md`.

## Passos

- [ ] **`lib/metricas.ts`**: `revalidarEmSegundos` de `buscarFunil` de `60` para `30`; comentário da TEC-309/D7 corrigido para o número novo.
- [ ] **`lib/metricas.test.ts`**: as duas asserções `revalidate: 60` → `30`.
- [ ] **`components/AtualizacaoAutomatica.tsx`** (novo): componente de cliente com o polling (D1, D3, D4, D5).
- [ ] **`components/AtualizacaoAutomatica.test.tsx`** (novo): os cenários do Gherkin com `vi.useFakeTimers`.
- [ ] **`app/(painel)/page.tsx`**: grava `atualizadoEm` quando `buscarFunil` retorna com sucesso; renderiza `<AtualizacaoAutomatica>` dentro do bloco `{funil ? ... : null}` (D6).
- [ ] **`app/(painel)/page.test.tsx`**: mock de `next/navigation` ganha `useRouter`; teste novo para o texto "Atualizado há" aparecer/não aparecer.
- [ ] **`app/globals.css`**: `.funil-atualizacao`, no molde das classes já existentes ao lado do funil.
- [ ] **Gates**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [ ] **Navegador**: funil aberto com um filtro aplicado; esperar ~30 s e confirmar que os números mudam (ou o texto "Atualizado há" reseta) sem recarregar e sem perder o filtro; ocultar a aba e confirmar (via Network) que nenhuma nova chamada ao funil acontece enquanto oculta.
- [ ] **Jira**: comentário na card com o que a verificação no navegador confirmou e qualquer divergência achada; mover para "Em análise".

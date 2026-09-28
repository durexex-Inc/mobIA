# TEC-342 — Plano: eliminar os dados do titular com confirmação forte

Desenho: `docs/superpowers/specs/2026-09-28-tec-342-eliminacao-do-titular-design.md`. Só frontend: o `DELETE` já existe (TEC-207).

## Passos

- [x] **`lib/servidor/bff.ts`**: nova entrada em `ROTAS_PERMITIDAS` — `DELETE api/v1/leads/*/dados-pessoais`.
- [x] **`components/EliminarDadosDoTitular.tsx`**: botão + diálogo de confirmação (texto = `leadId`), `DELETE` pelo `/bff/*`, aviso de solicitado, tratamento de erro no molde de `ControleDaConversa`.
- [x] **`components/FilaDoTitular.tsx`**: coluna "Portabilidade" vira "Ação"; célula decide por `tipo` (`ACESSO` baixa, `ELIMINACAO` com `leadId` elimina, resto `'—'`).
- [x] **Testes**: `bff.test.ts` (rota nova); `EliminarDadosDoTitular.test.tsx` (desabilitado até bater, DELETE certo, cancelar, 401, erro genérico); `FilaDoTitular` (coluna renomeada e as três ramificações).
- [x] **Gates**: os três do Python, `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: diálogo abrindo, botão desabilitado/habilitado, `DELETE` real e o aviso.
- [x] **Prosa**: nota na TEC-340 (L3) fechando a lacuna de eliminação.

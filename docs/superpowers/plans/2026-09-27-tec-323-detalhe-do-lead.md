# TEC-323 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-323-detalhe-do-lead-design.md`. Node 24 (ver o plano da TEC-309).

1. `lib/detalhe.ts`, puro: os tipos da resposta, o corte do resumo em seis blocos (D3) e os rótulos da qualificação, dos agendamentos e dos follow-ups (D4, D6). Testes primeiro.
2. `lib/servidor/leads.ts`: `buscarDetalhe`, `no-store` (D7).
3. `components/detalhe/`: resumo, contato, qualificação, agendamentos, follow-ups.
4. `app/(painel)/leads/[leadId]/page.tsx` e `loading.tsx`, com os estados (D1, D7).
5. A lista: a linha vira `<a>` para quem tem `VER_DETALHE_DO_LEAD` (D1, D2).
6. Gates do frontend, suíte do Python (nada muda lá), ponta a ponta com o FastAPI local.
7. Commit, push, PR, comentário na card e "Em análise".

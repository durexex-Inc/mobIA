# TEC-326 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-326-regenerar-resumo-design.md`. Só frontend. Node 24 (ver o plano da TEC-309).

1. `/bff/*`: `POST api/v1/handoffs/*/resumo` (D5).
2. `components/ResumoRegeneravel.tsx`: o corpo do resumo, o botão, a trava por `geradoEm`, "Gerando novo resumo…", a troca pela resposta e as recusas (D2 a D4). Testes com `fetch` falso e timers falsos primeiro.
3. `SecaoResumo` usa o componente; a página passa `podeRegenerar` (`ATENDER_LEAD`) (D1).
4. Testes da página; README; gates; ponta a ponta.
5. Commit, push, PR, comentário na card e "Em análise".

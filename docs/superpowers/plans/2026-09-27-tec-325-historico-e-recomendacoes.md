# TEC-325 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-325-historico-e-recomendacoes-design.md`. Só frontend. Node 24 (ver o plano da TEC-309).

1. `lib/detalhe.ts`: os tipos de `historicoScore` e `recomendacoes`; `CAUSAS_DO_SCORE`, `REACOES`, `DESCARTES`; `linhasDoHistorico`, `reacaoLegivel` e os pontos do gráfico. Unitários primeiro.
2. `tests/unit/test_vocabulario_da_tela.py`: os três mapas contra `ReacaoLead`, `CategoriaDescarte` e as `CAUSA_*` (D4).
3. `DetalheDoLead.tsx`: `SecaoHistorico` (SVG com a lista) e `SecaoRecomendacoes`, nas posições 4 e 5 (D1 a D3).
4. Testes da página: os três cenários.
5. README, gates dos dois lados, ponta a ponta.
6. Commit, push, PR, comentário na card e "Em análise".

# TEC-329 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-329-corrigir-qualificacao-design.md`. Node 24 (ver o plano da TEC-309).

Backend:
1. `PedidoDeEdicao.regiao` passa por `normalizar_regiao`, e o vazio vira `null` (D1). Teste de feature primeiro.
2. `tests/unit`: os mapas de rótulo de `frontend/src/lib/detalhe.ts` batem com os enums de `agente/schemas.py` (D2).
3. Emenda E-02 à RN-18.3.

Frontend:
4. `/bff/*`: `PATCH api/v1/leads/*/qualificacao` na allowlist (D6).
5. `lib/detalhe.ts`: os mapas exportados; `lib/qualificacao.ts` com o formulário ↔ `PATCH` (diferença, reais ↔ centavos) e a leitura do 422. Unitários primeiro.
6. `components/EdicaoDaQualificacao.tsx`: botão, formulário, antes e depois, recusas, alteração não salva (D3–D5).
7. A seção e a página: `podeEditar` (`ATENDER_LEAD`) e `encerrada`.
8. README, gates dos dois lados, suíte, ponta a ponta.
9. Commit, push, PR, comentário na card e "Em análise".

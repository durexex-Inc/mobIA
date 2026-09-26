# TEC-379 — plano

Desenho: `docs/superpowers/specs/2026-09-26-tec-379-suite-paralela-design.md`.

1. Em `tests/features/test_dado_pessoal_do_lead.py::test_revelar_devolve_o_numero_e_grava_a_trilha`, trocar `antes = datetime.now(UTC)` por `antes = await session.scalar(text("SELECT clock_timestamp()"))`, com o comentário do porquê (D2).
2. Rodar o arquivo sozinho algumas vezes.
3. Os três gates estáticos.
4. Rodar a suíte inteira com `-n 8 --dist loadfile`: a coleta tem de passar (critério 1) e o teste do passo 1 não pode reprovar.
5. Commit, push, PR; na card, um comentário com a D1 (a falha 1 já estava consertada) e a varredura da D3, e a card vai para "Em análise".

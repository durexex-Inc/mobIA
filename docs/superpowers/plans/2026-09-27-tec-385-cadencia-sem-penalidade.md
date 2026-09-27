# TEC-385 — plano de implementação

Desenho: `docs/superpowers/specs/2026-09-27-tec-385-cadencia-sem-penalidade-design.md`.

1. `context/temperatura.py::temperatura_da_cadencia_de` e os unitários dela.
2. A coluna em `LeadQualification`, a migration 0068 com o preenchimento parcial, e a gravação em `registrar_recalculo`.
3. As duas consultas de `followup/repositorio.py` passando a ler `COALESCE`.
4. `preencher_temperaturas_da_cadencia` e o script, com o teste de integração.
5. As features (os três cenários da card), a Emenda E-03 à RN-13.1 com a linha no índice, e os gates.

# TEC-327 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-327-assumir-e-devolver-design.md`. Node 24 (ver o plano da TEC-309).

Backend:
1. `atendimento/repositorio.py`: `em_curso`, com quem tem a conversa e o nome (D2, D3).
2. O detalhe ganha `atendimento`; o 409 de `assumir` ganha `assumidoPor` (D2, D3). Integração primeiro.
3. `transcricao.py`: `posteriores_da_transcricao` e `cursorPosterior`; a rota aceita `depois` e só registra com fala (D1). Unitários do cursor e integração da trilha primeiro.
4. Emendas E-02 e E-03 à seção 6.2 do SRS.

Frontend:
5. `/bff/*`: `POST api/v1/leads/*/assumir` e `/devolver` na allowlist (D4).
6. `lib/transcricao.ts`: `cursorPosterior`, `urlDasPosteriores`. `lib/detalhe.ts`: `atendimento`.
7. `components/ControleDaConversa.tsx`: faixa, botões, confirmação, 409 com nome (D4).
8. `Transcricao.tsx`: polling com a aba visível, só quando `acompanhar` (D5).
9. A página do detalhe liga os dois.
10. Gates dos dois lados, suíte, ponta a ponta.
11. Commit, push, PR, comentário na card e "Em análise".

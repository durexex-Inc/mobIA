# TEC-328 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-328-responder-pelo-painel-design.md`. Node 24 (ver o plano da TEC-309).

Backend:
1. `atendimento/fala.py` e a rota: `messageId` como id da fala; reenvio devolve a fala gravada; `message_id_em_uso` e `fala_em_envio` (D1). Teste de feature primeiro.
2. `falar_com_o_lead` confere `dentro_da_janela` antes da Meta (D2). Teste de feature primeiro.
3. O detalhe ganha `janelaDeServicoFechaEm` (D2). Integração primeiro.
4. Emendas E-03 à RN-18.3 e E-03 à seção 6.2 (`GET /api/v1/leads/{leadId}`), e o índice de emendas do topo do SRS, que não tem as linhas das TEC-327 e TEC-329.

Frontend:
5. `/bff/*`: `POST api/v1/leads/*/mensagens` (D5).
6. `lib/resposta.ts`: limite, contador, janela, leitura da recusa. Unitários primeiro.
7. `components/RespostaDoCorretor.tsx`, montado dentro de `Transcricao`: a fala enviada entra na lista (D3, D4).
8. A página passa `resposta` (janela e se pode responder).
9. README, gates dos dois lados, suíte, ponta a ponta.
10. Commit, push, PR, comentário na card e "Em análise".

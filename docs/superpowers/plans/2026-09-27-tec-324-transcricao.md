# TEC-324 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-324-transcricao-design.md`. Node 24 (ver o plano da TEC-309).

1. `lib/servidor/bff.ts`: a entrada `GET api/v1/leads/*/mensagens` na allowlist, com teste (D2).
2. `lib/transcricao.ts`, puro: tipos, rótulo e lado do autor, texto da fala sem conteúdo ou retida (D4). Testes primeiro.
3. `lib/servidor/leads.ts`: `buscarTranscricao`, `no-store`.
4. `components/Transcricao.tsx` (`'use client'`): rolagem no fim, carregar anteriores pelo `/bff/*` preservando a posição, `aria-live` (D2, D3, D5, D6).
5. A página do detalhe: detalhe e transcrição em paralelo; a falha da transcrição fica dentro da seção (D1).
6. Gates do frontend, suíte do Python, ponta a ponta com uma conversa longa.
7. Commit, push, PR, comentário na card e "Em análise".

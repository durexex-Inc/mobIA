# TEC-311 — plano

Desenho: `docs/superpowers/specs/2026-09-26-tec-311-sessao-ociosa-design.md`. Node 24. Linha de base: 249 testes no frontend.

1. `lib/inatividade.ts` — os tempos, a fase (`ativo`, `aviso`, `encerrar`) a partir de dois horários, e o registro de alterações não salvas (D1, D4). Puro, e seguro para o cliente.
2. `sessao.ts` — a chave de atividade com 32 minutos (D3): criada no login, regravada a cada leitura; sem ela, a sessão é apagada.
3. `app/sessao/atividade/route.ts` — o batimento; `proxy.ts` deixando a rota passar.
4. `components/AvisoDeInatividade.tsx` — o diálogo, a contagem, o batimento a cada minuto de interação, o `localStorage` entre abas, o `POST /sair` e o login com `erro=inatividade` (D1, D2).
5. O layout do painel desenha o aviso; a tela de login ganha a mensagem (D5).
6. Testes com relógio falso; gates; ponta a ponta do lado do servidor (chave de atividade some → login).
7. Commit, push, PR, comentário e "Em análise".

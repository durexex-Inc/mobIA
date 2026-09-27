# TEC-330 — plano

Desenho: `docs/superpowers/specs/2026-09-27-tec-330-revelar-dado-pessoal-design.md`. Só frontend; o backend é o da TEC-195. Node 24 (ver o plano da TEC-309).

1. `/bff/*`: `POST api/v1/leads/*/revelar` na allowlist e `Cache-Control: no-store` em toda resposta (D5). Teste da allowlist invertido.
2. `components/DadoRevelavel.tsx`: máscara, Revelar, Ocultar, prazo de 5 min, erros (D1, D2). Testes com `fetch` falso e timers falsos primeiro.
3. `DetalheDoLead.tsx`: `SecaoContato` com o componente e lendo `contato.email`; a página passa `podeRevelar` (D4).
4. `TabelaDeLeads.tsx` e a página da lista: `podeRevelar`, botão fora do link (D4).
5. Testes das páginas: GERENTE vê o botão, CORRETOR não; nada de número no HTML servido.
6. README do frontend, gates (lint, test, build, bundle), `comentarios_tocados.py --checar`.
7. Commit, push, PR, comentário na card e "Em análise".

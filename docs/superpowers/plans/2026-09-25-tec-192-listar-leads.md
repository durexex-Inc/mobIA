# TEC-192 — Listar leads com ordenação por score e busca — plano

Desenho: `docs/superpowers/specs/2026-09-25-tec-192-listar-leads-design.md`
Branch: `feat/tec-192-listar-leads`

## Task 1 — `VER_LEADS` na matriz

`domain/usuarios/permissoes.py`: a permissão nova, para os quatro papéis (D7).
Atualizar `tests/unit/test_matriz_de_permissoes.py` e o mapa `PERMISSAO_ESPERADA`
de `tests/unit/test_autorizacao_em_toda_rota.py`.

## Task 2 — O cursor

`domain/leads/consulta.py`: `Filtro` (busca, status, temperatura, canal, corretor, limite),
`Cursor` e a codificação base64 opaca, com recusa de cursor corrompido (D5). Unitário.

## Task 3 — A consulta

`domain/leads/repositorio.py`: espinha em `messages` com `max(created_at)` (D1),
score corrente por `DISTINCT ON` (D4), LEFT JOIN de qualificação e conversa,
busca por região e telefone nas duas origens (D3), keyset pelo par (D5).

## Task 4 — A rota

`GET /api/v1/leads`, guardada por `Exige(Permissao.VER_LEADS)`. O recorte do papel
`CORRETOR` é aplicado por último, sobre o filtro que veio na query (D7).

## Task 5 — O dono do lead

`domain/notificacao/envio.py` grava `handoffs.corretor_id` com o destinatário
escolhido, inclusive quando o canal falha (D6).

## Task 6 — Testes

Os quatro cenários do Gherkin contra banco; a paginação nos dois sentidos
(ordem **e** nenhuma linha repetida); o empate de score; a busca por telefone nas
duas origens; o lead sem score; a escrita do `corretor_id`.

## Task 7 — Documentação e gates

Emendas E-01 (seção 6.2) e E-06 (RN-16.2); os três gates estáticos;
`comentarios_tocados.py` e `--checar`; a suíte inteira uma vez.

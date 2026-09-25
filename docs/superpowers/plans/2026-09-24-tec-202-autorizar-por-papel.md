# TEC-202 — Autorizar por papel em todas as rotas — plano

Desenho: `docs/superpowers/specs/2026-09-24-tec-202-autorizar-por-papel-design.md`
Branch: `feat/tec-202-autorizar-por-papel`

## Task 1 — A matriz de permissões

`src/mobia/domain/usuarios/permissoes.py`: enum `Permissao`, `MATRIZ` por papel e `permissoes_de(papel)`.
`ADMIN` recebe o conjunto inteiro por construção, não por repetição (D1, D2).

## Task 2 — A claim `corretor_id` no JWT

`tokens.py`: `emitir` e `emitir_desafio` passam a receber `corretor_id`; `Identidade` ganha o campo e
`validar` o exige como os outros — `None` é valor legítimo, e num `CORRETOR` nega tudo o que é por dono (D4).
`routes/auth.py` passa o `usuario.corretor_id` nos três pontos de emissão.

## Task 3 — A guarda por permissão

`src/mobia/api/autorizacao.py`: `IdentidadeDaRequisicao` (JWT ou o `ADMIN` sintético do token
compartilhado), a dependência `Exige(permissao)`, `ROTAS_PUBLICAS` e o evento `autorizacao.negada` (D2, D3, D6).
`api/deps.py` perde o `exigir_admin`; o ramo do token compartilhado migra com os comentários que ainda valem.

## Task 4 — As onze rotas declaram a permissão

`imoveis` (`GERIR_CATALOGO`, `BUSCAR_IMOVEIS`), `corretores` (`GERIR_CORRETORES`),
`metricas` (`VER_FUNIL`), `handoffs` e `conversas` (`ATENDER_LEAD`).

## Task 5 — A regra do dono

`handoffs.corretor_id` conferido contra a identidade em `/aceitar` e `/resumo`; `corretor_id` do corpo
conferido em `/conversas/assumir` e `/devolver`, só para papel `CORRETOR` (D5, D8).

## Task 6 — `GET /api/v1/auth/me`

Papel, vínculo de corretor e permissões de quem apresenta JWT — o consumidor que torna
`VER_DADOS_COMPLETOS` observável e a origem do `GET /bff/me` da TEC-312 (D7).

## Task 7 — Testes

- Unitários: a matriz (`ADMIN` completo, `LEITURA` sem escrita) e a varredura de `app.routes`.
- Integração: o esquema dos quatro papéis, o dono do handoff, o `assumir` em nome de outro,
  o `LEITURA` recusado nas escritas, o registro da tentativa negada, a coexistência com o token
  compartilhado e o `/auth/me`.

## Task 8 — Documentação e gates

Emendas E-01 (RNF-12) e E-02 (RN-16.4) no SRS; os três gates estáticos;
`comentarios_tocados.py` e `--checar`; a suíte inteira uma vez.

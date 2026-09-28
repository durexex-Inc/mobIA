# TEC-340 — Plano: fila de pedidos do titular

Desenho: `docs/superpowers/specs/2026-09-28-tec-340-fila-do-titular-design.md`. Só frontend: a API é da TEC-207.

## Passos

- [x] **`lib/titular.ts`**: o tipo do pedido, os dias restantes por calendário em São Paulo, o texto do prazo, o destaque e os rótulos. Testes da tabela da card, da virada de dia e das bordas.
- [x] **`lib/servidor/titular.ts`**: `buscarFilaDoTitular`, com `status=ABERTA` e sem cache.
- [x] **`FilaDoTitular`**: a tabela, com o destaque em texto e o link para o lead.
- [x] **Página `/admin/titular`**: a guarda por `ATENDER_TITULAR`, 401 ao login, 403 a "Sem permissão", a falha de carga e a fila vazia. Testes da página, com os três cenários.
- [x] **Área de administração**: a seção "Pedidos do titular" com link; `ATENDER_TITULAR` em `PERMISSOES_DE_ADMIN`.
- [x] **CSS** da tabela e do destaque.
- [x] **Gates do frontend**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: GERENTE e ADMIN (com MFA) sobre uma base semeada.

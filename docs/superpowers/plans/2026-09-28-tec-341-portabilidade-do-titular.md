# TEC-341 — Plano: baixar os dados do titular

Desenho: `docs/superpowers/specs/2026-09-28-tec-341-portabilidade-do-titular-design.md`. Só frontend: a exportação é da TEC-207.

## Passos

- [x] **`lib/servidor/titular.ts`**: `buscarSolicitacao(id, acesso)`, sem filtro de status.
- [x] **Route Handler** `/admin/titular/[solicitacaoId]/baixar`: guarda por sessão e por `ATENDER_TITULAR`; a solicitação relida decide "já concluído" (status antes de `leadId`, por causa do par zerado); transmite o corpo do backend com os três cabeçalhos.
- [x] **`FilaDoTitular`**: coluna "Portabilidade", com o link só nas linhas `ACESSO`.
- [x] **Página da fila**: o aviso de `?concluido=1`.
- [x] **Testes**: o Route Handler (sessão, permissão, os dois cenários, e as bordas sem cenário na card); a coluna nova na tabela; o aviso na página.
- [x] **Gates**: os três do Python, `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: baixar de verdade (cabeçalhos e corpo), baixar de novo (achou e corrigiu um bug de ordem), GERENTE sem permissão.
- [x] **Prosa**: nota na TEC-340.

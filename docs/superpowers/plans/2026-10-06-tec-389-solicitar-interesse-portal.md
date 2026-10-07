# TEC-389 — Plano de implementação

Ver o desenho em `docs/superpowers/specs/2026-10-06-tec-389-solicitar-interesse-portal-design.md`.

## Backend

- [x] `Gatilho.INTERESSE_PORTAL` + entradas em `ETIQUETA_DE`/`PRIORIDADE_DE`
      (`domain/handoff/vocabulario.py`).
- [x] `CANAL_PORTAL = "portal"` (`domain/messages/canais.py`).
- [x] Tabela `solicitacoes_de_interesse` + `registrar_interesse`
      (`domain/portal/interesse.py`), idempotente por
      `(channel, conversation_key, imovel_id)`.
- [x] Migration `0070_solicitacoes_de_interesse.py`.
- [x] `rate_limit_interesse_por_minuto` em `app/config.py` (default 3/min,
      mesmo escopo `ESCOPO_NUMERO` do rate limit por telefone já existente).
- [x] `POST /portal/imoveis/{id}/interesse` (`api/routes/portal.py`):
  - valida telefone (`identidade/telefone.py::normalizar`), 422 se inválido;
  - reaproveita `_imovel_disponivel` (mesmo 404 da TEC-388);
  - rate limit por telefone (`infra/rate_limit.py::consumir` +
    `registrar_bloqueio`), 429 se excedido;
  - `registrar_identidade` (índice de telefone) + `registrar_handoff` +
    `registrar_interesse`, na mesma transação;
  - resumo determinístico (`_resumo_do_interesse`) gravado só quando o
    handoff nasce (`registro.criado`);
  - enfileira `NOTIFICAR_JOB` só quando o handoff nasce; 503 se faltar pool
    ou o enqueue falhar (mesmo padrão de `titular.py::eliminar`).
- [x] `ROTAS_PUBLICAS["/portal/imoveis/{imovel_id}/interesse"]`
      (`api/autorizacao.py`).
- [x] `solicitacoes_de_interesse` em `TABELAS` (`tests/conftest.py`) e em
      `TABELAS_COM_CHAVE_DE_LEAD` (`domain/identidade/reindexacao.py`).
- [x] `titular/anonimizacao.py`: `nome` vira `NULL` na eliminação, mesmo
      argumento do `resumo` do handoff (é conteúdo que identifica).
- [x] `tests/integration/test_portal_interesse_endpoint.py`: CA-01..04 +
      isolamento handoff-por-lead vs solicitação-por-imóvel (D2/D4) + rota
      pública sem header.

## Frontend

- [ ] Formulário de interesse na página de detalhe (`/busca/[id]`): telefone
      obrigatório, nome/e-mail opcionais.
- [ ] Função servidor `solicitarInteresse` (`lib/servidor/vitrinePublica.ts`
      ou módulo próprio) chamando a rota nova.
- [ ] Estados: enviando, sucesso ("pedido recebido"), erro de validação
      (telefone), erro genérico, 404 (imóvel ficou indisponível — CA-03),
      429 (rate limit).
- [ ] Testes do formulário e da função servidor.

## Gates antes do PR

- [ ] `ruff check` / `ruff format --check` / `mypy`.
- [ ] `tests/unit`.
- [ ] `tests/integration` (ao menos os arquivos tocados; suíte completa se
      o ambiente permitir).
- [ ] Frontend: testes, lint, build.
- [ ] `scripts/comentarios_tocados.py --checar`.

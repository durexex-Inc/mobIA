# TEC-180 — Exportar para CRM via webhook com retry — plano

Desenho: `docs/superpowers/specs/2026-09-24-tec-180-exportar-para-crm-design.md`
Branch: `feat/tec-180-exportar-para-crm`

## Task 1 — As três colunas em `handoffs` e a migration

- `domain/handoff/models.py`: `crm_sincronizado_em` (timestamptz nulável), `crm_tentativas` (int, `server_default` 0), `crm_ultimo_erro` (`String(80)` nulável).
- `alembic/versions/0043_exportacao_para_crm.py`, sobre a 0042.
- Comentário de cada coluna dizendo o que nulo significa, no molde das vizinhas (`sla_limite_em`, `notificado_em`).
- Índice parcial para a varredura: `crm_sincronizado_em IS NULL`.

Checagem: `alembic upgrade head` e `downgrade` de volta.

## Task 2 — `domain/crm/port.py` e `domain/crm/payload.py`

- `CrmPort` (`Protocol`, `nome: str`, `async def exportar(self, *, payload: dict) -> None`).
- `FalhaDeExportacao(RuntimeError)`, com o mesmo argumento de `FalhaDeCanal`: separa "o destino não aceitou" de defeito de programação, que deve subir.
- `payload.montar(...)` puro, `VERSAO_DO_PAYLOAD = 1`; campos: versão, id do handoff, par `(channel, conversation_key)`, gatilho, etiqueta, prioridade, status, qualificação, resumo (ou `null`) e `resumo_fallback`, carimbos.

Testes unitários do formato e da versão.

## Task 3 — `domain/crm/webhook.py`

- `CrmWebhook` sobre `httpx.AsyncClient`, no molde de `WhatsAppOutbound`: timeout de módulo, cliente injetável para o teste.
- `X-Mobia-Signature-256` quando há segredo; `Idempotency-Key` com o `handoff_id` sempre.
- 2xx entrega; qualquer outra coisa (status, timeout, erro de rede) vira `FalhaDeExportacao`.

## Task 4 — `domain/crm/repositorio.py`

- Ler o handoff com o resumo decifrado (reusar o que `notificacao/envio.py` já faz).
- `marcar_sincronizado`, `registrar_falha` (incrementa `crm_tentativas`, grava só o nome da classe) e a consulta de pendentes da D8.

## Task 5 — `workers/jobs/exportar_crm.py`

A ordem importa e é a D3:

1. `ctx["crm"] is None` → retorna `"desligado"`.
2. `crm_sincronizado_em` preenchido → retorna `"ja_sincronizado"`, sem rede.
3. Monta, exporta. Sucesso → marca e retorna.
4. `FalhaDeExportacao` → incrementa. Se ficou `< 3`, levanta `Retry(defer=base * 2 ** (tentativas - 1))`. Se chegou a 3, **não levanta**: loga `crm.exportacao_falhou_permanente` em `error` e retorna `"falhou"`.

Docstring dizendo por que a contagem não é do ARQ, com o trecho de `arq/worker.py` que o desenho cita.

## Task 6 — `workers/jobs/sweep_crm_pendentes.py`

- `ctx["crm"] is None` → devolve 0 antes de tocar o banco.
- Um `UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED)` zerando `crm_tentativas` e devolvendo os ids, no molde de `sweep_importacoes_travadas`.
- Os dois ramos da D8 (esgotado, e nunca tentado há mais que a janela).
- Enqueue por id, com `_job_id` derivado.

## Task 7 — Config e montagem

- `app/config.py`: `crm_webhook_url`, `crm_webhook_secret`, `crm_timeout_segundos`, `crm_backoff_base_segundos`, cada um com o comentário do porquê do default.
- `workers/main.py`: `ctx["crm"]`, o `warning` único da D2, `functions` e `cron_jobs`.
- `workers/jobs/gerar_resumo.py`: o enqueue da D10.
- `.env.example`.

## Task 8 — Testes de integração e os três gates

- Os cenários do Gherkin, mais o da D3 e o de `ctx["crm"] is None`.
- `ruff check` / `ruff format --check` / `mypy` no escopo `src tests alembic evals scripts`.
- `scripts/comentarios_tocados.py` e `--checar`.
- Suíte inteira, uma vez.

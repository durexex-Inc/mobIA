# TEC-339 — Plano: reverter um agente para uma versão anterior do prompt

Desenho: `docs/superpowers/specs/2026-09-28-tec-339-reverter-prompt-design.md`. **Full-stack**, como a TEC-337 — falta o `tempoDeAtivacaoMs` no backend (TEC-199).

## Backend

- [x] **`api/routes/prompts.py::reverter`**: mede a duração da reversão com `time.perf_counter()` e acrescenta `"tempoDeAtivacaoMs"` na resposta de sucesso (D1). Sem mudança em 404/409.
- [x] **Testes de backend**: `tempoDeAtivacaoMs` presente e não-negativo na resposta de sucesso; ausente em 404/409. Dois testes novos em `tests/features/test_versionar_prompts.py`.
- [x] **Gates do Python**: `ruff check`, `ruff format --check`, `mypy` (`src tests alembic evals scripts`) — limpos. `tests/unit` 4090 passed; `tests/features` 274 passed + 1 falha isolada em `test_atendimento_pelo_widget_web.py` (WebSocket do widget, sem relação com prompts) — 3/3 verde isolada, mesmo padrão de flake já documentado neste arquivo.

## Frontend

- [x] **`lib/prompts.ts`**: `RespostaDoRollback` (`ativa` + `tempoDeAtivacaoMs`).
- [x] **`components/prompts/ReverterVersao.tsx`** (`'use client'`, mesmo molde de `EliminarDadosDoTitular.tsx`): `<dialog>` com confirmação por texto igual ao número da versão (D2), botão desabilitado até bater; ao confirmar, `POST /bff/api/v1/prompts/{AGENTE}/rollback`; sucesso mostra "Revertido para a versão N em X ms" com botão "Fechar" que chama `router.refresh()` (D4); 404/409 mostram a mensagem do backend.
- [x] **`app/(painel)/admin/prompts/[agente]/page.tsx`**: seção "Versões anteriores" lista as versões (já buscadas para o seletor) com `ReverterVersao` ao lado de cada uma que não é a ativa, mais a versão 0 (padrão do código) quando a ativa não é ela (D3).
- [x] **`lib/servidor/bff.ts`**: `{ metodo: 'POST', padrao: ['api', 'v1', 'prompts', '*', 'rollback'] }`.
- [x] **Testes de frontend**: `components/prompts/ReverterVersao.test.tsx` (confirmar com o número certo reverte e mostra o tempo; número errado mantém o botão desabilitado e não chama `fetch`; 404/409 mostram a mensagem do backend), `app/(painel)/admin/prompts/[agente]/page.test.tsx` (o botão aparece por versão não-ativa, não pela ativa; a página de um agente só busca dado do próprio agente — D5), mais um caso em `bff.test.ts`.
- [x] **Gates do frontend**: `npm test` (1301 passed), `npm run lint` (limpo), `tsc --noEmit` (limpo), `npm run build` (Node 24 via fnm) — todos limpos.
- [ ] **Navegador**: os três cenários do Gherkin — mesma lacuna de sessão ADMIN autenticada da TEC-338 (TOTP); cobertos por teste automatizado, registrado no comentário da card.
- [ ] **Jira**: comentar o link do PR, a peça de backend que faltava (D1) e a lacuna de verificação manual; mover para "Em análise".

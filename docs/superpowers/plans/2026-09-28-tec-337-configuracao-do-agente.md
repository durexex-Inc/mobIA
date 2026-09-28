# TEC-337 — Plano: configurar o agente com diff, confirmação e histórico

Desenho: `docs/superpowers/specs/2026-09-28-tec-337-configuracao-do-agente-design.md`. **Full-stack**, como a TEC-335 — falta controle de concorrência no backend (TEC-198).

## Backend

- [x] **`domain/configuracao/repositorio.py`**: `id_da_vigente(session) -> uuid.UUID | None` (D1), sem mudar a assinatura de `configuracao_vigente`.
- [x] **`api/routes/configuracao.py`**: `GET /agente` ganha `"versao"` na resposta; `PedidoDeAlteracao` ganha `seVersao: str | None = None`; `alterar()` compara e devolve `409` antes de validar/gravar quando não bate (D1).
- [x] **Testes de backend**: `409` quando `seVersao` não bate com a vigente (e nada é gravado — a versão anterior permanece); `seVersao` ausente não checa nada (compatibilidade); `seVersao: null` bate com "nunca editado"; `versao` aparece em `GET /agente` e muda depois de um `PATCH` bem-sucedido. Seis testes novos em `tests/features/test_configurar_o_agente.py`.
- [x] **Gates do Python**: `ruff check`, `ruff format --check`, `mypy` (escopo `src tests alembic evals scripts`) — todos limpos. Suíte inteira: `tests/unit` 4090 passed; `tests/integration` 1839/1840 em duas rodadas, cada uma com UMA falha diferente (`test_apresentacao_no_turno.py`, depois `test_sweep_stalled.py` — os dois já documentados como flakeiam sob carga neste arquivo), cada uma 3/3 verde isolada; `tests/features` 273 passed limpo. Com `-n 8 --dist loadfile` a suíte inteira reproduziu o crash do Postgres sob paralelismo já documentado ("Quando o `-n 8` derruba o Postgres") — rodada por blocos depois, como o próprio arquivo recomenda.

## Frontend

- [x] **`lib/servidor/configuracao.ts`** (novo): `buscarConfiguracao` (`GET /api/v1/configuracao/agente` — configuração, limites e versão, D1/D2), `buscarHistorico` (`GET /api/v1/configuracao/agente/historico`), `ErroDeConfiguracao`.
- [x] **`lib/configuracao.ts`** (novo): tipos (`Configuracao`, `Limites`, `Formulario` — só os sete campos desta tela, D0/decisão prévia), `formularioDe`, validação client-side usando os `limites` recebidos (D2, sem hardcode), `diffDe` (D4 — as linhas "atual → novo" para a confirmação), `pedidoDeEdicao` (parcial; `seVersao` é acrescentado por quem chama, não é campo do formulário).
- [x] **`components/FormularioDeConfiguracao.tsx`** (novo): os sete campos (nome, tom, teto de perguntas, cinco pesos, grade de cadência fixa por temperatura — D3 —, orçamento), botão "Salvar" abre a confirmação (D4) em vez de enviar direto.
- [x] **`components/ConfirmarAlteracaoDaConfiguracao.tsx`** (novo, separado): mostra o diff campo a campo, presentational — o `PATCH` com `seVersao` sai de `FormularioDeConfiguracao`; em `409`, mensagem inline com botão "Recarregar" (D5).
- [x] **`components/HistoricoDaConfiguracao.tsx`** (novo): lista as entradas de `GET /agente/historico`, mais recente primeiro (já vem assim), autor/data/mudanças.
- [x] **`app/(painel)/admin/configuracao/page.tsx`** (novo): guarda `CONFIGURAR_AGENTE`, busca configuração e histórico do servidor. `key={dados.versao}` em `FormularioDeConfiguracao` — e não um `useEffect` copiando prop para estado (isso cai no lint `react-hooks/set-state-in-effect` deste repo) — é o que descarta a edição em curso quando uma versão nova chega (após salvar ou após "Recarregar" num 409).
- [x] **`app/(painel)/admin/page.tsx`**: `href: '/admin/configuracao'` na seção "Configuração do agente".
- [x] **`lib/servidor/bff.ts`**: `GET`/`PATCH api/v1/configuracao/agente`, `GET api/v1/configuracao/agente/historico`.
- [x] **Testes de frontend**: `lib/configuracao.test.ts`, `components/FormularioDeConfiguracao.test.tsx` (os quatro cenários do Gherkin, incluindo o 409/recarregar), `components/HistoricoDaConfiguracao.test.tsx`, `app/(painel)/admin/configuracao/page.test.tsx`, mais casos em `bff.test.ts` e `admin/page.test.tsx` (contagem de "ainda não disponível" 2 → 1).
- [x] **Gates do frontend**: `npm test` (1272 passed), `npm run lint` (limpo), `tsc --noEmit` (limpo), `npm run build` (sucesso, Node 24 via fnm) — todos limpos.
- [ ] **Navegador**: não executado nesta rodada — os quatro cenários do Gherkin estão cobertos por teste automatizado (feature tests do backend + component tests do frontend); a verificação manual por CDP fica pendente e é registrada no PR/card.
- [ ] **Jira**: comentar a peça de backend que faltava (D1), a decisão de deixar domínios/aparência fora, e o link do PR; mover para "Em análise".

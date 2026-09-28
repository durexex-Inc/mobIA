# TEC-337 — Plano: configurar o agente com diff, confirmação e histórico

Desenho: `docs/superpowers/specs/2026-09-28-tec-337-configuracao-do-agente-design.md`. **Full-stack**, como a TEC-335 — falta controle de concorrência no backend (TEC-198).

## Backend

- [ ] **`domain/configuracao/repositorio.py`**: `id_da_vigente(session) -> uuid.UUID | None` (D1), sem mudar a assinatura de `configuracao_vigente`.
- [ ] **`api/routes/configuracao.py`**: `GET /agente` ganha `"versao"` na resposta; `PedidoDeAlteracao` ganha `seVersao: str | None = None`; `alterar()` compara e devolve `409` antes de validar/gravar quando não bate (D1).
- [ ] **Testes de backend**: `409` quando `seVersao` não bate com a vigente (e nada é gravado — a versão anterior permanece); `seVersao` ausente não checa nada (compatibilidade); `seVersao: null` bate com "nunca editado"; `versao` aparece em `GET /agente` e muda depois de um `PATCH` bem-sucedido.
- [ ] **Gates do Python**: `ruff check`, `ruff format --check`, `mypy` (escopo `src tests alembic evals scripts`), suíte completa.

## Frontend

- [ ] **`lib/servidor/configuracao.ts`** (novo): `buscarConfiguracao` (`GET /api/v1/configuracao/agente` — configuração, limites e versão, D1/D2), `buscarHistorico` (`GET /api/v1/configuracao/agente/historico`), `ErroDeConfiguracao`.
- [ ] **`lib/configuracao.ts`** (novo): tipos (`Configuracao`, `Limites`, `Formulario` — só os sete campos desta tela, D0/decisão prévia), `formularioDe`, validação client-side usando os `limites` recebidos (D2, sem hardcode), `diffDe` (D4 — as linhas "atual → novo" para a confirmação), `pedidoDeEdicao` (parcial + `seVersao`).
- [ ] **`components/FormularioDeConfiguracao.tsx`** (novo): os sete campos (nome, tom, teto de perguntas, cinco pesos, grade de cadência fixa por temperatura — D3 —, orçamento), botão "Salvar" abre a confirmação (D4) em vez de enviar direto.
- [ ] **`components/ConfirmarAlteracaoDaConfiguracao.tsx`** (novo, ou parte do componente acima): mostra o diff campo a campo, confirma o `PATCH` com `seVersao`; em `409`, mensagem "a configuração mudou" com botão "Recarregar" (D5).
- [ ] **`components/HistoricoDaConfiguracao.tsx`** (novo): lista as entradas de `GET /agente/historico`, mais recente primeiro (já vem assim), autor/data/mudanças.
- [ ] **`app/(painel)/admin/configuracao/page.tsx`** (novo): guarda `CONFIGURAR_AGENTE`, busca configuração e histórico do servidor.
- [ ] **`app/(painel)/admin/page.tsx`**: `href: '/admin/configuracao'` na seção "Configuração do agente".
- [ ] **`lib/servidor/bff.ts`**: `GET`/`PATCH api/v1/configuracao/agente`, `GET api/v1/configuracao/agente/historico`.
- [ ] **Testes de frontend**: `lib/configuracao.test.ts`, `components/FormularioDeConfiguracao.test.tsx` (os quatro cenários do Gherkin, incluindo o 409/recarregar), `components/HistoricoDaConfiguracao.test.tsx`, `app/(painel)/admin/configuracao/page.test.tsx`, mais casos em `bff.test.ts` e `admin/page.test.tsx`.
- [ ] **Gates do frontend**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [ ] **Navegador**: Edge headless por CDP, ADMIN — mudar o teto de perguntas de 5 para 3 e ver "5 → 3" na confirmação; tentar peso -1 e ver a recusa antes do envio; abrir a tela em duas abas, salvar numa, tentar salvar na outra e ver o aviso de conflito com "recarregar"; mudar o nome do assistente e ver a entrada no topo do histórico.
- [ ] **Jira**: comentar a peça de backend que faltava (D1), a decisão de deixar domínios/aparência fora, e o link do PR; mover para "Em análise".

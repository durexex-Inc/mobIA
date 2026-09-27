# TEC-207 — Direitos do titular e retenção: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pedido de titular (WhatsApp e ADMIN) com prazo de 15 dias, exportação JSON, eliminação por anonimização que preserva métricas, retenção de 24/12 meses e auditoria.

**Architecture:** um pacote novo `src/mobia/domain/titular/` (vocabulário, modelo, detecção, repositório, anonimização, exportação, retenção). A anonimização é uma função sync sobre `Connection`, no molde de `identidade/reindexacao.py`: troca o par por um pseudônimo aleatório em todas as tabelas, apaga identidade/vínculo/resumo/apelido, zera o conteúdo das mensagens e devolve as chaves de mídia a apagar depois do commit. Rotas ADMIN novas em `api/routes/titular.py`; job ARQ para a eliminação; sweep diário para a retenção.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.1 async, Alembic, ARQ.

**Spec:** `docs/superpowers/specs/2026-09-26-tec-207-direitos-do-titular-design.md` — leia antes de qualquer task.

## Global Constraints

- Gates antes de todo commit: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`; `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`; `./.venv/Scripts/python.exe -m mypy`.
- Comentários e docstrings em `src/`/`tests/`: português **sem acento**. Texto que o lead recebe: **com acento**. Prosa em `docs/`: com acento.
- Comentário diz o porquê; comentário que o código desmente é defeito.
- `.md`: cite código por âncora `arquivo.py::Nome`, nunca por número de linha em linha nova; `scripts/comentarios_tocados.py --checar` antes do PR.
- Commits `tipo(TEC-207): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Migration nova: `0063`, `down_revision = "0062"`. Tuplas copiadas na migration são literais.
- Prazo: **15 dias**. Retenção: **24 meses** (lead sem handoff `ACEITO`/`CONCLUIDO`, desde `max(messages.created_at)`) e **12 meses** (conteúdo de mensagem).
- Unitários sem Docker: `./.venv/Scripts/python.exe -m pytest tests/unit`. Integração exige `docker compose up -d`. Suíte inteira UMA vez no fim (Task 8), por blocos se o `-n 8` derrubar o Postgres (ver `CLAUDE.md`).

## Review Focus

1. **Lead já em opt-out pede para apagar os dados**: o pedido é registrado e a confirmação chega (o portão de silêncio e a guarda de envio não o engolem). → Task 4.
2. **"Remover meu contato" continua opt-out; "remover meus dados" é pedido de titular.** → Task 2.
3. **O funil e o custo do período são idênticos antes e depois de anonimizar.** → Task 5.
4. **Visitante web que volta com a mesma sessão depois da anonimização** não reencontra as mensagens antigas (a chave dela não bate mais com nada, nem no prefixo do `provider_message_id`). → Task 5.
5. **Lead convertido (handoff aceito) com 25 meses parado não é anonimizado**, mas a transcrição dele é esvaziada aos 12. → Task 7.

---

### Task 1: vocabulário, modelo, migration `0063` e permissão

**Files:**
- Create: `src/mobia/domain/titular/__init__.py`, `src/mobia/domain/titular/vocabulario.py`, `src/mobia/domain/titular/models.py`
- Create: `alembic/versions/0063_solicitacoes_de_titular.py`
- Modify: `src/mobia/domain/auditoria/vocabulario.py` (`Acao`, `Entidade`), `src/mobia/domain/usuarios/permissoes.py` (`ATENDER_TITULAR` em `DE_ESCRITA`), `src/mobia/domain/identidade/reindexacao.py` (`TABELAS_COM_CHAVE_DE_LEAD` ganha `solicitacoes_de_titular`), `tests/conftest.py` (`TABELAS` ganha `solicitacoes_de_titular`), `tests/unit/test_auditoria_vocabulario.py` (`test_a_tupla_vem_da_migration_mais_recente` aponta os valores novos)
- Test: `tests/unit/test_titular_vocabulario.py`

**Interfaces — Produces:**
- `vocabulario.TipoDeSolicitacao(StrEnum)`: `ELIMINACAO`, `ACESSO`.
- `vocabulario.OrigemDaSolicitacao(StrEnum)`: `WHATSAPP`, `ADMIN`, `RETENCAO`.
- `vocabulario.StatusDaSolicitacao(StrEnum)`: `ABERTA`, `ATENDIDA`, `RECUSADA`.
- `vocabulario.PRAZO_DO_TITULAR = timedelta(days=15)`; `vocabulario.RETENCAO_DO_LEAD_MESES = 24`; `vocabulario.RETENCAO_DA_TRANSCRICAO_MESES = 12`.
- `models.SolicitacaoDeTitular` (`solicitacoes_de_titular`): `id UUID PK`, `lead_ref CHAR(64) NOT NULL`, `channel String(32) NULL`, `conversation_key String(64) NULL`, `tipo String(16)`, `origem String(16)`, `status String(16)`, `motivo_da_recusa Text NULL`, `recebida_em timestamptz server_default now()`, `prazo_em timestamptz NOT NULL`, `atendida_em timestamptz NULL`. CHECKs dos três enums; CHECK `(status = 'ABERTA') = (channel IS NOT NULL)` (o par só existe enquanto aberta); índice único parcial `uq_solicitacao_aberta` em `(lead_ref, tipo) WHERE status = 'ABERTA'`; índice em `(status, prazo_em)`.
- `Acao`: `TITULAR_SOLICITOU`, `DADOS_EXPORTADOS`, `LEAD_ANONIMIZADO`, `TITULAR_RECUSADO`. `Entidade`: `SOLICITACAO_DE_TITULAR = "solicitacao_de_titular"`.
- `Permissao.ATENDER_TITULAR` — só ADMIN (fora de `_CONCEDIDAS`), em `DE_ESCRITA`, com comentário no molde de `OPERAR_FILA`.

- [ ] **Step 1: testes que falham** — `tests/unit/test_titular_vocabulario.py`: `PRAZO_DO_TITULAR == timedelta(days=15)`; `permissoes_de("ADMIN")` contém `ATENDER_TITULAR` e `GERENTE`/`CORRETOR`/`LEITURA` não; `ATENDER_TITULAR in DE_ESCRITA`. O teste existente `test_o_vocabulario_bate_com_o_check_da_migration` vai reprovar assim que o enum ganhar valores sem migration — é o sinal certo.
- [ ] **Step 2: rodar e ver falhar.**
- [ ] **Step 3: implementar** vocabulário, modelo, enums, permissão. Migration `0063`, no molde de `0057_injecao_na_trilha.py` para os CHECKs da trilha:
  - `_ACOES` = a tupla da `0059` + os quatro valores novos; `_ENTIDADES` = a tupla da `0057` + `"solicitacao_de_titular"`; `_ACOES_ANTERIORES`/`_ENTIDADES_ANTERIORES` = sem os novos; downgrade recria com `NOT VALID`. O arquivo tem de conter a string `eventos_auditoria` (o teste de vocabulário procura por ela).
  - `op.create_table("solicitacoes_de_titular", ...)` com os CHECKs e índices acima; downgrade dropa.
  - Docstring da migration explica por que o par é nulável (some ao atender) e por que `lead_ref` fica.
- [ ] **Step 4: rodar** `tests/unit` e, com Docker, `tests/integration/test_migrations.py` e `tests/unit/test_tabelas_com_chave_de_lead.py`.
- [ ] **Step 5: gates e commit** — `feat(TEC-207): a solicitacao de titular existe, com prazo, e a trilha a nomeia`.

---

### Task 2: detectar o pedido de titular no texto

**Files:**
- Create: `src/mobia/domain/titular/deteccao.py`
- Test: `tests/unit/test_titular_deteccao.py`

**Interfaces — Produces:** `pedido_de_titular(texto: str) -> TipoDeSolicitacao | None`; `TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO`, `TEXTO_DA_CONFIRMACAO_DE_ACESSO` (com acento, texto do spec D3); `KIND_DA_CONFIRMACAO_DE_TITULAR = "titular_confirmacao"`.

- [ ] **Step 1: testes que falham** (parametrizados):
  - Eliminação: "quero apagar meus dados", "Apague meus dados, por favor", "excluir meus dados", "deletem os meus dados", "podem esquecer meus dados?", "quero que apaguem todos os meus dados pessoais".
  - Acesso: "quero meus dados", "quais dados vocês têm de mim?", "quero ver os meus dados", "me mandem uma cópia dos meus dados".
  - **Não é pedido** (devolve `None`): "remover meu contato" (é opt-out), "parar", "quero um apartamento", "os dados do imóvel estão errados", "vocês têm os dados do condomínio?", "não quero apagar meus dados" (negação), "".
  - **Precedência:** para cada frase de eliminação/acesso acima, `pediu_optout(frase)` pode ser qualquer coisa — o teste afirma só `pedido_de_titular`; e para "remover meu contato", `pedido_de_titular` é `None` e `pediu_optout` é `True`.
- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar**, reusando a normalização de `optout/deteccao.py` (importe `_normalizar` se o módulo aceitar; se preferir não importar privado, promova-o a `normalizar` lá, com o ajuste mínimo nos usos). Regras:
  - Casa só quando a frase fala de **dados do próprio lead**: "meus dados", "os meus dados", "dados pessoais", "dados de mim", "dados que vocês têm". "Dados" sozinho (do imóvel, do condomínio) não casa.
  - Eliminação: verbo de apagar (`apag`, `exclu`, `delet`, `remov`, `esquec`, `elimin`) + objeto de dados do lead.
  - Acesso: objeto de dados do lead + verbo/pergunta de ver/receber (`quero meus dados`, `quais dados`, `ver`, `copia`, `mandem`, `enviem`) sem verbo de apagar.
  - Negação imediatamente antes do verbo ("nao quero apagar", "nao apague") → `None`. Use a mesma abordagem de `humano/deteccao.py` (`_casa_sem_negacao`) se couber.
  - Docstring do módulo: por que determinístico (decisão de LGPD não depende de provedor), e a regra de precedência sobre o opt-out.
- [ ] **Step 4: rodar** `tests/unit/test_titular_deteccao.py` e os testes de opt-out/humano unitários.
- [ ] **Step 5: gates e commit** — `feat(TEC-207): o pedido de titular e reconhecido no texto sem chamar o modelo`.

---

### Task 3: repositório da solicitação

**Files:**
- Create: `src/mobia/domain/titular/repositorio.py`
- Test: `tests/integration/test_titular_repositorio.py`

**Interfaces — Produces:**
- `async registrar_solicitacao(session, *, channel, conversation_key, tipo, origem, ator: Ator) -> uuid.UUID` — idempotente: se já existe `ABERTA` do mesmo `(lead_ref, tipo)`, devolve o id dela sem criar (use `INSERT ... ON CONFLICT DO NOTHING` sobre `uq_solicitacao_aberta` e depois `SELECT`). Calcula `lead_ref` com `auditoria/referencia.py::lead_ref` e `Settings.auditoria_chave_do_lead`; `prazo_em = agora + PRAZO_DO_TITULAR`. Registra `TITULAR_SOLICITOU` (entidade `SOLICITACAO_DE_TITULAR`, `lead=(channel, conversation_key)`) só quando cria. Não commita.
- `async solicitacao_aberta(session, *, channel, conversation_key, tipo) -> SolicitacaoDeTitular | None`.
- `async marcar_atendida(session, solicitacao_id, *, agora) -> None` — status `ATENDIDA`, `atendida_em`, par nulo.
- `async recusar(session, solicitacao_id, *, motivo: str, ator: Ator) -> None` — só de `ABERTA`; motivo obrigatório não vazio; par nulo; registra `TITULAR_RECUSADO`. Levanta `SolicitacaoNaoAberta` se não estiver aberta.
- `async listar(session, *, status: StatusDaSolicitacao | None) -> list[SolicitacaoDeTitular]` — ordem `prazo_em`, depois `recebida_em`.
- `async vencidas(session, *, agora, tipo) -> list[SolicitacaoDeTitular]` — `ABERTA` com `prazo_em <= agora`.

- [ ] **Step 1: testes que falham** — registrar cria com prazo de 15 dias e evento na trilha; registrar de novo o mesmo tipo devolve o mesmo id e não cria evento; tipos diferentes coexistem; recusar sem motivo reprova; recusar zera o par e registra evento; `marcar_atendida` zera o par; recusar uma atendida levanta `SolicitacaoNaoAberta`; `vencidas` só devolve as abertas com prazo passado.
- [ ] **Step 2: ver falhar. Step 3: implementar. Step 4: rodar.**
- [ ] **Step 5: gates e commit** — `feat(TEC-207): solicitacao de titular registrada, recusada e atendida com trilha`.

---

### Task 4: o turno atende o pedido de titular

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (`_executar_turno`, e o tipo `ResultadoDoTurno`), `src/mobia/domain/outbound/port.py` (`GuardedOutbound.send`: as duas guardas passam a aceitar também `KIND_DA_CONFIRMACAO_DE_TITULAR`)
- Test: `tests/integration/test_turno_titular.py`

**Interfaces — Consumes:** Task 2 (`pedido_de_titular`, textos, kind) e Task 3 (`registrar_solicitacao`); `optout/repositorio.py::registrar_optout`, `esta_em_optout`; `_entregar_texto_fixo`.

- [ ] **Step 1: testes que falham** — no molde de `tests/integration/test_turno_optout.py` (mesmas fixtures `classificador_fake`, `outbound_fake`, `moderador_fake`, `resumidor_fake`, `contador_fake`, e `_mensagem_gravada`):
  - "quero apagar meus dados" → resultado `"pedido_de_titular"`; `classificador.chamadas == 0`; moderador **não** chamado; uma solicitação `ELIMINACAO` `ABERTA` com o par; `esta_em_optout` verdadeiro; `outbound.entregues` tem `TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO`.
  - "quero meus dados" → solicitação `ACESSO`; **sem** opt-out; confirmação de acesso.
  - **Lead já em opt-out** (registre antes com `registrar_optout`) pede para apagar → solicitação criada e confirmação entregue (não "silenciado").
  - **Conversa em atendimento humano** (use o helper que os testes de `test_turno_*humano*` usam) → a confirmação ainda sai.
  - Pedir duas vezes → uma solicitação só; duas confirmações.
- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar.**
  - Em `_executar_turno`, logo depois de `pedido_de_humano = ...`: `tipo_de_titular = pedido_de_titular(corpo) if corpo else None`.
  - **Antes do portão de silêncio por opt-out** (`if not pedido_de_optout: ... esta_em_optout`), um bloco `if tipo_de_titular is not None:` que:
    1. abre sessão, chama `registrar_solicitacao(..., origem=WHATSAPP, ator=ATOR_SISTEMA)` e commita;
    2. se `ELIMINACAO` e ainda não em opt-out, chama `registrar_optout` (transação própria, como no bloco de opt-out);
    3. entrega o texto fixo do tipo por `_entregar_texto_fixo(..., kind=KIND_DA_CONFIRMACAO_DE_TITULAR, subagent=SUBAGENTE_TITULAR)` (constante nova ao lado de `SUBAGENTE_OPTOUT`);
    4. devolve `"pedido_de_titular"` (ou o desfecho da entrega, como o bloco de opt-out faz).
    Comentário explica: por que antes do portão de silêncio e da moderação, e por que o opt-out junto.
  - Acrescente `"pedido_de_titular"` a `ResultadoDoTurno` e a quem trata os resultados (grep `"opt_out"` em `src` para achar os consumidores e o mapeamento para status da mensagem).
  - Em `GuardedOutbound.send`, as duas condições `kind != KIND_DA_CONFIRMACAO_DE_OPTOUT` passam a `kind not in KINDS_QUE_FURAM_AS_GUARDAS` (constante nova em `port.py` = `{KIND_DA_CONFIRMACAO_DE_OPTOUT, KIND_DA_CONFIRMACAO_DE_TITULAR}`). Os comentários longos sobre a exceção única passam a dizer que são duas, com a razão da segunda. Em `_entregar_texto_fixo`, a checagem `kind != KIND_DA_CONFIRMACAO_DE_OPTOUT and await _bloqueado_por_optout_concorrente(...)` recebe o mesmo tratamento.
- [ ] **Step 4: rodar** `tests/integration/test_turno_titular.py`, `test_turno_optout.py`, `test_optout_guarda.py`, `test_optout_fura_a_janela.py` e os testes unitários.
- [ ] **Step 5: gates e commit** — `feat(TEC-207): o lead pede pelo WhatsApp e o pedido entra na fila com prazo`.

---

### Task 5: anonimizar o lead

**Files:**
- Create: `src/mobia/domain/titular/anonimizacao.py`, `src/mobia/domain/titular/eliminacao.py`
- Modify: `src/mobia/domain/midia/armazem.py` (`apagar` na porta e nas duas implementações)
- Test: `tests/integration/test_anonimizacao.py`, `tests/unit/test_armazem_apagar.py`

**Interfaces — Produces:**
- `ArmazemDeMidia.apagar(chave: str) -> None` — local: `unlink(missing_ok=True)` via `asyncio.to_thread`, com a mesma checagem de `_caminho`; S3: `delete_object`.
- `anonimizacao.anonimizar_lead(conn: Connection, *, channel: str, conversation_key: str) -> list[str]` — sync, não commita; devolve as `chave_no_armazem` a apagar depois do commit.
- `eliminacao.anonimizar(session_factory, armazem: ArmazemDeMidia, *, solicitacao_id: uuid.UUID) -> None` — orquestra: carrega a solicitação (tem o par), roda `anonimizar_lead` via `await session.run_sync(lambda s: anonimizar_lead(s.connection(), ...))`, registra `LEAD_ANONIMIZADO` (entidade `SOLICITACAO_DE_TITULAR`, `lead=` par antigo), `marcar_atendida`, commit; depois apaga cada blob (falha ao apagar blob loga `titular.midia_nao_apagada` com a chave e segue — o dado já está desligado do lead). Solicitação que não está `ABERTA` → não faz nada e loga.

`anonimizar_lead`, na ordem, numa transação só (o chamador a abre):
1. `novo = secrets.token_hex(32)`.
2. Lê as chaves de mídia: `SELECT mr.chave_no_armazem FROM midias_recebidas mr JOIN messages m ON m.id = mr.message_id WHERE m.channel = :c AND m.conversation_key = :k AND mr.chave_no_armazem IS NOT NULL`; depois `DELETE FROM midias_recebidas WHERE message_id IN (SELECT id FROM messages WHERE channel = :c AND conversation_key = :k)`.
3. `DELETE` do par em `conversation_summaries`, `vinculos_de_sessao`, `identidades_de_lead`, `referencias_de_lead`.
4. `UPDATE messages SET text_body = NULL, raw_payload = NULL, envelope_context = NULL WHERE channel = :c AND conversation_key = :k`. `UPDATE handoffs SET resumo = NULL WHERE ...` (o resumo do handoff é derivado da transcrição).
5. Desliga as triggers de `lead_score_audit` e `conversation_intent_audit` (não a de `eventos_auditoria`: a trilha não é tocada) — reuse `reindexacao.TRIGGERS_DE_IMUTABILIDADE` filtrando essas duas, ou exporte de lá uma função `desligar_triggers(conn, tabelas)`/`religar_triggers` e use nos dois módulos.
6. `UPDATE {tabela} SET conversation_key = :novo WHERE channel = :c AND conversation_key = :k` para cada tabela de `TABELAS_COM_CHAVE_DE_LEAD` que ainda tem linhas do par (as apagadas no passo 3 não têm).
7. `messages.sender_external_id`/`recipient_external_id` iguais à chave velha → `novo` (como `reindexacao._mover`); prefixo do `provider_message_id` web → `novo` (mesmo `LIKE ... ESCAPE` de `_mover`; extraia a função de lá em vez de copiar); `rate_limit_events.chave` (escopo `numero`) → `novo`.
8. Religa as triggers — só no caminho de sucesso, como `reindexar` faz.

Docstring do módulo: o pseudônimo é aleatório e não tem volta (diferente do HMAC da TEC-203); a trilha fica com o `lead_ref` antigo, que deixa de bater; o que é mantido e por quê (métricas: coorte do funil por `min(messages.created_at)`, custo por `message_telemetry`).

- [ ] **Step 1: testes que falham** (`tests/integration/test_anonimizacao.py`). Semeie um lead WhatsApp completo — use os helpers do `tests/conftest.py` (`_lead`, `_handoff_aceito`, `_agendar`) e `identidade/indice.py::registrar` —, com mensagens de entrada e saída, resumo, qualificação, trilha de score, handoff com resumo, agendamento, consentimento, opt-out, mídia armazenada (`ArmazemLocal` em `tmp_path`), evento de rate limit e um evento de auditoria. Casos:
  - Nenhuma coluna de texto das tabelas de `TABELAS_COM_CHAVE_DE_LEAD` + `rate_limit_events` guarda a chave antiga nem o telefone; `identidades_de_lead`, `vinculos_de_sessao`, `conversation_summaries`, `referencias_de_lead` não têm linha do par; `text_body`/`raw_payload`/`envelope_context` nulos; o arquivo de mídia sumiu; `handoffs.resumo` nulo.
  - **Métricas iguais**: com `metricas/filtros.py::montar_recorte` cobrindo o período, `contar_etapas`, `calcular_indicadores(novos=...)` e `custo/custo_do_periodo` dão o mesmo resultado antes e depois.
  - As triggers de `lead_score_audit` e `conversation_intent_audit` voltam ligadas (um `UPDATE` reprova).
  - `eventos_auditoria` inalterada, exceto o evento `LEAD_ANONIMIZADO` novo.
  - **Web**: sessão com mensagens (`provider_message_id` com prefixo da chave); depois de anonimizar, `chave_de("web", sessao)` não aparece em nenhuma coluna, nem como prefixo.
  - Solicitação vira `ATENDIDA` com par nulo; chamar de novo não faz nada.
  - Unitário do armazém local: `apagar` remove; apagar inexistente não levanta; chave fora do diretório levanta `ValueError`.
- [ ] **Step 2: ver falhar. Step 3: implementar. Step 4: rodar** os novos, `test_reindexacao_do_lead.py` (se extraiu funções de lá) e `tests/unit`.
- [ ] **Step 5: gates e commit** — `feat(TEC-207): anonimizar troca o lead por pseudonimo sem volta e preserva as metricas`.

---

### Task 6: rotas ADMIN e job de eliminação

**Files:**
- Create: `src/mobia/domain/titular/exportacao.py`, `src/mobia/api/routes/titular.py`, `src/mobia/workers/jobs/eliminar_lead.py`
- Modify: `src/mobia/app/main.py` (`include_router`, com uma linha no comentário que explica cada router), `src/mobia/workers/main.py` (`functions`: `func(eliminar_lead, keep_result=0)`)
- Test: `tests/integration/test_rotas_de_titular.py`, `tests/integration/test_job_eliminar_lead.py`

**Interfaces — Produces:**
- `exportacao.exportar(session, *, lead_id: uuid.UUID, par: tuple[str, str]) -> dict[str, object] | None` — `None` se `leads/detalhe.py::ler_detalhe` devolve `None`. JSON:
  ```
  {"exportadoEm", "canal", "telefone" ("+55..." ou null, por identidade.indice.telefones_de),
   "qualificacao", "score", "agendamentos", "recomendacoes", "followups",
   "consentimentos": [{"marketing", "textoExibido", "registradoEm"}],
   "transcricao": [{"autor", "tipo", "conteudo", "em"}]}
  ```
  A transcrição inteira: pagine `leads/transcricao.py::pagina_da_transcricao` com `ve_retidas=True` e `LIMITE_MAXIMO_DA_TRANSCRICAO` até o cursor acabar. Datas em ISO 8601. Chaves em camelCase, como o resto da API.
- `ELIMINAR_LEAD_JOB = "eliminar_lead"`; `async eliminar_lead(ctx, solicitacao_id: str) -> None` — chama `eliminacao.anonimizar(ctx["session_factory"], armazem_da_config(ctx["settings"]), solicitacao_id=uuid.UUID(...))`. Confirme em `workers/main.py::startup` que `ctx["settings"]` existe; se não, use `get_settings()`.
- Rotas (todas `Depends(Exige(Permissao.ATENDER_TITULAR))`):
  - `GET /api/v1/titular/solicitacoes?status=` → `{"itens": [{"id", "tipo", "origem", "status", "recebidaEm", "prazoEm", "atendidaEm", "motivoDaRecusa", "leadId"}]}`; `leadId` via `leads/repositorio.py::referencias_para` quando o par existe, senão `null`. Status inválido → 422.
  - `GET /api/v1/leads/{lead_id}/dados-pessoais` → `par_de` (404 se não resolve); `exportar`; registra `DADOS_EXPORTADOS` (entidade `LEAD`, `entidade_id=str(lead_id)`, `lead=par`); se há `ACESSO` aberta para o par, `marcar_atendida`; commit; devolve o JSON.
  - `DELETE /api/v1/leads/{lead_id}/dados-pessoais` → `par_de` (404); pega a `ELIMINACAO` aberta ou registra uma com `origem=ADMIN` e o ator da requisição; commit; enfileira `eliminar_lead` com `_job_id=f"titular:{solicitacao_id}"` no `request.app.state.redis_pool` (sem pool ou falha ao enfileirar → 503, no molde de `api/routes/imoveis.py`); 202 `{"solicitacaoId", "status": "ABERTA"}`.
  - `POST /api/v1/titular/solicitacoes/{id}/recusa` body `{"motivo": str}` (1..2000, sem só espaço) → `recusar`; 404 se não existe; 409 se não está aberta; 200 com a solicitação.
- [ ] **Step 1: testes que falham** — com o `_bearer` de `tests/integration/test_rota_de_auditoria.py`:
  - GERENTE/CORRETOR/LEITURA → 403 em todas; ADMIN → ok.
  - Exportação traz telefone revelado, qualificação, transcrição completa com mais de 200 mensagens (paginação), consentimento; evento `DADOS_EXPORTADOS` na trilha; solicitação `ACESSO` aberta vira atendida.
  - `DELETE` → 202 e um job `eliminar_lead` no `redis_pool` (inspecione as chaves do ARQ ou `pool.queued_jobs()`); a solicitação da origem WhatsApp aberta é reaproveitada; depois de rodar o job à mão (`await eliminar_lead(ctx, id)`), `GET /leads/{id}` e `DELETE` de novo dão 404.
  - Recusa: motivo vazio 422; ok 200 com `RECUSADA` e par nulo; recusar de novo 409.
  - Fila ordenada por prazo, com `leadId` nulo nas atendidas.
- [ ] **Step 2–4: ver falhar, implementar, rodar.**
- [ ] **Step 5: gates e commit** — `feat(TEC-207): o ADMIN exporta, elimina e recusa pedidos de titular pela API`.

---

### Task 7: retenção

**Files:**
- Create: `src/mobia/domain/titular/retencao.py`, `src/mobia/workers/jobs/sweep_retencao_de_leads.py`
- Modify: `src/mobia/workers/main.py` (`functions` e `cron_jobs`: diário às **5h**, uma hora depois do `sweep_retencao_auditoria`, com comentário no molde do dele)
- Test: `tests/integration/test_retencao_de_leads.py`

**Interfaces — Produces:**
- `async esvaziar_transcricoes_vencidas(session_factory, armazem, *, lote: int = 500) -> int` — em lotes: mensagens com `created_at < clock_timestamp() - interval '12 months'` e algum conteúdo não nulo → lê chaves de mídia, apaga `midias_recebidas` dessas mensagens, zera `text_body`/`raw_payload`/`envelope_context`, commit; depois apaga os blobs. Também apaga `conversation_summaries` de pares cuja última mensagem é mais velha que 12 meses. Loga `titular.transcricoes_esvaziadas` com a contagem.
- `async anonimizar_leads_vencidos(session_factory, armazem, *, lote: int = 100) -> int` — pares com `max(messages.created_at) < clock_timestamp() - interval '24 months'` e **sem** handoff `ACEITO`/`CONCLUIDO`; para cada um, registra uma solicitação `ELIMINACAO` com `origem=RETENCAO` (ou reaproveita a aberta) e chama `eliminacao.anonimizar`. Um lead por transação. Loga `titular.leads_anonimizados_por_retencao`.
- `async cumprir_eliminacoes_vencidas(session_factory, armazem) -> int` — `repositorio.vencidas(tipo=ELIMINACAO)` → `eliminacao.anonimizar` para cada.
- `async sweep_retencao_de_leads(ctx, lote: int = 500) -> int` — chama as três, nessa ordem: cumprir vencidas, anonimizar vencidos, esvaziar transcrições.
- Pares já anonimizados não voltam a ser anonimizados: `anonimizar_leads_vencidos` ignora pares sem `identidades_de_lead` (o anonimizado não tem) — escreva isso na docstring.
- [ ] **Step 1: testes que falham** (datas antigas via `UPDATE messages SET created_at = now() - interval '...'` depois de semear):
  - mensagem de 13 meses: conteúdo nulo e mídia apagada; de 11 meses: intacta.
  - lead sem handoff, última mensagem há 25 meses: anonimizado, com solicitação `RETENCAO` `ATENDIDA`; há 23 meses: intacto.
  - **lead com handoff `ACEITO` há 25 meses: não anonimizado**, mas conteúdo esvaziado.
  - solicitação `ELIMINACAO` aberta com prazo vencido: cumprida; com prazo no futuro: intacta.
  - rodar o sweep duas vezes: a segunda não muda nada.
- [ ] **Step 2–4: ver falhar, implementar, rodar.**
- [ ] **Step 5: gates e commit** — `feat(TEC-207): a retencao esvazia transcricao de 12 meses e anonimiza lead parado ha 24`.

---

### Task 8: docs, emendas e verificação final

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, `docs/seguranca/segredos.md` (só se citar algo afetado), docstrings tocadas, spec (status)

- [ ] **Step 1: emendas ao SRS**, aninhadas no formato `Emenda E-nn (TEC-207, 26/09/2026)` abaixo da regra, sem reescrever o texto original (use o próximo número livre de cada regra):
  - **RNF-21:** o pedido pelo WhatsApp entra numa fila com prazo de 15 dias, atendida pelo ADMIN (permissão `ATENDER_TITULAR`); o que o ADMIN não executa nem recusa no prazo é cumprido pela retenção. Correção continua pelo dashboard (TEC-194); pedido de correção pelo WhatsApp não é detectado.
  - **RNF-22:** "lead sem conversão" = sem handoff `ACEITO`/`CONCLUIDO`; anonimização = par trocado por pseudônimo aleatório sem volta, identidade/vínculo/resumo/apelido apagados, conteúdo das mensagens zerado, linhas mantidas para as métricas; o que foi para o CRM externo não é apagado por nós.
  - **§6.7:** `DELETE .../dados-pessoais` devolve 404 para lead já anonimizado (o apelido some); a recusa por retenção legal é `POST /api/v1/titular/solicitacoes/{id}/recusa`, não um 409.
- [ ] **Step 2: docstrings que a card tornou falsas** — `leads/detalhe.py::ler_detalhe` ("a TEC-207 vai eliminar" → o que acontece agora), `midia/models.py` (a docstring do CASCADE: o blob não some pelo CASCADE; a anonimização e a retenção o apagam), `atendimento/fala.py` (comentário que prevê mensagens eliminadas), `auditoria/referencia.py::lead_ref` se algo mudou, e o que `scripts/comentarios_tocados.py` apontar.
- [ ] **Step 3:** `./.venv/Scripts/python.exe scripts/comentarios_tocados.py` (releia `ALTERADO`/`VIZINHO`) e `--checar` (exit 0).
- [ ] **Step 4: os três gates.**
- [ ] **Step 5: suíte inteira UMA vez** — `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`; se o Postgres cair, reinicie e rode por blocos. Guarde hash e resultado.
- [ ] **Step 6: spec** — `**Status:** implementado, PR aberto`.
- [ ] **Step 7: commit** — `docs(TEC-207): emendas ao SRS e docstrings que a eliminacao tornou falsas`.

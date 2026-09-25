# TEC-195 — Mascarar dado pessoal por permissão, com auditoria

**Desenho:** `docs/superpowers/specs/2026-09-25-tec-195-mascarar-dado-pessoal-com-auditoria-design.md`
**Branch:** `feat/tec-195-mascarar-dado-pessoal-com-auditoria`

---

### Task 1: A máscara, pura e sem I/O

**Files:** `src/mobia/domain/leads/mascara.py` (novo), `tests/unit/test_mascara_de_dado_pessoal.py` (novo)

- [ ] **Step 1: `mascarar_telefone`** (D6). Entra pela forma canônica de `identidade/telefone.py::normalizar`; sai `+55 11 9****-**21`. O que não normaliza devolve `None` — a `conversation_key` do canal web é UUID de sessão, não telefone, e formatá-la como se fosse mentiria sobre o que é.
- [ ] **Step 2: `mascarar_email`** (D6, D7). Primeiro e último do local, primeiro e último do domínio antes do TLD, TLD inteiro.
- [ ] **Step 3: o degrau é sempre para esconder.** Entrada curta demais para a regra é mascarada por inteiro menos o último caractere. Escrito como teste, não só como comentário: `a@b.com`, `ab@cd.io`, local de um caractere, domínio sem ponto.
- [ ] **Step 4: a docstring de `mascarar_email` declara que a função não tem chamador**, e por quê (D7) — nenhuma tabela guarda e-mail de lead. Sem isso, o primeiro leitor a encontrá-la vai tentar "ligar".

---

### Task 2: A tabela de referência

**Files:** `alembic/versions/0056_referencias_de_lead.py` (novo), `src/mobia/domain/leads/models.py` (novo)

- [ ] **Step 1: `down_revision` conferido contra `alembic heads`** (`0055`), e não presumido — é o que produziu a TEC-377.
- [ ] **Step 2: a tabela** (D2): `id` uuid PK, `channel`, `conversation_key`, `criado_em`, `UNIQUE (channel, conversation_key)`.
- [ ] **Step 3: na MESMA migration, o CHECK `ck_eventos_auditoria_entidade` é recriado** com `lead` (D5). Drop e create — o Postgres não estende CHECK.
- [ ] **Step 4: a docstring da migration guarda o porquê da tabela**, que é a parte que não se lê do DDL: o par é o dado pessoal, e o handle existe para que ele pare de sair da API.

---

### Task 3: O vocabulário da trilha ganha `LEAD`

**Files:** `src/mobia/domain/auditoria/vocabulario.py`, `tests/unit/test_auditoria_vocabulario.py`

- [ ] **Step 1: `Entidade.LEAD = "lead"`**, e `CAMPO_TELEFONE` / `CAMPO_EMAIL` ao lado de `CAMPO_RESUMO`.
- [ ] **Step 2: o comentário de `CAMPO_RESUMO` deixa de dizer "O unico `campo` com chamador hoje"** — passa a ser falso. É o `VIZINHO` mais provável desta branch.
- [ ] **Step 3: o teste que prende as cópias passa a ler a migration mais recente que define cada CHECK**, e não a `0053` fixa. Sem isto ele reprova: o enum ganhou um valor que a `0053` não tem. **Cuidado:** a correção não pode ser afrouxar o teste — ele existe para que enum e banco não divirjam.

---

### Task 4: O repositório resolve e cria handles

**Files:** `src/mobia/domain/leads/repositorio.py`, `src/mobia/domain/leads/consulta.py`

- [ ] **Step 1: `referencia_de` (get-or-create)** com `ON CONFLICT (channel, conversation_key) DO NOTHING` seguido de releitura (D2). Duas requisições simultâneas não podem dar dois handles ao mesmo lead.
- [ ] **Step 2: `par_de(lead_id)`** — o caminho inverso, que a revelação usa. Devolve `None` para handle inexistente, e a rota traduz em 404.
- [ ] **Step 3: `Cursor` troca `channel`/`conversation_key` por `lead_id`** (D3), e a consulta junta `referencias_de_lead` para o desempate.
- [ ] **Step 4: a docstring de `Cursor` registra que o conteúdo deixou de ser dado pessoal**, e que é por isso que "opaco não é segurança" agora basta.
- [ ] **Step 5: `listar_leads` devolve o handle e o telefone mascarado** por item; `_onde_a_busca_bate` fica como está (D8), e ganha uma linha dizendo que a busca por telefone é confirmação e não revelação.

---

### Task 5: A rota da lista para de vazar

**Files:** `src/mobia/api/routes/leads.py`

- [ ] **Step 1: `conversationKey` sai do item; entram `leadId` e `telefone`** (mascarado, ou `null`).
- [ ] **Step 2: a docstring do módulo perde o parágrafo que diz que o telefone "só poderia sair mascarado, o que é a TEC-195"** — é esta card. Ganha no lugar o porquê de `leadId` existir, e o apontamento para a D2 da TEC-192 que ele revisita.
- [ ] **Step 3: nenhum ramo por papel.** Todo chamador recebe mascarado (D4) — se aparecer um `if identidade.pode(...)` nesta rota, o desenho foi contrariado.

---

### Task 6: A rota da revelação

**Files:** `src/mobia/api/routes/leads.py`

- [ ] **Step 1: `POST /api/v1/leads/{leadId}/revelar`**, `Exige(Permissao.VER_DADOS_COMPLETOS)`, corpo `{"campo": "telefone"}` (D5).
- [ ] **Step 2: o registro ANTES do valor**, e `commit` antes do `return` — molde de `handoffs.py`. Registra a tentativa: se o valor falhar em montar, a trilha diz "acessado" e a resposta é erro.
- [ ] **Step 3: `campo` fora do vocabulário é 422**, e não 500. `email` é aceito pelo vocabulário e devolve `null` com a razão — não há fonte (D7).
- [ ] **Step 4: handle inexistente é 404**, e CORRETOR que revela lead que não é dele é 403 — o mesmo recorte de papel da lista, senão a revelação vira a porta dos fundos da autorização que a lista aplica.

---

### Task 7: A permissão deixa de ser "consultada dentro de um handler"

**Files:** `src/mobia/domain/usuarios/permissoes.py`

- [ ] **Step 1: a docstring do módulo e o comentário de `VER_DADOS_COMPLETOS` passam a dizer que ela é exigência de rota** (D4). Hoje os dois afirmam o contrário, nomeando esta card — comentário que descreve o futuro errado é o defeito da TEC-146.
- [ ] **Step 2: `DE_ESCRITA` continua sem ela**, e o comentário que explica isso continua valendo: revelar um telefone não altera o telefone. Conferir, não reescrever.

---

### Task 8: Os cenários do Gherkin

**Files:** `tests/integration/test_mascara_de_lead.py` (novo), `tests/features/test_dado_pessoal_do_lead.py` (novo)

- [ ] **Step 1: CORRETOR sem a permissão vê o telefone mascarado** na lista, e a resposta **não contém** os dígitos em lugar nenhum — asserta sobre o corpo inteiro serializado, não sobre um campo. É a asserta que pega o vazamento pelo cursor.
- [ ] **Step 2: o cursor não carrega o par** — decodifica o base64 e afirma que o telefone não está lá (D3).
- [ ] **Step 3: revelar grava a trilha com autor, lead, campo e horário**, e a linha tem `lead_ref` e não o par.
- [ ] **Step 4: quem não tem a permissão recebe 403 ao revelar**, e **nenhum** evento é gravado — negativa de acesso já é registrada pelo middleware da TEC-206, e um `DADO_PESSOAL_ACESSADO` aqui mentiria.
- [ ] **Step 5: GERENTE também vê mascarado na lista** (D4). É a asserta que impede alguém de "otimizar" devolvendo o valor cheio para quem pode.
- [ ] **Step 6: lead web sem telefone digitado sai `null`**, e não máscara de vazio.
- [ ] **Step 7: a imutabilidade aponta para o teste da TEC-206**, em vez de reescrevê-lo (D9). Uma linha de comentário no arquivo dizendo onde ele está.

---

### Task 9: As três emendas ao SRS

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1:** RN-18.5 → **E-01**; RN-18.1 → **E-01**; RNF-12 → **E-02**. Numeração conferida no arquivo, não presumida.
- [ ] **Step 2:** item aninhado sob a regra, sem tocar no texto de 22/08/2026. As duas lacunas — e-mail sem fonte, exportação inexistente — ditas com todas as letras.
- [ ] **Step 3:** as três linhas na tabela-índice do topo.

---

### Task 10: Os gates e a suíte

- [ ] **Step 1:** `ruff check src tests alembic evals scripts`
- [ ] **Step 2:** `ruff format --check src tests alembic evals scripts` — gate separado do linter.
- [ ] **Step 3:** `mypy`, sem argumento.
- [ ] **Step 4:** `scripts/comentarios_tocados.py` e `--checar`. Esta branch contradiz comentário de três cards anteriores (TEC-192, TEC-202, TEC-206) — o `VIZINHO` aqui é o ponto inteiro.
- [ ] **Step 5:** a suíte inteira, **uma vez**, com `--tb=short`. Conferir de perto os testes da TEC-192: a forma do cursor e o item da lista mudaram, e eles afirmam a forma antiga.

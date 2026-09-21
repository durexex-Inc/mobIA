# TEC-223 — o vocabulário fechado de `messages` passa a ser garantido pelo banco

**Status:** implementado
**Card:** [TEC-223](https://eduardodurieuxlopes.atlassian.net/browse/TEC-223) — épico TEC-123
**Branch:** `feat/tec-223-check-no-vocabulario-de-messages`
**Origem:** review final da branch `feat/tec-126-telemetria`.

## Objetivo

Pôr no banco as quatro constraints `CHECK` que hoje só existem como enums Python, de modo que uma grafia divergente seja recusada na gravação em vez de passar em silêncio e reaparecer como comportamento errado três camadas adiante.

## Por que agora, e por que isto não é cosmético

Duas garantias do sistema comparam **string literal em SQL cru**, não pelo enum:

- `sweep_stalled.py:16` — `WHERE direction = 'INBOUND'`. Uma linha gravada como `'inbound'` seria varrida, e **a fala do próprio agente voltaria para `process_message`**, que emitiria efeito externo por uma mensagem que ninguém enviou.
- `followup/repositorio.py:181` — o mesmo literal, na CTE `falas_do_lead`, que serve a duas consultas.
- `sweep_stalled.py:19` e `:21` — `status = 'RECEIVED'` e `status IN ('QUEUED', 'PROCESSING', 'FAILED')`.
- `0004:190` — `DELETE FROM messages WHERE direction = 'OUTBOUND'` no downgrade. Uma linha com grafia divergente sobreviveria ao delete e derrubaria o downgrade no `provider_message_id NOT NULL` restaurado.

Hoje isso é defesa em profundidade e não defeito ativo: há exatamente dois escritores de linha (`IngestionService._persist` e `MessageRecorder.record_agent_message`) e ambos passam pelos enums. **O risco é o terceiro escritor** — a TEC-124 traz o canal web, e é ele quem vai gravar pela primeira vez sem passar pelo parser da Meta.

E o repo já tem o precedente do que acontece sem a constraint: o comentário de `followup/repositorio.py:79-89` registra que `lead_qualification.temperatura` é uma `String(8)` sem CHECK, que *"um `UPDATE` manual em producao e o bastante para gravar um valor fora do enum"*, e que por isso aquela consulta precisa filtrar defensivamente. É o custo de não ter feito isto lá.

## O que foi medido antes de decidir

### Um `CHECK` com `IN` aceita `NULL` sem cláusula extra

`status` é a única das quatro `nullable`, e o `NULL` ali é **semântico e ativamente gravado** — `recorder.py:128` o escreve, e `models.py:58-59` diz que significa "nao participa do pipeline de ingestao". Medido contra o Postgres desta máquina:

```sql
CREATE TEMP TABLE sonda (s varchar(16) NULL CHECK (s IN ('RECEIVED','QUEUED')));
INSERT INTO sonda VALUES ('RECEIVED');  -- INSERT 0 1
INSERT INTO sonda VALUES (NULL);        -- INSERT 0 1
INSERT INTO sonda VALUES ('received');  -- ERROR: violates check constraint
```

`IN` com `NULL` resulta em `UNKNOWN`, e `UNKNOWN` não viola um `CHECK`. A cláusula `status IS NULL OR …` da D1 é portanto **redundante tecnicamente e deliberada editorialmente**: ela documenta que o `NULL` é permitido de propósito, para ninguém "consertar" a constraint depois achando que faltou cobrir o caso.

### O que uma violação real despejaria, e para onde isso vai

Medido sobre a tabela `messages` de verdade, dentro de uma transação revertida — a linha da `DETAIL` abaixo foi montada à mão para a sonda, e isso importa para o campo `conversation_key`: ela sai aqui como `whatsapp:5511987654321`, mas `_persist` grava `item.sender_external_id` **cru**, sem prefixo de canal (`service.py:72`, cujo comentário diz "Quem fala e o lead, entao a conversa e a dele"). A conclusão abaixo — o telefone aparece dentro do `conversation_key` — continua valendo; a amostra é que engana sobre a forma dele.

```
ERROR:  new row for relation "messages" violates check constraint "ck_sonda_direction"
DETAIL:  Failing row contains (f72e8a54-…, whatsapp, wamid.SONDA, 5511987654321,
  5511000000000, TEXTO, RECEIVED, 0, 2026-09-21…, null, …, LEAD, inbound,
  whatsapp:5511987654321, \x0123456789abcdef, null, null).
```

Duas leituras, e as duas importam:

**O conteúdo da conversa não vaza.** `text_body` sai como `\x0123…` — ciphertext, porque a coluna é `bytea` cifrado desde a TEC-221. A colisão que o desenho da TEC-292 registrou entre esta card e o vetor do `DETAIL` é **menor do que aquele texto supunha**, e esta é a medição que o mostra.

**O telefone vaza duas vezes, não três:** em `sender_external_id` e dentro de `conversation_key`. O terceiro campo do INSERT, `recipient_external_id`, **não** é o telefone do lead numa mensagem de entrada — é o número do negócio, o `phone_number_id` da Meta; quem fala é o lead, então é ele quem ocupa o papel de remetente, e o destinatário é a própria conta do WhatsApp Business. No log isso está fechado — `motivo_do_erro_de_banco` nunca repassa o `detail`, e desde a TEC-293 o traceback não leva a mensagem da exceção. **Mas o INSERT em `messages` acontece em `_persist`, chamado de `whatsapp.py`, que re-levanta** — e aí o uvicorn emite o traceback cru no stdout, fora do mascarador. É o flanco que a TEC-293 deixou declaradamente aberto.

**O inventário acima também omite `last_error`, que é `Text` em claro** (`models.py:96`). Uma violação de `ck_messages_status` só pode vir de um `UPDATE`, e `process_message.py:125-130` grava `last_error` na mesma linha em que grava `status` — a `DETAIL` de um `UPDATE` que viola CHECK imprime a linha nova inteira, `last_error` incluído. Hoje isso é impossível na prática, porque os três `UPDATE` que tocam `status` gravam sempre um membro do enum; mas o inventário se apresenta como completo, e não é enquanto deixar este campo de fora.

**Esta card não abre esse vazamento; ela cria a condição que o dispara.** Dito sem rodeio: se um escritor futuro gravar grafia divergente, o resultado passa a ser um 500 com o telefone do lead no stdout do uvicorn. O balanço, ainda assim, é a favor da constraint — hoje o mesmo erro passa **silencioso** e faz o sweeper devolver a fala do agente ao pipeline, o que é pior e mais difícil de descobrir. Falhar alto é o comportamento certo; o preço fica registrado aqui e **sobe a prioridade da card do uvicorn/arq**.

## As decisões

### D1 — Quatro constraints, não três

A card pede três e deixa `status` como pergunta. Entram as quatro, porque `status` tem exatamente o mesmo problema — o sweeper o compara por literal em duas linhas — e a medição acima removeu o único obstáculo técnico que ele tinha.

| nome | expressão |
| --- | --- |
| `ck_messages_role` | `role IN ('LEAD', 'AGENTE', 'CORRETOR', 'SISTEMA')` |
| `ck_messages_direction` | `direction IN ('INBOUND', 'OUTBOUND')` |
| `ck_messages_content_type` | `content_type IN ('TEXTO', 'AUDIO', 'IMAGEM', 'DOCUMENTO', 'DESCONHECIDO')` |
| `ck_messages_status` | `status IS NULL OR status IN ('RECEIVED', 'QUEUED', 'PROCESSING', 'PROCESSED', 'FAILED')` |

Nome e forma seguem `ck_handoffs_status` (`domain/handoff/models.py:166-168`), que é o precedente exato de "CHECK que fecha vocabulário" no repo. Uma constraint por coluna, e não uma composta, para que o erro diga **qual** coluna recusou — é o que a card pede e é o que `motivo_do_erro_de_banco` transforma em `23514 table_name=messages constraint_name=ck_messages_direction`.

### D2 — O CHECK espelha o enum inteiro, inclusive os valores que ninguém usa

`MessageRole.CORRETOR` e `MessageRole.SISTEMA` não têm **nenhum** uso em `src/` nem em `tests/`. Entram no CHECK assim mesmo.

A razão é a D3: o teste que impede enum e constraint de divergirem compara os dois conjuntos, e uma exceção nessa comparação seria uma exceção que ninguém lembra de manter. Excluir os dois também faria o primeiro código que gravasse `CORRETOR` ser recusado pelo banco sem que nada explicasse por quê.

Remover os dois do enum foi considerado e fica de fora: é mexer no vocabulário do domínio, que não é o que esta card decide.

### D3 — Um teste impede o enum e a constraint de divergirem

Sem ele, esta card tem prazo de validade: alguém acrescenta um valor ao enum, a suíte passa, e o banco recusa em produção.

O precedente é `tests/integration/test_corretores_schema.py:190-203`, que lê `pg_constraint` e afirma que o CHECK cobre o enum inteiro — e cuja docstring registra que o repo não tinha teste desse tipo antes. Esta card escreve o equivalente para as quatro colunas de `messages`: lê a expressão de cada constraint do catálogo e confronta com os membros do enum correspondente, **nos dois sentidos** — valor do enum que falta no CHECK, e valor do CHECK que não existe mais no enum.

### D4 — A migration é a `0037`, com round-trip

Head é a `0036`. Criação por `op.create_check_constraint` sobre tabela existente, seguindo a `0014` (`0014_temperatura_do_lead.py:51-60`), e o `downgrade` com `op.drop_constraint` em ordem inversa, como lá.

O round-trip não é ritual. A docstring de `test_a_0035_desce_e_sobe_de_novo` (`tests/integration/test_migrations.py:296-299`) dá a razão da casa: objeto que nasce fora do autogenerate pode sobreviver órfão ao downgrade e fazer o **upgrade seguinte** reprovar com "already exists" — num banco de desenvolvimento que já subiu e desceu a revisão, e não no CI, que parte do zero. Um `CheckConstraint` criado por `op.create_check_constraint` cai exatamente nessa categoria.

O teste segue o molde de `test_a_0013_desce_e_sobe_de_novo` (`:258-289`): desce para `0036`, afirma pelo catálogo que as quatro constraints sumiram, e depois de voltar ao head afirma que as quatro existem.

### D5 — A constraint também vive no `__table_args__` do modelo

**A prática do repo tem maioria, não unanimidade, e vale dizer qual é.** Dos doze CHECKs que existem hoje, **oito** vivem em dois lugares — no modelo ORM e na migration, mesmo nome e mesmo texto — e **quatro não**: `ck_lead_qualification_forcada_quente`, `ck_lead_qualification_forcada_motivos`, `ck_lead_score_audit_total` e `ck_lead_score_audit_causas` existem só na migration. Conferido por varredura, não por lembrança.

Esta card duplica, com os oito. `CheckConstraint` passou a ser importado em `models.py`, que não o importava, e as quatro entram no `__table_args__` junto do `Index` e do `UniqueConstraint` que já estão lá.

A razão de duplicar aqui, e não seguir os quatro que não duplicaram: `messages` é a tabela mais lida deste repo, e o modelo é onde alguém vai procurar o que a coluna aceita — uma `String(8)` sem constraint visível é exatamente o que fez esta card existir. O custo da duplicação é ela poder divergir de si mesma; a D3 pega a divergência que importa (constraint contra enum) lendo o banco, e a que sobra — modelo contra migration — é responsabilidade de quem escreve, como nos outros oito.

Nada no esquema de teste depende dessa cópia: as fixtures sobem por `alembic upgrade`, não por `create_all`, então quem cria as constraints é a migration.

## O que a ordem do downgrade já protege, e por isso não vira trabalho

A `0004`, no downgrade, converte `content_type` para o vocabulário da Meta — `'text'`, `'audio'`, `'image'`, `'document'`, `'unknown'` (`0004:79-87`), todos **fora** do enum. Isso não colide com a nova constraint: um `alembic downgrade` abaixo da `0004` executa a `0037` primeiro, e quando o `UPDATE` da `0004` roda o CHECK já não existe. O caminho já é exercitado por `test_downgrade_decifra_text_body_e_raw_payload`, que desce abaixo da `0004` e volta.

## Fora de escopo, e por quê

- **O vazamento por uvicorn e arq.** Medido acima e declarado: quando a violação acontece em `_persist`, o 500 sobe e o uvicorn emite a `DETAIL` com o telefone no stdout. É a lacuna que a TEC-293 registrou em "Fora de escopo" e que continua valendo; fechá-la é configurar os loggers `uvicorn.error` e `arq.worker`. **Card nova**, e esta medição é argumento para priorizá-la.
- **Remover `CORRETOR` e `SISTEMA` do enum.** Ver D2.
- **`ADD CONSTRAINT … NOT VALID` seguido de `VALIDATE`.** A forma direta pega `ACCESS EXCLUSIVE` e varre a tabela; a forma em dois passos existe para tabelas grandes em produção sem janela. O risco mais agudo, porém, não é a varredura — é a fila de lock: um `ALTER TABLE` esperando `ACCESS EXCLUSIVE` bloqueia todo `SELECT` que chegar atrás dele na fila, e `NOT VALID` não resolve isso, só encurta a janela em que o `ACCESS EXCLUSIVE` fica preso; quem resolve a fila é `SET lock_timeout` com retentativa. Não há medição de volume que justifique a complexidade hoje, e a primeira aplicação real será num banco pequeno. Anotado para quem for aplicar isto com `messages` já grande.
- **`lead_qualification.temperatura`**, a outra coluna de vocabulário sem CHECK, citada em `followup/repositorio.py:79-89`. Mesma classe de problema, outra tabela, outra card.

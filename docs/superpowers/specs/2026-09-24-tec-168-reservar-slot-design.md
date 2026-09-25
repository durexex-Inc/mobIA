# TEC-168 — Reservar o slot, com a garantia de não sobreposição no banco

**Status:** implementado
**Card:** [TEC-168](https://eduardodurieuxlopes.atlassian.net/browse/TEC-168) — épico TEC-164
**Branch:** `feat/tec-168-reservar-slot`
**Origem:** RF-11, RN-11.4 (SRS v1.0); RT-07.

## Objetivo

Gravar agendamentos de modo que **dois compromissos do mesmo corretor nunca se sobreponham** — garantido por uma constraint de exclusão no Postgres, não por verificação em memória — com uma reserva de 5 minutos durante a confirmação que expira sozinha, e com o lead que perde uma disputa recebendo janelas alternativas em vez de erro.

## O que esta card não entrega, dito antes

**Nada muda na conversa.** Como nas TEC-165 e TEC-167: o turno não reconhece pedido de horário, não oferece janela e não reserva nada. Esta card entrega a gravação e a garantia; ligá-las ao turno é trabalho de conversa que nenhuma das cards do épico assumiu até aqui.

**Fora:** notificar lead e corretor (TEC-170), cancelar e remarcar (TEC-172), lembretes (TEC-171), lista de espera (TEC-169), e os indicadores de agendamento do painel de funil — a Emenda E-01 da RN-17.1 diz que eles voltam com a RF-12, que é a TEC-170.

## D1 — A tabela

Migration `0044_agendamentos.py`, tabela `agendamentos`:

| coluna | tipo | nota |
| --- | --- | --- |
| `id` | `UUID` PK | gerado em Python, como o resto do repo |
| `corretor_id` | `UUID` FK `corretores.id` | não nulo |
| `channel`, `conversation_key` | `String(32)`, `String(64)` | o par que identifica o lead em todo o repo — não existe tabela de lead |
| `imovel_id` | `UUID` FK `imoveis.id`, **nulo** | o contrato do SRS (6.4) tem `imovelId`; reunião remota pode não ter imóvel |
| `tipo` | `String(24)` + `CHECK` | `VISITA_PRESENCIAL`, `REUNIAO_REMOTA` — o `TipoDeCompromisso` da TEC-165 |
| `inicio`, `fim` | `timestamptz` | `CHECK (inicio < fim)` |
| `status` | `String(16)` + `CHECK` | `RESERVADO`, `CONFIRMADO`, `EXPIRADO` |
| `reservado_ate` | `timestamptz` | a reserva mais 5 minutos |
| `criado_em` | `timestamptz` | carimbado pelo repositório |
| `confirmado_em` | `timestamptz`, nulo | preenchido na confirmação |

Status como `String` + `CHECK`, sem enum nativo: é a regra do repo desde a migration 0016.

## D2 — A garantia é do banco

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE agendamentos ADD CONSTRAINT ex_agendamentos_sem_sobreposicao
  EXCLUDE USING gist (corretor_id WITH =, tstzrange(inicio, fim, '[)') WITH &&)
  WHERE (status IN ('RESERVADO', 'CONFIRMADO'));
```

- `btree_gist` é o que permite `corretor_id WITH =` num índice gist. É contrib do Postgres, presente na imagem `pgvector/pgvector:pg16`; o downgrade não a remove, pelo mesmo argumento da 0017 para `vector`.
- `'[)'` — fechado no início, aberto no fim: **encostar não conflita**, a mesma regra do motor da TEC-165 (10h–11h convive com 11h–12h).
- O `WHERE` tira `EXPIRADO` da exclusão. **Ele não pode olhar o relógio**: predicado de constraint tem de ser imutável, e `now()` não é. É por isso que existe a D3.

É a primeira constraint `EXCLUDE` do repo.

## D3 — A expiração é preguiçosa, sem job

Uma reserva vencida (`RESERVADO` com `reservado_ate <= agora`) continua `RESERVADO` na tabela até que alguém precise do lugar:

- **Na leitura** — `AgendaPostgres.ocupados` só conta `CONFIRMADO` e `RESERVADO` com `reservado_ate > agora`. O slot vencido volta às propostas no instante em que vence, sem esperar nada rodar (cenário "reserva expira" da card).
- **Na escrita** — `reservar`, na mesma transação e antes de inserir, marca `EXPIRADO` as reservas vencidas **daquele corretor que sobrepõem o horário pedido**. A constraint nunca barra um lugar por causa de uma reserva morta.

Um job varredor seria redundante: limparia linhas que nenhuma leitura conta e que toda escrita já limpa quando precisa. Se um dia alguém quiser contar reservas expiradas, é outra card — e ela sabe que as linhas estão lá.

**`agora` entra como parâmetro**, não `now()` do banco: é o padrão do domínio, e é o que deixa os cenários "reservado há 5 minutos" e "há 2 minutos" testáveis sem dormir.

## D4 — O repositório

`src/mobia/domain/agendamento/repositorio.py`. Recebe a sessão e **não commita** — a disciplina de `registrar_handoff` e `criar_corretor`.

- `reservar(session, *, corretor_id, channel, conversation_key, janela, tipo, imovel_id, agora) -> Reserva | Conflito`. Expira as vencidas sobrepostas (D3), insere com `reservado_ate = agora + 5 min`, e dá `flush`. Uma violação de `ex_agendamentos_sem_sobreposicao` vira `Conflito`, reconhecida pelo **nome** da constraint (`constraint_name` do asyncpg, com o fallback por substring de `corretores/repositorio.py`); qualquer outro `IntegrityError` sobe. O `flush` que falha deixa a sessão inutilizável até um `rollback`, e quem chama precisa saber disso — a função faz o `rollback` dela antes de devolver `Conflito`, e isso está na docstring.
  - **Emenda E-01 (TEC-168, 24/09/2026):** o conflito é tratado com um SAVEPOINT (`session.begin_nested()`), não com o `rollback` de sessão inteira que o parágrafo acima descreve. Só a tentativa desta chamada volta; escrita pendente anterior de quem chama sobrevive. O motivo: um `rollback` de sessão inteira expira todo objeto já carregado nela — inclusive o que quem chama tinha em mãos —, e o acesso síncrono a um atributo expirado fora de contexto async explode com `MissingGreenlet`.
- `confirmar(session, *, reserva_id, agora) -> Confirmado | Expirado`. `RESERVADO` com `reservado_ate > agora` vira `CONFIRMADO` com `confirmado_em = agora`. Vencida, já expirada ou inexistente → `Expirado`, sem gravar nada: quem chama oferece de novo.
- `AgendaPostgres(session_factory)` — a implementação real da porta `AgendaDoCorretor` da TEC-165. `ocupados(corretor_id, de, ate)` devolve todo intervalo que **sobrepõe** `[de, ate]` (o contrato que a revisão da TEC-165 escreveu na docstring da porta), contando só `CONFIRMADO` e reservas válidas em `de`.

**A constante de 5 minutos** mora no módulo (`DURACAO_DA_RESERVA`), pelo argumento da D4 da TEC-285 e da TEC-165: regra do SRS, não configuração.

## D5 — Quem perde a disputa recebe alternativas

`reservar_ou_alternativas(session, *, corretor, agenda, channel, conversation_key, janela, tipo, imovel_id, agora) -> Reserva | list[Intervalo]`: tenta `reservar`; em `Conflito`, devolve `propor_janelas_do_corretor(...)` com a agenda real — que já enxerga a reserva vencedora, porque o vencedor commitou. É o cenário "dois leads disputam o mesmo horário": um fica com a reserva, o outro com janelas, e nenhum com erro técnico.
  - **Emenda E-02 (TEC-168, 24/09/2026):** a assinatura ganhou o parâmetro `ate` — o horizonte das alternativas, que vem de quem chama, mesma regra da TEC-165. E "o vencedor commitou", acima, vale para o escritor concorrente de **outra** sessão: `AgendaPostgres` lê só o que já foi commitado, então um conflito com uma reserva pendente da própria sessão de quem chama (reservar duas vezes na mesma transação, antes do commit) não tem essa garantia — a agenda ainda não enxerga a tentativa anterior, e as alternativas podem incluir o horário que ela acabou de perder.

## Testes

De integração, contra o Postgres real (`tests/integration/test_agendamento_repositorio.py`). A tabela entra em `TABELAS` de `tests/conftest.py`.

Os quatro cenários da card:

| cenário | como |
| --- | --- |
| dois leads disputam o mesmo horário | duas sessões do `session_factory`, `asyncio.gather` de `reservar_ou_alternativas` no mesmo slot, cada uma commitando: exatamente uma `Reserva`, a outra uma lista não vazia de janelas que não inclui o slot disputado, e `count(*) = 1` |
| reserva expira sem confirmação | reserva em `t`; em `t + 5 min`, `ocupados` não a conta, e `propor_janelas_do_corretor` volta a oferecer o slot |
| confirmação dentro do prazo | reserva em `t`, `confirmar` em `t + 2 min` → `Confirmado`, linha `CONFIRMADO` com `confirmado_em` |
| sobreposição barrada pelo banco | agendamento `CONFIRMADO` quinta 10h–11h; **INSERT cru** (SQL, sem o repositório) de quinta 10h30–11h30 → `IntegrityError` nomeando `ex_agendamentos_sem_sobreposicao` |

Mais: `reservar` sobre uma reserva vencida do mesmo slot sucede e deixa a antiga `EXPIRADO`; slots que encostam convivem; corretores diferentes no mesmo horário convivem; `confirmar` depois do prazo → `Expirado` e a linha continua `RESERVADO`; `confirmar` de id inexistente → `Expirado`; `EXPIRADO` não entra na exclusão (INSERT cru sobre uma linha `EXPIRADO` passa).

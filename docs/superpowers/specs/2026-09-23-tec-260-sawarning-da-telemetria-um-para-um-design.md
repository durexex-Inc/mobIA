# TEC-260 — Calar o SAWarning do teste de telemetria um-para-um

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-260](https://eduardodurieuxlopes.atlassian.net/browse/TEC-260) — épico TEC-123
**Branch:** `feat/tec-260-sawarning-da-telemetria-um-para-um`
**Origem:** revisão final do ramo da TEC-185, que triou o warning como anterior àquele ramo e recomendou card própria.

## Objetivo

Devolver a saída da suíte a zero warnings, sem afrouxar o que `test_telemetria_e_um_para_um_com_a_mensagem` prova — e deixando escrito de onde vem o `IntegrityError`, que é a pergunta que originou a card.

## A medição que a card pede, feita antes de escolher

A card condiciona a correção a uma pergunta: o `IntegrityError` vem do Postgres ou do SQLAlchemy? Sonda rodada em 23/09/2026, containers de pé, contra `message_telemetry`:

```
tipo...........: sqlalchemy.exc.IntegrityError
erro.orig......: sqlalchemy.dialects.postgresql.asyncpg.IntegrityError
orig.__cause__.: asyncpg.exceptions.UniqueViolationError
causa.sqlstate.: 23505
causa.constraint_name: message_telemetry_pkey
causa.table_name: message_telemetry
causa.detail...: Key (message_id)=(2e0e...) already exists.
statement......: INSERT INTO message_telemetry (...) VALUES (...)
```

**Vem do banco.** O `INSERT` chega ao Postgres e é a PK que recusa. O teste prova o que o nome dele diz, e o warning é ruído de forma — o primeiro ramo da card.

## O mecanismo do warning não é o que a card descreve, e isso muda a correção

A card explica o aviso assim: *"A primeira instância continua persistente no identity map da sessão."* Correto, mas incompleto — e a parte que falta é a que decide o conserto.

**O identity map do SQLAlchemy guarda referência fraca** (`WeakInstanceDict`). Medido, com três variantes da mesma sonda:

| variante | primeira instância fica viva? | SAWarning |
| --- | --- | --- |
| `session.add(MessageTelemetry(...))`, sem variável, sem `get` | não — coletada | **não sai** |
| `linha = await session.get(...)` (o teste de hoje) | sim, `linha` a segura | **sai** |
| `primeira = ...; session.add(primeira)`, sem `get` | sim, `primeira` a segura | **sai** |

Ou seja: o gatilho não é o `session.get()` nem a persistência em si — é **haver referência forte viva** no momento em que a segunda instância nasce com a mesma chave. O `session.get()` do teste apenas amarra a primeira a uma variável local.

Isso importa porque reclassifica o warning: ele não é consequência do que o teste prova, é consequência de o teste ter guardado a linha numa variável para conferir o `cost_usd`. É artefato do teste, não do banco.

## D1 — Remover a causa, em vez de silenciar o sintoma

A card prescreve, para o ramo "vem do banco", a correção mínima: `pytest.warns(SAWarning)` ou `filterwarnings` naquele teste. **Divirjo, e a medição acima é a razão.**

`session.expunge(linha)` antes de inserir a colidente tira a primeira instância da sessão. O `INSERT` continua indo ao Postgres exatamente igual — nada do que o teste prova muda —, e o aviso deixa de existir em vez de ser suprimido.

Os dois caminhos que a card sugeria são piores aqui:

- **`pytest.warns(SAWarning)`** afirmaria o aviso como comportamento esperado. Além de fixar detalhe interno do ORM, fixaria um detalhe que **depende de coleta de lixo** — a tabela acima mostra que a mesma operação avisa ou não conforme haja referência viva. Um teste que assere isso é frágil por construção e, pior, documenta o ruído como se fosse carga útil.
- **`filterwarnings`** esconde sem explicar. Some o aviso, fica a colisão, e a próxima pessoa que mexer no teste a reencontra sem o filtro.

`expunge` é a correção que deixa o teste igual ao vizinho limpo: sem colisão de identidade nenhuma.

## D2 — A origem passa a ser afirmada, não suposta

O quarto critério de pronto é *"fica escrito de onde vem o `IntegrityError`"*. Escrever num comentário atenderia à letra; o teste passa a **afirmar**:

```python
causa = capturado.value.orig.__cause__
assert causa.sqlstate == "23505"
assert causa.constraint_name == "message_telemetry_pkey"
```

A diferença é que um comentário envelhece em silêncio e uma asserção reprova. Se um dia a recusa passar a vir do identity map — porque alguém removeu o `expunge`, ou porque o ORM mudou —, o teste cai em vez de continuar verde provando outra coisa. É exatamente a distinção que originou a card, agora defendida por gate.

Isto também reforça o terceiro critério: removida a PK de `message_telemetry`, não há `IntegrityError` nenhum e o `pytest.raises` já reprovaria; com a asserção, reprova dizendo qual constraint sumiu.

## D3 — O segundo warning da suíte é ambiental, e não é desta card

Com o SAWarning resolvido, a execução local ainda imprime:

```
PytestConfigWarning: Unknown config option: timeout
```

**Não é defeito do repositório.** `pytest-timeout>=2.3` está declarado no `pyproject.toml` (extra `dev`, junto do `pytest-xdist`) desde a TEC-291; a venv desta máquina é que estava sem ele. No CI, que instala o extra, o warning não existe — e o CLAUDE.md já registra o sintoma e a cura.

Instalado o plugin, a execução fecha com **zero warnings**, que é o critério da card. Nenhuma mudança de repositório entra por causa disso: seria consertar no `pyproject.toml` algo que o `pyproject.toml` já diz.

## O que este desenho não entrega

**Nenhuma varredura por outros usos do mesmo padrão.** Se há outro teste que insere colidente com referência viva, ele não foi procurado — hoje a suíte tem um warning só, então, se existe, não está disparando.

**Nada sobre o teto de 120s.** Instalar o `pytest-timeout` liga um teto que nesta máquina não estava ligado. Isso é o comportamento que o repositório já pedia; se algum teste passar a estourá-lo, é achado novo e card nova, não regressão desta.

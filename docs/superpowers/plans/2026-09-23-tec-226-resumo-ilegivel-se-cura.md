# TEC-226 — Plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-23-tec-226-resumo-ilegivel-se-cura-design.md`
**Branch:** `feat/tec-226-resumo-ilegivel-se-cura`

## Tarefa 0 — O teste que reproduz, antes da correção (executada)

`test_resumo_ilegivel_com_marca_adiantada_tambem_se_cura`, em `tests/integration/test_montagem.py`, ao lado dos dois que já cobrem o degradado.

Marca da linha corrompida em `criadas[-1]`, a mensagem mais recente — pior caso determinístico, independente de `contexto_literais_minimas`. Confirmado reprovando antes da mudança, com a mensagem nomeando a causa (`a dobra virou no-op na guarda de monotonia`), e os dois vizinhos passando.

Ordem obrigatória: sem ver o teste reprovar, não há como saber que ele testa o que diz.

## Tarefa 1 — `apagar_resumo` (D1)

`src/mobia/domain/context/repositorio.py`: função nova, `DELETE` por `(channel, conversation_key)`, idempotente, **sem commit** — a sessão é emprestada, mesma disciplina de `gravar_resumo` e `ler_resumo`.

`src/mobia/domain/context/montagem.py`, no `except DecryptionError`: chamar e commitar. O `except` passa a capturar `as exc`, que a tarefa 3 usa.

O comentário do bloco degradado é reescrito: ele prometia que "a próxima dobra sobrescreve" e essa promessa era falsa nesta janela. Tem de dizer o que passou a ser verdade **e** por que a versão anterior não bastava, senão a próxima pessoa remove o `apagar_resumo` por achá-lo redundante.

## Tarefa 2 — `gravar_resumo` devolve se gravou (D2)

Mesma função: retorno `bool` a partir do `rowcount`.

**Armadilha de nome, e ela compila:** neste módulo `cast` é o do SQLAlchemy (cast SQL, usado em `_acrescentar_perguntados`). O cast de tipagem tem de ser `typing.cast` qualificado. Trocar pelo `cast` curto não quebra o import — faz coisa completamente diferente. Comentário obrigatório no sítio.

`_dobrar` loga `contexto.resumo_nao_gravado` quando receber `False`. Nível `info`, pela razão da D2.

## Tarefa 3 — O discriminador do log, e o comentário que mentia (D3)

`log.warning("contexto.resumo_ilegivel", ...)` passa a levar `reason` e `marca_do_aad`.

O comentário acima dizia *"só o tipo do erro vai para o log"* enquanto a chamada passava só `channel`. Reescrito para descrever o que o código faz.

Teste: estender `test_resumo_ilegivel_degrada_em_vez_de_travar_a_conversa` para afirmar `DecryptionError` e a marca no `caplog` — **e que o telefone não aparece**, que é o ponto da tarefa 4.

## Tarefa 4 — `marca_do_aad` com HMAC (D4)

`src/mobia/infra/crypto.py`:

- `_chave_da_marca()`, HKDF-SHA256 sobre a `content_encryption_key`, `info=b"mobia/marca-do-aad/v1"`, 32 bytes.
- `_marca_do_aad` → `marca_do_aad` (público, porque `montagem.py` passa a usar), agora `hmac.new(...)`.
- Três chamadas internas em `decrypt` renomeadas.

Dois testes em `tests/unit/test_crypto.py`:

1. a marca **difere** de `sha256(aad)[:12]` — é a força bruta do atacante com um candidato, e falharia se alguém revertesse para hash simples;
2. trocada a chave, a marca muda — fixa a consequência aceita como decisão visível.

## Verificação

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit/test_crypto.py tests/integration/test_montagem.py tests/integration/test_repositorio_contexto.py tests/integration/test_handoff_dossie_do_banco.py
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

A suíte inteira uma vez, com o hash guardado. **Rodar por blocos, ou por fatias:** o Postgres desta máquina caiu duas vezes em 23/09 durante a TEC-260, uma sob `-n 8` e outra serial. Se voltar com dezenas de `CannotConnectNowError`, é a queda documentada, não a branch.

`comentarios_tocados.py` importa mais que o normal aqui: a branch mexe em `montagem.py`, que tem 2706 linhas em `executar_turno` e concentra 75,9% do ruído de `VIZINHO`. Ler a listagem inteira com `--tudo` é caro; o teto padrão é o que se lê, e o que ele omitir fica declarado.

## Risco declarado

**O `apagar_resumo` é a primeira escrita no caminho de leitura de `montar_contexto`.** Até aqui aquela sessão só lia. Duas consequências a vigiar: um `DELETE` por turno degradado, e um commit onde antes não havia nenhum. Ambos só acontecem no caminho de exceção, que por definição é raro — mas se algum dia o `decrypt` começar a falhar em volume, isto vira escrita em volume.

**A D4 muda o valor de uma marca que pode estar em log já coletado.** Nada quebra, mas marcas anteriores ao deploy não correlacionam com as posteriores. É o mesmo efeito da rotação de chave, e está declarado no docstring.

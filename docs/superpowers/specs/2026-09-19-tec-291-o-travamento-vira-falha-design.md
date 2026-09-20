# TEC-291 — O travamento vira falha que se explica

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-291](https://eduardodurieuxlopes.atlassian.net/browse/TEC-291)
**Branch:** `feat/tec-291-o-travamento-vira-falha`
**Origem:** TEC-229 e TEC-230, que esbarraram no travamento ao tentar verificar a própria entrega.

## Objetivo

Fazer com que um travamento da suíte de integração custe **um traceback**, e não dez horas de silêncio.

A card pede três coisas, nesta ordem: reproduzir com instrumentação de lock, instalar `pytest-timeout`, e corrigir a causa conforme o achado. As duas primeiras foram feitas. A terceira mudou de forma depois do que a primeira mediu, e é disso que este desenho trata.

## O que foi medido antes de desenhar

### A suíte de integração fecha nesta máquina, hoje

Sobre `main` em `c9541d8`, 19/09/2026, Python 3.13.15, containers de pé havia sete dias:

```
943 passed, 1 warning in 229.31s (0:03:49)
```

Com `pg_stat_activity` e `pg_blocking_pids` amostrados a cada 10 segundos durante a execução inteira: **nenhum bloqueio em nenhuma das 27 amostras**. Nenhum backend `idle in transaction` com transação mais velha que o teste corrente.

Isso não desmente a card — desmente só a leitura mais forte dela, a de que a instrução "rode a suíte uma vez" seria hoje inexecutável. Ela é executável; o que ela não é é **confiável**, porque o travamento é intermitente e não tem teto.

### Hipótese 2 da card (esgotamento de pool) — descartada por medição

```
pool class: AsyncAdaptedQueuePool
size 5  overflow_max 10  timeout 30.0  recycle -1
```

O `pool_timeout` do SQLAlchemy é 30 segundos e **levanta** `TimeoutError` ao estourar. Um pool esgotado, portanto, não produz espera indefinida: produz falha em 30 segundos, com traceback. Seja qual for a causa do travamento observado, não é esta.

### Hipóteses 1 e 3 (tarefa abandonada segurando transação) — não reproduzidas em quatro formas

A hipótese era boa e o mecanismo, plausível: `dispose_engine()` faz `AsyncEngine.dispose()`, que fecha só as conexões **no** pool — uma conexão ainda tomada por uma tarefa abandonada ficaria de fora, o backend ficaria `idle in transaction` segurando `ACCESS SHARE`, e o `TRUNCATE` do teste seguinte esperaria por ele para sempre.

Quatro experimentos, cada um seguido de um teste cujo `TRUNCATE` de setup denunciaria o lock retido:

| forma exercitada | resultado |
| --- | --- |
| `cancel()` sem `await`, tarefa dormindo dentro da sessão | passa |
| `cancel()` sem `await`, com `SELECT pg_sleep(3600)` em voo | passa |
| tarefa nunca cancelada nem aguardada, consulta em voo | passa |
| cancelamento esperando **lock de linha**, 40 iterações seguidas | 40 passed em 21,5s |

A última é a forma dos dois alvos que a card relata, repetida quarenta vezes: `FOR UPDATE` segurando a linha numa sessão e `asyncio.wait_for` cancelando a outra em cima do cadeado, exatamente como em `test_o_cadeado_serializa_dois_turnos_da_mesma_conversa`.

O motivo de não vazar apareceu no traceback do segundo experimento: no fim de cada teste o `pytest-asyncio` cancela as tarefas pendentes e o SQLAlchemy cai em `do_terminate` → `asyncpg.terminate()`, que **fecha o socket**. O backend morre e o Postgres solta os locks dele. A conexão tomada não sobrevive ao fim do teste como a hipótese supunha.

**O comentário de `presenca.py` que diz "não awaitar não custa nada" continua, portanto, verdadeiro** — medido, e não só argumentado. Não é preciso mexer nele.

### O que não é hipótese: não existe teto em lugar nenhum

| camada | teto | efeito de uma espera |
| --- | --- | --- |
| Postgres (`lock_timeout`, `statement_timeout`, `idle_in_transaction_session_timeout`) | **nenhum** — `docker-compose.yml` não sobrescreve nada, e o padrão é `0` | infinita |
| pool do SQLAlchemy (`pool_timeout`) | 30s | falha com traceback |
| pytest | **nenhum** — `pytest-timeout` não está instalado | infinita |

Duas das três camadas esperam para sempre. É isso, e não o gatilho, que transforma qualquer contenção momentânea em dez horas paradas.

E há um lugar onde essa ausência dói mais que nos outros: `banco_limpo` faz um `TRUNCATE` de 19 tabelas **antes de cada teste que toca banco**, e `TRUNCATE` exige `ACCESS EXCLUSIVE` em todas elas. É o lock mais largo que a suíte toma, tomado com a frequência mais alta, sem teto nenhum. Qualquer backend que segure qualquer lock em qualquer uma das 19 o bloqueia — e basta um `ACCESS SHARE`, que um `SELECT` já toma.

## A decisão

**O gatilho não reproduz; o que o torna ilimitado e mudo reproduz sempre.** Este desenho ataca o segundo, em três camadas, da mais específica e mais informativa para a mais geral. A ordem importa: quem dispara primeiro é quem dá o melhor diagnóstico.

Isto é o que a card chama de "converte travamento em falha com traceback — troca 10 horas de silêncio por um diagnóstico", levado a sério: um teto que só diz "estourou" troca dez horas por uma pergunta. Os dois primeiros itens abaixo existem para que a troca seja por uma **resposta**.

### D1 — `lock_timeout` na sessão que trunca

A sessão de `banco_limpo` passa a rodar `SET lock_timeout` antes do `TRUNCATE`. Uma espera que hoje é infinita vira `LockNotAvailable` em segundos.

O teto é por **sessão do Postgres**, aplicado só na conexão que a fixture abre, e não em `infra/db.py`: pôr `lock_timeout` no engine de produção é decisão de produto sobre comportamento em produção, não tem nada a ver com esta card, e o `FOR UPDATE` do turno **quer** esperar — é assim que ele serializa dois turnos da mesma conversa.

### D2 — Quando estourar, dizer quem segura

`LockNotAvailable` sozinho diz que alguém bloqueou; não diz quem. A informação que resolve o caso vive em `pg_stat_activity`, e ela só existe **enquanto** o bloqueio existe — depois do fim do processo não há mais o que consultar. É por isso que a consulta tem de estar dentro do `except`, e não numa instrução que alguém rode depois.

Ao estourar, a fixture consulta `pg_blocking_pids()` e levanta um erro que nomeia, para cada backend bloqueador: o pid, o estado (`idle in transaction` ou `active`), há quanto tempo a transação está aberta e os primeiros caracteres da consulta.

É a diferença entre "o setup do teste X falhou" e "o setup do teste X foi bloqueado pelo backend 1669128, `idle in transaction` há 4 minutos, última consulta `SELECT ... FROM imoveis`". A segunda frase nomeia o teste culpado sem nenhuma execução adicional.

### D3 — `pytest-timeout` como rede de fora

D1 e D2 cobrem o `TRUNCATE`, que é o suspeito mais provável e o mais frequente. Não cobrem um travamento no **corpo** do teste — um `FOR UPDATE` do código de produção esperando um cadeado, um `await` que nunca volta, um impasse de `asyncio` sem banco nenhum envolvido. Para esses, o teto do `pytest-timeout`.

**O comportamento dele difere entre esta máquina e o CI, e a diferença precisa estar escrita** — quem só leu a documentação vai esperar a de POSIX:

| | método | ao estourar |
| --- | --- | --- |
| Linux (o CI é `ubuntu-latest`) | `signal` | o teste falha, **a execução continua** |
| Windows (esta máquina) | `thread` | despeja a pilha de todas as threads em stderr e **mata o processo** com `os._exit()` — sem teardown |

Nesta máquina, portanto, o teto não devolve uma execução completa com uma falha dentro: devolve a pilha de onde o processo estava parado e encerra. É pior que o do CI e é muito melhor que hoje — dez horas de silêncio contra um despejo de pilha imediato, que é precisamente o diagnóstico que faltou nas duas ocorrências.

O teto vale para **setup, teste e teardown** juntos (é o padrão do plugin; `timeout_func_only` o restringiria ao corpo). Fica assim de propósito: o travamento mais provável está no setup.

### D4 — O que o `CLAUDE.md` passa a dizer

A seção "Quando o `-n 8` derruba o Postgres" hoje documenta sintoma e método de diagnóstico. Ela passa a registrar o que foi medido: que a suíte de integração fechou em 229s sobre `c9541d8`, que pool está descartado, que tarefa abandonada não vaza conexão, que não há teto em duas das três camadas — e que, a partir desta card, um travamento se apresenta como falha nomeando quem bloqueia.

O par de comandos `stat`/`Get-Process` que ela ensina continua valendo para o caso que nenhum teto cobre: o processo parado **sem** estar esperando lock nem estourar o teto do teste.

## O que este desenho não entrega

**A causa do travamento observado em 17 e 18/09 continua desconhecida.** Ele não reproduziu em nenhuma das formas exercitadas nem na execução completa. O que esta card entrega é que a **próxima** ocorrência se explique sozinha, em segundos, nomeando o bloqueador — em vez de custar mais uma sessão inteira.

Isso é uma escolha declarada, não um atalho: sem reprodução não há como escrever "a causa está onde ela vive", que é o segundo critério de pronto da card. Com D1 e D2 de pé, a ocorrência seguinte produz o dado que falta.

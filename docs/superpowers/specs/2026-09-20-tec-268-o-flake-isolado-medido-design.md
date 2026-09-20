# TEC-268 — O flake isolado, medido

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-268](https://eduardodurieuxlopes.atlassian.net/browse/TEC-268) — bug, sem épico
**Branch:** `feat/tec-268-o-flake-isolado-medido`
**Origem:** achado ao levantar o baseline da TEC-162, 09/09/2026.

## Objetivo

Fazer a instrução de diagnóstico do CLAUDE.md — *"rode o arquivo sozinho antes de culpar sua mudança"* — voltar a ser verdadeira, e ficar verificável.

## A medição, e ela desmente a card tanto quanto o CLAUDE.md

A card afirma que a instrução "passou a produzir diagnóstico errado", com base numa execução de 09/09/2026 em que `test_dedup_por_message_id.py` reprovou 3 de 5 sozinho.

Refiz a medição em 20/09/2026, em **outra máquina** (o Eduardo trocou):

| arquivo | execuções isoladas | com falha |
| --- | --- | --- |
| `tests/features/test_dedup_por_message_id.py` | 30 | **0** |
| `tests/integration/test_montagem.py` | 15 | **0** |
| `tests/integration/test_sweep_stalled.py` | 15 | **0** |
| `tests/integration/test_optout_repositorio.py` | 15 | **0** |
| **total** | **75** | **0** |

Treze minutos de relógio, containers de pé, máquina ociosa.

**As duas medições estão certas.** A de setembro reprovou de verdade, com `redis.exceptions.ConnectionError` em `localhost:6380`; esta passou de verdade, 75 vezes. O defeito não é a afirmação estar desatualizada — é ela ser **incondicional**: o CLAUDE.md escreve "passam 100% em isolamento" como propriedade do repositório, quando é propriedade da máquina.

E o próprio arquivo já sabe disso em outro parágrafo: *"desconfie de qualquer número aqui que não diga em que máquina e em que Python foi medido"*. A regra existia; esta linha é que não a seguia.

## D1 — A afirmação passa a ser uma tabela datada, e não uma propriedade

O parágrafo vira: as duas medições, com data e máquina, lado a lado. Nenhuma apaga a outra — apagar a de setembro faria a próxima pessoa que vir o flake achar que é a primeira.

A instrução prática sobrevive, com a força certa: **"passa isolado" é evidência forte, não prova; "reprova isolado" não é prova de regressão sua.** E o que fazer quando reprovar já está escrito no repo, em outra seção: rodar a versão ANTIGA o mesmo número de vezes.

## D2 — `scripts/taxa_de_flake.py`, para a próxima máquina não precisar de uma sessão

A conta que fiz à mão vira script. Sem ele, esta card terá produzido exatamente o que a TEC-276 acabou de condenar no mesmo dia: um número medido que vive só em prosa, que ninguém consegue re-derivar, e que três pessoas derivam de três jeitos.

Com ele, a pergunta *"isso ainda vale nesta máquina?"* custa um comando e treze minutos.

**Não é gate e não reprova nada** — imprime a contagem e, quando acha falha, diz o que fazer com ela (acrescentar a medição ao CLAUDE.md, sem apagar as anteriores). A lista de arquivos é a mesma que o CLAUDE.md nomeia, e o comentário registra por que ela não deve crescer sozinha: o script mede a afirmação que está escrita lá, não procura flake novo.

## D3 — Nada de mexer no Redis às cegas

A card sugere investigar o caminho do Redis (`localhost:6380`), já que o CLAUDE.md descreve o WinError 64 sobretudo na negociação SSL do `asyncpg`. É uma pista boa, e fica **fora**: o sintoma não reproduz nesta máquina, então qualquer `retry` ou `health_check_interval` acrescentado agora seria mudança de produção contra um defeito que não consigo provocar — e, portanto, sem como saber se ajudou.

Quando reaparecer, o script desta card dá a taxa antes e depois, que é o que falta hoje para decidir isso com número.

## O que este desenho não entrega

O flake em si. Ele continua possível em máquina que o produza, e nada nesta card o torna menos provável — o que muda é que a instrução de diagnóstico parou de afirmar mais do que sabe, e ficou re-verificável.

# TEC-261 — Varrer importações de catálogo travadas em PROCESSANDO

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-261](https://eduardodurieuxlopes.atlassian.net/browse/TEC-261) — História, prioridade Medium, épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155). Origem: lacuna declarada no desenho da TEC-156; RF-08, RN-08.5.

**A história:** *"Como administrador da imobiliária, quero saber quando uma importação parou de andar, para não ficar esperando por um relatório que nunca vai chegar."*

## Objetivo

`PROCESSANDO` tem dois significados e nada os distingue: *"o worker está trabalhando nisso"* e *"o worker morreu e ninguém vai voltar"*. O `GET /api/v1/imoveis/importacoes/{id}` responde igual nos dois casos, então quem consulta não sabe se espera mais trinta segundos ou reimporta — e a linha retém até 10 MB em `importacoes.arquivo` sem servir a nada.

A TEC-156 fechou o caso do **enqueue que falha**. Fica o do **enqueue que deu certo e do processamento que não terminou**: o worker cai entre pegar o job e gravar o relatório, o Redis perde a fila, ou o job estoura o tempo sem retry.

## O que a exploração descobriu

### A card está desatualizada num ponto, e a favor

Ela pede, como se fosse novidade: *"Ao encerrar a linha, preencher `concluida_em` — hoje só o caminho de sucesso o preenche."*

**Isso deixou de ser verdade no mesmo dia em que a card foi escrita.** O commit `35ec649` (07/09/2026, `fix(TEC-156): o endpoint para de prometer 202 sobre job que nao foi enfileirado`) criou `_marcar_falha` em `api/routes/imoveis.py`, que já grava as três coisas:

```python
importacao.status = str(StatusImportacao.FALHOU)
importacao.erros = [{"linha": 0, "motivo": motivo}]
importacao.concluida_em = datetime.now(UTC)
```

A consequência é boa: **a convenção inteira já existe e tem um precedente para seguir**, em vez de um padrão a inventar. A varredura grava exatamente o mesmo formato, e a card sai de "decida como encerrar" para "encerre como já se encerra".

### O limite tem um piso derivável, e a card não o dá

A card pede *"um limite vindo de `Settings`"* sem valor nem piso. O piso existe e sai do worker (`workers/main.py`):

```python
max_tries = 5
job_timeout = 240
```

Um `job_timeout` do ARQ vira `CancelledError`, e `CancelledError` é uma das três exceções que o ARQ **reagenda** — então uma importação que estoura o tempo pode ser legitimamente retentada até cinco vezes. São **20 minutos de processamento no pior caso**, mais a espera na fila e o backoff entre tentativas.

Um limite abaixo disso faz a varredura fechar em `FALHOU` uma linha cujo job ainda está vivo — e o relatório passa a mentir no meio do caminho, que é exatamente o que esta card existe para acabar.

## Decisões

### D1 — O limite é de 30 minutos, e a derivação fica escrita

`sweep_importacao_travada_after_seconds: int = 1800`, em `app/config.py`, ao lado dos três `sweep_*` existentes.

Trinta minutos ficam ~50% acima dos 20 do pior caso, cobrindo também a fila e o backoff sem precisar calculá-los com precisão. Importação é rara: uma linha travada esperar meia hora antes de ser fechada não custa nada, e o custo do outro lado — fechar uma que ainda está viva — é a mentira que a card quer eliminar.

**O comentário do campo registra a derivação** (`job_timeout` × `max_tries`), para o número não virar mágico. Este repo já tem precedente do contrário: um teto transcrito em prosa que envelheceu sozinho e mandou gente procurar problema inexistente.

### D2 — Um statement só, e não as duas fases da `sweep_stalled`

A card manda seguir o molde da `sweep_stalled`: SQL cru, `FOR UPDATE SKIP LOCKED`. O SQL cru e o `SKIP LOCKED` ficam. **As duas fases, não.**

`sweep_stalled` faz SELECT, commita, e só então enfileira, e o docstring dela explica por quê: há I/O de rede no meio, e segurar lock de linha no Postgres enquanto se fala com o Redis teria efeito concreto — o `claim_message` do worker usa `SKIP LOCKED`, então um job que chegasse durante a janela sairia como no-op.

**Esta varredura não tem I/O nenhum.** Ela lê e escreve a mesma tabela. Um statement resolve:

```sql
UPDATE importacoes
   SET status = 'FALHOU',
       concluida_em = now(),
       erros = CAST(:erro AS jsonb)
 WHERE id IN (
         SELECT id
           FROM importacoes
          WHERE status = 'PROCESSANDO'
            AND criada_em < now() - make_interval(secs => :travada_after)
          ORDER BY criada_em
          LIMIT :limite
            FOR UPDATE SKIP LOCKED
       )
RETURNING id
```

Isso resolve o quarto cenário Gherkin — duas varreduras concorrentes não encerram a mesma linha duas vezes — **por construção**. Copiar as duas fases faria o oposto: abriria uma janela entre o commit do SELECT e o UPDATE em que a segunda varredura ainda leria `PROCESSANDO` e fecharia a mesma linha.

### D3 — Grava o que `_marcar_falha` grava, e substitui `erros` em vez de anexar

`status = 'FALHOU'`, `concluida_em = now()`, `erros = [{"linha": 0, "motivo": ...}]` — a convenção da linha 0 que a TEC-156 usa para falha de arquivo inteiro.

**Substituir e não anexar é seguro, e a razão é verificável:** `catalogo/importacao.py` grava o relatório **de uma vez só, no fim** (`importacao.erros = [...]` junto com `status` e `concluida_em`). Uma linha travada nunca chegou lá, então `erros` está vazio. Anexar a uma lista vazia e substituí-la dão o mesmo resultado, e substituir é o que o precedente faz.

O motivo é uma frase legível dizendo que o processamento não terminou — o relatório passa a dizer "não terminou" em vez de mentir "processando". O texto fica fixo, numa constante do módulo, e diz o que aconteceu sem prometer o que não se sabe:

> `"O processamento nao terminou e a importacao foi encerrada pela varredura. Reimporte o arquivo."`

Não nomeia a causa (worker caído, fila perdida, tempo estourado) porque a varredura não tem como distingui-las — afirmar uma seria inventar. E diz o que fazer, porque quem lê o relatório é o administrador, não quem opera.

**Detalhe de implementação que o SQL cru impõe:** `erros` é `JSONB`, e um `text()` com parâmetro precisa do cast explícito — `CAST(:erro AS jsonb)`, com o valor ligado como string JSON. Passar uma lista Python direto não funciona por este caminho.

### D4 — Cadência de 5 minutos, no molde da `sweep_followups`

`cron(sweep_importacoes_travadas, minute={0, 5, ..., 55}, run_at_startup=False)`.

O argumento é o mesmo que `sweep_followups` e `sweep_sla` já escrevem: precisão de segundos não compra nada quando a janela é de dezenas de minutos, e custaria uma varredura por passagem. O erro máximo de disparo fica em cinco minutos sobre uma janela de trinta.

`sweep_stalled` roda de 30 em 30 segundos porque a janela dela é de 300s — é o contraste, não o molde.

### D5 — Marcar FALHOU, não reenfileirar

Decisão da card, mantida, com a razão que ela dá: reenfileirar exigiria uma coluna de tentativas que `importacoes` não tem. A `sweep_stalled` depende de `messages.attempts` para não entrar em laço; aqui não há equivalente, e inventá-lo está fora do escopo.

## A corrida que fica, e é aceitável

Se algo exceder os 30 minutos e o job ainda estiver vivo quando a varredura fechar a linha, **o job sobrescreve com o resultado verdadeiro no fim** — `catalogo/importacao.py` grava `status`, `erros` e `concluida_em` sem olhar o estado atual da linha.

O sistema se cura, e o resultado final é o certo. Vai declarado aqui porque a alternativa é alguém descobrir isso num incidente e achar que é defeito.

## Arquivos

| Arquivo | O quê |
|---|---|
| `src/mobia/workers/jobs/sweep_importacoes_travadas.py` | **Criar.** O job e o SQL. |
| `src/mobia/app/config.py` | `sweep_importacao_travada_after_seconds`, com a derivação no comentário |
| `src/mobia/workers/main.py` | registro em `functions` e em `cron_jobs` |
| `tests/integration/` | os quatro cenários Gherkin |

## Testes

Os quatro cenários da card são o critério de aceite:

1. **Importação parada além do limite é encerrada** — vira `FALHOU`, com motivo legível e `concluida_em` preenchido.
2. **Importação recente não é tocada** — continua `PROCESSANDO`.
3. **Importação concluída não é tocada** — nem status nem totais mudam.
4. **Duas varreduras concorrentes não encerram a mesma linha duas vezes.** Este precisa de **duas sessões de verdade**, em paralelo, com a primeira segurando o lock — senão não exercita o `SKIP LOCKED` e passa por acidente.

## Lacunas conhecidas

**L1 — A retenção dos bytes continua.** A varredura fecha a linha mas não limpa `importacoes.arquivo`. A card põe isso fora do escopo, e o problema que ela descreve ("retém até 10 MB sem servir a nada") continua de pé para a linha encerrada. Fica para quem decidir a política de retenção.

**L2 — Nada avisa o administrador.** A linha passa a dizer a verdade quando ele consultar, mas ninguém o procura. Notificação de importação é outra card; a consequência prática é que ele só descobre se voltar a olhar.

**L3 — O limite não se move sozinho.** Se alguém subir `job_timeout` ou `max_tries` em `workers/main.py`, o piso de 20 minutos cresce e o limite de 30 pode ficar apertado — sem nada acusar. Derivá-lo em runtime foi descartado porque os dois são atributos da classe do worker, não campos de `Settings`, e puxá-los para o config é mudança maior que esta card. O comentário do campo nomeia a dependência para quem mexer nos dois ter chance de lembrar.

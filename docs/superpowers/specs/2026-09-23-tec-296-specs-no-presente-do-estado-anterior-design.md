# TEC-296 — Os desenhos da TEC-292 e da TEC-293 descrevem o estado anterior no presente

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-296](https://eduardodurieuxlopes.atlassian.net/browse/TEC-296) — épico TEC-123
**Branch:** `feat/tec-296-specs-no-presente-do-estado-anterior`
**Origem:** revisão final da branch `feat/tec-128-debounce-de-rajada` (PR #142).

## Objetivo

Fazer as specs da TEC-292 e da TEC-293 pararem de afirmar, no presente, um estado do log que a implementação da própria TEC-293 desfez — sem apagar o levantamento histórico, que é o que explica a decisão.

## A conferência dos quatro pontos, um a um contra o arquivo

A card manda conferir os quatro sítios do inventário "não por diferença de linha". Feito, ancorando no nome do evento de log em vez do número:

| sítio, como a spec cita | evento de log | onde está hoje | kwarg de texto? |
| --- | --- | --- | --- |
| `turno.py:566` | `resumo_handoff.nao_agendado` | `turno.py:583` | **sim**, `motivo=str(falha)` |
| `process_message.py:214` | `resumo_handoff.nao_agendado` | `process_message.py:220` | **sim**, `motivo=str(falha)` |
| `gerar_resumo.py:48` | `notificacao.nao_agendada` | `gerar_resumo.py:57` | **sim**, `motivo=str(falha)` |
| `importacao.py:111` | `catalogo.importacao_interrompida` | `importacao.py:137` | **não**, só `importacao_id` |

**Três dos quatro mudaram; o quarto não.** Isto não estava no enunciado da card, que trata os quatro como um bloco. A frase da TEC-292 lista os 4 juntos porque em 20/09 os 4 eram iguais; hoje `importacao.py` é o único que ainda se encaixa na descrição, e a D4 da TEC-293 explica por quê — ela decidiu mexer só nos três de Redis, e `importacao.py` não é um deles.

Um pretérito em bloco, portanto, é a correção certa para a frase da TEC-292 — ela descreve um levantamento datado, e naquela data estava correta. O que não pode sobreviver é o presente.

## D1 — A D4 da TEC-293 vira pretérito e ganha âncora estável

A frase é:

> `turno.py:566`, `process_message.py:214` e `gerar_resumo.py:48` **hoje têm só** `exc_info=True`, sem nenhum kwarg de texto.

O parágrafo se contradiz três linhas abaixo, onde o mesmo texto diz *"Os três passam a levar `motivo=str(falha)`"*. O "hoje" era o estado **antes** da implementação desta mesma card, e ficou falso no merge dela.

Vira pretérito explícito — *"tinham, antes desta card, só `exc_info=True`"* — e cada sítio passa a ser citado também pelo nome do evento, que é o que a conferência acima usou e o que não deriva. A spec já declara esse princípio no cabeçalho (*"Onde o alvo tem nome estável, ele é citado pelo nome"*); aqui ele simplesmente não foi aplicado.

## D2 — A frase de inventário da TEC-292 recebe o mesmo tratamento

> Faltavam os **4 que só têm** `exc_info=True`/`log.exception` e nenhum kwarg de texto

`Faltavam` já é pretérito; `que só têm` não é, e é essa metade que mente. Vira `que então só tinham`, com os quatro eventos nomeados.

O padrão é o que a TEC-128 aplicou ao próprio desenho: **renomear ou datar não basta se os verbos continuarem no presente**, porque quem lê só o parágrafo lê o presente.

## D3 — O cabeçalho da TEC-292 ficou falso, e é a mesma classe de defeito

Achado ao fazer a conferência da D1, não previsto pela card. O cabeçalho daquela spec afirma:

> **Sobre os números de linha deste documento.** Eles descrevem a árvore **antes** da branch (...) A `comentarios_tocados.py` marca 20 dessas citações como `PROSA` e **nenhuma** como `FALSO`; a conferência foi feita.

Só que o commit `fba9f37` (TEC-128, 21/09) **atualizou quatro desses números para a árvore daquele dia** — `process_message.py:198`→`:214`, `service.py:164`→`:206`, `service.py:128`→`:170`, `process_message.py:333`→`:443`. Depois disso o documento passou a misturar duas épocas, e o cabeçalho, que promete uma só, ficou falso.

É exatamente o defeito que esta card existe para corrigir, uma camada acima: uma afirmação sobre o documento, em vez de sobre o código. O cabeçalho passa a dizer o que é verdade — que os números são de épocas diferentes, que derivam, e que a âncora confiável é o nome.

## D4 — Os números não são atualizados para a árvore de hoje

A tentação é reconferir os 20 e mais alguns números das duas specs contra a `main` de hoje. Fica **fora**, por medição: os quatro números que a TEC-128 atualizou em 21/09 já estão errados de novo em 23/09 — `214`→`220`, e os outros três do inventário igualmente (`566`→`583`, `48`→`57`, `111`→`137`). Dois dias, seis merges, e a conferência caducou.

Perseguir o número é esteira. O que esta card entrega é o que não caduca: o tempo verbal certo e o nome do evento ao lado do número. O número fica onde está, descrito pelo que é — uma referência à árvore de quando aquele parágrafo foi escrito.

Isso também é o que a `comentarios_tocados.py` já pressupõe: a marca `PROSA` é *suspeita*, não veredito, justamente porque citação em spec histórica pode estar certa sobre o passado.

## O que este desenho não entrega

**As outras specs.** O `fba9f37` tocou quatro documentos (TEC-187, TEC-223, TEC-292, TEC-293); esta card cobre os dois que a TEC-296 nomeia. Se a TEC-187 e a TEC-223 têm o mesmo cabeçalho contraditório, isso não foi conferido aqui e não está afirmado nem negado.

**A regra automatizada.** Nenhum gate passa a pegar presente-falso em prosa. A `comentarios_tocados.py` continua sem opinar sobre tempo verbal, e não há como ela opinar — distinguir "hoje o código faz X" de "o código fazia X" é leitura, não regex. Continua sendo trabalho de quem revisa.

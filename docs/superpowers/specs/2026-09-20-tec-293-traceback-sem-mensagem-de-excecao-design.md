# TEC-293 — o traceback vai para o log sem a mensagem da exceção

**Status:** aprovado, não implementado
**Card:** [TEC-293](https://eduardodurieuxlopes.atlassian.net/browse/TEC-293) — épico TEC-123
**Branch:** `feat/tec-293-traceback-sem-mensagem-de-excecao`
**Origem:** a classe D da TEC-292, que fechou os kwargs de texto e deixou o traceback de fora de propósito. O Step 6 daquele plano mandou abrir esta card.

## Objetivo

Fechar o último caminho pelo qual o texto de uma exceção de terceiro chega ao log — o traceback de `exc_info`/`log.exception` — **sem perder a pilha, a cadeia de causas e o tipo**, que é o que torna erro diagnosticável e o que a TEC-237 comprou com um dia de investigação cega.

> **Sobre os números de linha deste documento.** Eles descrevem a árvore **de hoje** (`e43ea5e`, já com a TEC-292 mergeada) — não os da card, que foi escrita contra a árvore anterior e por isso cita `importacao.py:111` onde hoje é `:133`. Onde o alvo tem nome estável, ele é citado pelo nome.

## O que a medição corrigiu no enunciado da card

A card descreve o vazamento como "o traceback chega ao log inteiro, incluindo a linha final `TipoDoErro: <mensagem>` e os trechos de código-fonte dos frames". Medido contra um erro de banco encadeado — violação de CHECK gravando mensagem, o pior caso que a TEC-292 identificou —, a descrição está certa no essencial e **errada em dois pontos que mudam a solução**.

### A mensagem vaza duas vezes, não uma

O SQLAlchemy reembala a exceção do asyncpg, então a linha `DETAIL` do servidor aparece na seção da **causa** e de novo na seção da **wrapper**. Medido, 1628 caracteres em 24 linhas, com a frase do lead íntegra nas duas:

```
CheckViolationError: new row for relation "messages" violates check constraint "ck_messages_role"
DETAIL:  Failing row contains (a1b2, 5511987654321, Oi, quero um apto de 3 quartos ate 800 mil, inbound, 2026-09-20).

The above exception was the direct cause of the following exception:
...
IntegrityError: (asyncpg.exceptions.CheckViolationError) new row for relation "messages" violates ...
DETAIL:  Failing row contains (a1b2, 5511987654321, Oi, quero um apto de 3 quartos ate 800 mil, inbound, 2026-09-20).
```

**Consequência direta: "cortar a linha final" não é uma solução.** A mensagem da wrapper ocupa quatro linhas (`IntegrityError:`, `DETAIL:`, `[SQL: ...]`, `(Background on this error at: ...)`), e a mensagem da causa não é linha final de nada — está no meio do texto. Qualquer saneador textual erra. Tem de ser estrutural, percorrendo a cadeia.

Confirma-se também o que a TEC-292 já havia escrito: **o telefone sobrevive por acidente**. `5511987654321` tem 13 dígitos e o `_CORRIDA_DE_DIGITOS` de `app/logging.py:23` o mascara. A frase em português não tem nada que a pegue.

### As linhas de código-fonte não carregam valor de runtime

A card supõe que os trechos de fonte dos frames são parte do vazamento. **Não são.** A linha exibida é o texto do `.py` versionado; quando o argumento vem de uma variável — o caso de todos os seis sítios do repo — ela mostra `await service.ingest(parsed)`, não o valor de `parsed`. Medido e verificado.

Isso não muda a decisão de omiti-las (ver D2), mas muda o **motivo**: omitir fonte é escolha de volume, não de proteção. O que fecha o vazamento é tirar a mensagem de cada seção da cadeia.

### A peça pronta do structlog piora o problema

Antes de escrever processador próprio, foi medido o `ExceptionDictTransformer` (structlog 26.1.0), o caminho que um leitor futuro vai propor como simplificação:

| configuração | tamanho | fala do lead | telefone | mensagem da exceção |
| --- | --- | --- | --- | --- |
| default (`show_locals=True`) | 2067 car. | vaza | vaza | vaza |
| `show_locals=False` | 1643 car. | vaza | vaza | vaza |

No default ele despeja as **variáveis locais de cada frame** — inclusive o objeto que estava sendo persistido. E mesmo desligando isso, ele mantém `exc_value`, que é a `DETAIL` inteira. **Adotá-lo como está seria uma regressão**, e é por isso que a D1 escreve a razão no código em vez de deixá-la só aqui.

## As decisões

### D1 — Um processador próprio substitui `format_exc_info`

Em `app/logging.py`, `structlog.processors.format_exc_info` sai da lista de processadores e entra `_sanear_traceback`, na mesma posição — antes de `_mascarar_pii`, pela mesma razão que o comentário de hoje já registra: o traceback tem de virar chave do dict antes do renderer, senão nasce fora do alcance do mascaramento.

Ele monta a chave `exception` a partir de `traceback.TracebackException` e emite, por seção da cadeia:

- uma linha `File "<arquivo>", line <n>, in <função>` por frame;
- no lugar da linha final, **só `exc_type_str`** — o tipo qualificado (`sqlalchemy.exc.IntegrityError`), sem a mensagem.

`_mascarar_pii` e `_finalizar` não mudam. A corrida de dígitos continua passando por cima da chave `exception`, agora como redundância e não como única defesa; e `_finalizar` continua devolvendo `{"exc_info": False}`, porque `logging.Logger.exception` religa o `exc_info` por conta própria e sem isso o `Formatter` do stdlib reemite o traceback **cru** depois do JSON — o que anularia esta card inteira.

**As três alternativas foram consideradas e descartadas:**

- *Saneador textual sobre a string pronta* — erra, pela medição acima: a mensagem não está só na última linha.
- *`ExceptionDictTransformer`* — vaza nos dois modos, e no default vaza mais que hoje.
- *Regra de conteúdo no mascarador* — a `DETAIL` tem padrão reconhecível, mas o texto livre que ela carrega não tem nenhum. É a heurística com falso negativo garantido que a TEC-292 já havia recusado, e remedi-la não mudou a conclusão.

### D2 — Sem as linhas de código-fonte

Arquivo, linha e função já localizam o frame exatamente, e o fonte está versionado: quem depura tem o commit. Omiti-las leva o caso medido de 1628 para **738 caracteres**, de 24 para 9 linhas — o tamanho em caracteres depende do comprimento dos caminhos de arquivo desta máquina, a contagem de linhas não.

Como a subseção acima registra, isso **não** é proteção contra PII — é volume. O resíduo que elas teriam é outro: um literal escrito no próprio fonte, que no repo significaria segredo hardcoded, problema de outra natureza.

### D3 — A cadeia de causas é preservada, com a distinção do Python

Percorrer só `__cause__` perderia o encadeamento implícito, que é metade dos casos reais. O processador percorre `__cause__` e, na falta dele, `__context__`, e emite o elo com a frase que o próprio Python usa:

- `__cause__` → `The above exception was the direct cause of the following exception:`
- `__context__` → `During handling of the above exception, another exception occurred:`

`__suppress_context__` é respeitado, senão `raise ... from None` — que existe justamente para esconder o contexto — passaria a exibi-lo. E a travessia guarda os nós já vistos: cadeia cíclica é construível em Python e penduraria o logger, que é o pior lugar possível para um laço infinito.

Medido nos três modos: `from exc` (883 → 605 car.), implícito (815 → 604) e `from None` (261 → 195), com a fala do lead ausente nos três e o elo correto em cada um.

### D4 — Os três sítios de arq/Redis recebem o texto de volta, por kwarg

`turno.py:566`, `process_message.py:198` e `gerar_resumo.py:48` hoje têm **só** `exc_info=True`, sem nenhum kwarg de texto. Saneado o traceback, eles ficariam reduzidos a `RedisError` — e é exatamente onde a **D3 da TEC-292** afirmou que o texto é o que importa: o que sobra numa falha dessas é `Error 111 connecting to localhost:6379`, *"que é justamente o que se quer ler às três da manhã"*.

Os três passam a levar `motivo=str(falha)`, sob o argumento que a D3 já mediu e que aqui vale igual: **a única coisa que essas chamadas passam adiante é um UUID gerado por este projeto** — `registro.id` nos dois primeiros, `handoff_id` mais o `_job_id` derivado dele no terceiro. Não há entrada externa para a exceção ecoar. O comentário de cada sítio passa a dizer isso, em vez de justificar apenas o `exc_info`.

**Os outros três sítios não recebem nada novo.** `whatsapp.py:90` já tem `reason`; `whatsapp.py:122` já tem `reason` e `detail=motivo_do_erro_de_banco(exc)`; `importacao.py:133` já compõe o motivo curado antes de logar. Nos três, o traceback saneado é ganho líquido: some o texto cru que convivia com a curadoria.

**Isto fecha a ressalva que a TEC-292 deixou escrita.** A D4 daquele desenho diz que `webhook.persist_failed` *"não fica fechado por ela"*, porque o `log.exception` reemitia o que o `detail` curado havia evitado. A partir desta card, fica — e os comentários dos dois sítios de `whatsapp.py`, que hoje apontam a classe D como pendência, precisam deixar de dizer isso.

### D5 — O teste que existe hoje consagra o vazamento, e é reescrito

`tests/unit/test_logging_mascara.py:120`, `test_telefone_no_traceback_tambem_sai_mascarado`, é o único teste do repo que exercita a chave `exception`. Ele afirma:

```python
assert "5511987654321" not in caplog.text
assert "*********4321" in caplog.text
assert "ValueError" in caplog.text
```

A segunda asserta **exige que a mensagem da exceção chegue ao log**, contanto que mascarada — que é precisamente o comportamento que esta card acaba. Ela vai quebrar, e quebra pelo motivo certo.

O teste é reescrito para provar o oposto: dada uma exceção cuja mensagem contém a fala do lead, o log não contém nem o telefone, nem a versão mascarada dele, nem a frase — e contém o tipo e a pilha. O nome muda junto, porque o antigo descreve a garantia antiga.

Isto segue a restrição que o plano da TEC-292 deixou: *"cada quebra precisa de decisão consciente, não de ajuste mecânico da asserção para passar"*.

Entram dois testes novos:

- **cadeia de causas** — o caso medido acima, em que a mensagem vazava duas vezes; prova que nenhuma das duas seções leva mensagem e que o elo aparece;
- **`_finalizar` continua desarmando o `exc_info`** — hoje nada prova isso diretamente, e é a condição sem a qual o `Formatter` do stdlib reemite o traceback cru depois do JSON. Sem esse teste, a regressão mais cara desta card é silenciosa.

## O que se perde, dito sem rodeio

**A mensagem livre desaparece de todo traceback**, inclusive de exceções que nada têm a ver com lead e cujo texto era inofensivo. Onde ela era o diagnóstico, ela volta por kwarg curado (D4) — e a conta dos seis sítios é que em três ela nunca esteve num kwarg, nos outros três já havia curadoria.

Isso é a TEC-237 aplicada, não contrariada. Aquele precedente diz que uma regra de supressão *"aplicada sem exceção... apagou a única informação que resolvia o caso"*. A resposta desta card não é suprimir e torcer: é manter a estrutura inteira do erro — pilha, cadeia, tipo qualificado — e reintroduzir o texto, nomeado, onde ele é comprovadamente seguro. `motivo_do_provedor` e `motivo_do_erro_de_banco` continuam funcionando exatamente como antes; nenhum deles passa por traceback.

**Para exceções fora dos seis sítios**, o efeito é assimétrico e vale registrar: um `KeyError('conversation_key')` passa a aparecer como `KeyError` e ponto. Quem depurar vai ao frame, que está nomeado. O custo é real e foi aceito em troca de a garantia valer para todo `log.exception` que alguém escrever depois — inclusive o que ninguém vai revisar.

## Fora de escopo, e por quê

- **Ler o log de produção para medir volume.** O ganho de 1628 → 738 caracteres é medição de laboratório sobre o pior caso. Saber o volume agregado real exigiria acesso que esta card não tem, e não muda nenhuma das decisões acima.
- **Teto de tamanho no `motivo=` da D4.** A TEC-237 usou 300 caracteres para o corpo de erro de um provedor HTTP. Aqui o texto é de erro de conexão de Redis, curto por natureza, e um teto seria número sem medição por trás. Anotado, não implementado.
- **`admin/seed_catalogo.py:74-75`**, o `print()` que corre fora do mascarador. Herdado da TEC-292, continua anotado e continua fora: não passa por `exc_info` e não é traceback.
- **Os quatro pontos de classe C** (`turno.py:1307`, `:2176`, `process_message.py:333`, `importacao.py:78`). A D6 da TEC-292 já estabeleceu que estão protegidos pela garantia preexistente da TEC-237 e que nenhuma destas cards acrescenta proteção a eles.

# TEC-292 — log sem texto de exceção de terceiro

**Status:** implementado
**Card:** [TEC-292](https://eduardodurieuxlopes.atlassian.net/browse/TEC-292) — épico TEC-123
**Branch:** `feat/tec-292-log-sem-texto-de-excecao-de-terceiro`
**Origem:** levantamento feito durante a TEC-222, que fechou `messages.last_error` e deixou o log de fora de propósito.

## Objetivo

Tirar do log o texto de exceção que **este projeto não escreveu**, nos pontos em que ele pode ecoar entrada externa — sem jogar fora o diagnóstico que a TEC-237 comprou com um dia de investigação cega.

> **Sobre os números de linha deste documento.** Eles descrevem a árvore **antes** da branch, que é o estado que o desenho analisa — os comentários que a card acrescentou empurraram várias linhas para baixo. A `comentarios_tocados.py` marca 20 dessas citações como `PROSA` e **nenhuma** como `FALSO`; a conferência foi feita. Onde o alvo tem nome estável, ele é citado pelo nome.

## O que o levantamento corrigiu no enunciado da card

**São 29 pontos, não 25.** A card contou os 25 em que a *mensagem* de uma exceção entra num kwarg nomeado. Faltavam os **4 que só têm `exc_info=True`/`log.exception`** e nenhum kwarg de texto: `turno.py:566`, `process_message.py:214`, `gerar_resumo.py:48`, `importacao.py:111`. Como `app/logging.py:152` roda `format_exc_info` antes do mascaramento, o traceback vira a chave `exception` e chega ao log terminando em `TipoDoErro: <mensagem>`. São 15 arquivos, e `turno.py` concentra 9 pontos.

Classificados por **o que a exceção pode ecoar**, que é o que decide o tratamento:

| classe | o que é | quantos |
| --- | --- | --- |
| **A** | exceção de terceiro sobre entrada não confiável | 11 |
| **B** | exceção de `mobia` com texto escrito por este projeto | 10 |
| **C** | exceção de `mobia` cujo texto veio de terceiro | 4 |
| **D** | `exc_info` / `log.exception`, traceback inteiro | 4 exclusivos, 6 no total |

## O vetor de vazamento do banco não é o que a card supunha

A card herdou da TEC-222 a ideia de que o texto de um erro de SQLAlchemy carrega `[parameters: (...)]` com telefone e afins. **Medido contra o Postgres desta máquina, é falso** — `hide_parameters=True` (`infra/db.py:26`) funciona, e o texto traz literalmente `[SQL parameters hidden due to hide_parameters=True]`.

O vetor é outro: a linha **`DETAIL`**, que vem do **servidor** e por isso nenhuma configuração de cliente alcança.

**Violação de unique** — ecoa os valores das colunas da constraint:

```
duplicate key value violates unique constraint "uq_messages_channel_provider_message_id"
DETAIL:  Key (channel, provider_message_id)=(whatsapp, wamid.SENTINELA_ABC123) already exists.
```

**Violação de CHECK** — ecoa a **linha inteira**:

```
new row for relation "sonda_292" violates check constraint "ck_sonda_score"
DETAIL:  Failing row contains (5511987654321, quero 2 quartos na zona sul, -1).
```

**O telefone sobrevive por acidente, não por desenho.** `5511987654321` são 13 dígitos e o regex `\d{10,15}` de `app/logging.py:23` o mascara. Texto livre — bairro, título de imóvel, nome de arquivo — não tem nada que o pegue.

### Isto colide com a TEC-223, e ela não sabe

A TEC-223 quer pôr `CHECK` em `role`, `direction` e `content_type` de `messages`. Hoje `messages` não tem CHECK nenhum, então `Failing row contains` é **impossível** ali. Depois daquela card, passa a ser possível.

Em `messages` o estrago seria contido — `text_body`, `raw_payload` e `envelope_context` são `bytea` e sairiam como hex cifrado, e o telefone cai no regex de dígitos. Mas é uma porta que aquela card abre sem citar, e em outra tabela com coluna de texto em claro o resultado é diferente. Fica registrado na TEC-223, com a medição.

## D1 — A regra é por risco, não absoluta

A formulação tentadora é *"nunca logar `str(exc)` de exceção de terceiro"*. **Recusada**, e pelo precedente do próprio repositório: foi exatamente esse absolutismo que a TEC-237 teve de furar, depois de um dia inteiro de diagnóstico cego em que 91 falhas mostravam só o nome da classe e a causa — saldo esgotado — estava na primeira linha do corpo de erro.

A regra que fica:

> O texto de uma exceção de terceiro só vai para o log quando a chamada que ele descreve não carrega entrada externa, **ou** quando um extrator curado tira campos estruturados em vez do texto cru.

Aplicada às 11 ocorrências da classe A, ela não produz 11 mudanças iguais — produz quatro tratamentos diferentes, e é esse o trabalho da card.

## D2 — `motivo_do_erro_de_banco`, um extrator curado

Para os quatro pontos de SQLAlchemy — `api/routes/whatsapp.py:113`, `domain/messages/recorder.py:136` e `:203`, `domain/messages/service.py:206`.

A exceção que a SQLAlchemy levanta embrulha a do asyncpg, e é na embrulhada que estão os campos úteis. Medido:

```
[0] sqlalchemy.dialects.postgresql.asyncpg.IntegrityError
      sqlstate = '23514'
[1] asyncpg.exceptions.CheckViolationError        <- exc.orig.__cause__
      sqlstate        = '23514'
      constraint_name = 'ck_sonda'
      table_name      = 'sonda'
      detail          = 'Failing row contains (5511987654321, quero 2 quartos, -1).'
```

O extrator devolve `sqlstate`, `constraint_name` e `table_name`, e **nunca** `detail` nem `str(exc)`.

**Isso é diagnóstico melhor, não pior.** `23514` e `ck_sonda` são estruturados, greppáveis e dizem exatamente qual regra o banco recusou — enquanto `str(exc)` obrigava a ler prosa para descobrir o mesmo, e trazia a linha de dados junto.

Onde o `__cause__` não for uma exceção do asyncpg (erro de conexão, timeout), o extrator devolve `None` e o sítio fica só com `reason=type(exc).__name__`, que já está lá.

## D3 — Dos três pontos de Redis, dois mantêm o texto — e a razão fica escrita

`domain/messages/service.py:170` (`enqueue.failed`), `workers/jobs/sweep_stalled.py:105` (`sweep.enqueue_failed`) e o par de `api/routes/imoveis.py`.

O levantamento os pôs na classe A por serem exceção de terceiro. Mas a classificação desta card é sobre **o que a exceção pode ecoar**, e aqui o único argumento do job é um UUID que este projeto gerou: `enqueue_process_message` manda `str(message_id)`, e `importar_catalogo` manda `str(importacao_id)`. O texto que sobra é de nível de conexão — `Error 111 connecting to localhost:6379` —, que é justamente o que se quer ler às três da manhã.

Ficam como estão, **com comentário registrando por que** — sem ele, a próxima varredura os trata como esquecimento e os apaga.

### O mesmo destino HTTP tem outro escritor, e a revisão final o achou

`api/routes/imoveis.py` não é o único a gravar em `importacao.erros`. `domain/catalogo/importacao.py:109` grava ali `f"falha durante a gravacao: {erro}"`, e aquele `erro` vem de um `except Exception` em volta de `sincronizar(...)` — **exceção de SQLAlchemy, com a linha `DETAIL`**, num caminho cujos dados vêm do arquivo de catálogo importado.

É o mesmo vetor, na mesma coluna, servido pelo mesmo GET — e pior que o de `imoveis.py`, porque lá a exceção é de Redis e aqui é de banco. Entra nesta card, com `motivo_do_erro_de_banco`.

Não fosse isso, o comentário que a card escreve em `imoveis.py` — dizendo que aquela coluna não pode carregar texto de terceiro — seria falso no instante em que foi escrito.

**Fica de fora, de propósito:** `importacao.py:73`, que grava `str(erro)` de um `ArquivoInvalido`. O texto é de exceção do próprio projeto, e o que ele interpola é o nome do arquivo que o próprio cliente enviou, voltando para esse mesmo cliente. Registrado em comentário para a próxima varredura não o tratar como esquecimento.

### Menos um: `imoveis.py` tem segundo destino, e ele é servido por HTTP

`api/routes/imoveis.py:87` monta `motivo = f"falha ao enfileirar o job: {erro}"`, e esse valor vai para **dois** lugares: o log (`:130`) e `importacao.erros` (`:137`), coluna durável que o GET da rota devolve ao cliente.

É a mesma forma do `last_error` da TEC-222 — destino durável e fora da máscara — só que pior, porque é exposto por HTTP em vez de exigir acesso ao banco. Pelo argumento da TEC-222, este ponto **não** fica: `motivo` passa a nomear a falha sem interpolar `str(erro)`.

Os outros dois pontos de Redis não têm segundo destino e ficam.

## D4 — O ponto do parser perde o `detail`

`api/routes/whatsapp.py:86` loga o texto de uma exceção de `parse_meta_envelope` sobre o envelope cru da Meta. O eco realista é estrutural (`AttributeError: 'str' object has no attribute 'get'`), mas o envelope é entrada externa por definição e nada garante o formato da próxima exceção.

O `detail` sai; `reason=type(exc).__name__` fica. O `log.exception` da mesma chamada continua emitindo o traceback — **isso é classe D e fica fora desta card**, o que significa que este ponto **não fica fechado por ela**. Dito assim, sem rodeio, porque meia-solução que se apresenta como solução é pior que nenhuma.

## D5 — Os dois `motivo_do_provedor` têm o mesmo nome e garantias diferentes

| onde | o que devolve |
| --- | --- |
| `infra/anthropic.py:173` | extrai `status_code`, `error.type` e `error.message` do corpo, com teto de 300 |
| `infra/embeddings.py:115` | `f"{exc.status_code}: {str(exc)[:300]}"` — **`str(exc)` cru** |

O da OpenAI renderiza `Error code: 400 - {'error': {'message': ..., 'param': ...}}` inteiro, e o `input` daquela chamada é o documento do imóvel montado a partir do arquivo importado. O docstring dele afirma seguir "a mesma exceção deliberada" do outro — e não segue: o outro extrai campos, este passa o texto.

O de `embeddings.py` passa a extrair campos como o da Anthropic. A TEC-237 abriu a exceção para *o corpo de erro que o servidor escreveu*, não para `str(exc)` de um SDK.

## D6 — A classe C não muda, e esta card não é o que a protege

Os quatro pontos da classe C — `turno.py:1307` e `:2176` (`ModeracaoIndisponivel`), `process_message.py:443` (`_detalhe_para_o_log`) e `importacao.py:78` (`ArquivoInvalido`) — não aparecem nas decisões acima, e a revisão final apontou a lacuna. Aqui está a decisão, e ela tem duas metades.

**Os três primeiros já estavam protegidos antes desta card, e não por ela.** `ModeracaoIndisponivel` só carrega texto variável quando `infra/moderacao.py:176` a levanta com `motivo_do_provedor(exc)` — e o import daquele módulo é o de **`infra/anthropic.py`**, o que já extraía campos. Os outros três `raise` de `moderacao.py` usam literal. `_detalhe_para_o_log` repassa a mensagem de exceções de `mobia`, e a pior que chega lá é justamente essa mesma. A garantia é a da TEC-237, preexistente.

> **Correção.** A primeira versão desta seção dizia que os três passavam "pelo funil que a D5 conserta", e que havia frouxidão entre os dois `motivo_do_provedor` afetando a classe C. **É falso, e foi conferido nos imports:** o `motivo_do_provedor` de `infra/embeddings.py` — o único que estava frouxo, e o que a D5 conserta — é importado **só** por `workers/jobs/indexar_catalogo.py:59`, que é ponto de classe **A**. Ele nunca alcança a classe C. A D5 é uma decisão de classe A que eu havia atribuído à classe C.

**O quarto** é o `ArquivoInvalido` discutido na D3: exceção do projeto, interpolando o nome do arquivo que o cliente enviou de volta para esse mesmo cliente. Fica.

Conclusão honesta: **esta card não acrescenta proteção nenhuma à classe C.** Ela a examinou, encontrou a garantia já de pé, e registra isso para que a próxima varredura não conclua que os quatro pontos foram esquecidos.

## Fora de escopo, e por quê

- **Classe D, os 4 a 6 pontos de `exc_info`.** Traceback é o que torna erro diagnosticável, e removê-lo é decisão de outra natureza — não cabe junto de uma mudança que se justifica por risco estreito. **Card nova.** Consequência dita: `whatsapp.py:83` e `:110` continuam emitindo traceback depois desta card.
- **Classe B, os 10 pontos.** Fui a cada `raise`: literais, inteiros, enums e `type(x).__name__`. Sem mudança.
- **Dar regra de conteúdo ao mascarador.** A card perguntava se valia. Não nesta: mascarar texto livre em português é heurística com falso negativo garantido, e a resposta estrutural — não deixar o texto chegar lá — é a que esta card implementa.
- **`admin/seed_catalogo.py:74-75`**, que faz `print()` de motivos de rejeição direto no stdout, sem passar pelo mascarador. É script administrativo, não caminho de produção, mas aterrissa no mesmo coletor. Anotado.

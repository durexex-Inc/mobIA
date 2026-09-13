# TEC-273 — A reserva sobrevivente para de colar metade de um texto na metade de outro

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-273](https://eduardodurieuxlopes.atlassian.net/browse/TEC-273) — Bug, prioridade High, épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133). Origem: RN-04.2; introduzido pela TEC-140.

## Objetivo

O lead lê a primeira metade de um texto colada na segunda metade de outro, e nada no sistema diz que isso aconteceu.

A TEC-140 passou a entregar a resposta longa em **duas mensagens**, com `kind` próprio (`reply` e `reply_2`). `outbound_dispatches` tem `UNIQUE (message_id, kind)` e `GuardedOutbound.send` libera **só a reserva do kind que falhou**. Então:

1. A parte 1 sai e mantém a reserva de `reply`.
2. A parte 2 toma um `EnvioRetentavel` — um 429 na segunda de duas mensagens em rajada é o caso mais provável — e libera só `reply_2`.
3. A linha vira `FAILED`, que está em `CLAIMABLE_STATUSES`.
4. O sweeper reenfileira e o turno roda inteiro **com uma chamada nova ao modelo**: texto B ≠ texto A.
5. A parte 1 de B é suprimida pela reserva viva de `reply`.
6. A parte 2 de B sai.

**O lead recebe a primeira metade de A seguida da segunda metade de B.**

Este repo já decidiu que duplicata é melhor que perda — *"a duplicata e visivel e recuperavel e o silencio nao"* (TEC-134, TEC-227). O caso aqui não é nenhum dos dois: é **corrupção silenciosa de conteúdo**, uma terceira categoria que aquele precedente não cobre.

## O que a exploração descobriu

### A reserva significa coisas opostas nos dois caminhos de entrega

A card propõe liberar as reservas irmãs **do mesmo `message_id`**. As fichas compartilham o `message_id` com a resposta de texto, e a TEC-275 — mergeada hoje — usa exatamente essas reservas como sinal de que houve entrega parcial:

```
ja_reservados & {linha.kind for linha in lote}
```

Se uma falha retentável apagasse toda reserva da mensagem, esse conjunto ficaria vazio, `_continuar_entrega` nunca seria tomada, e todo reprocessamento cairia no ramo que refaz o turno inteiro. **A liberação por `message_id` neutralizaria a TEC-275** no único caso para o qual ela existe.

A razão de fundo:

| | O que a retentativa faz | O que ela quer da reserva |
|---|---|---|
| **Texto** | **regenera** — chamada nova ao modelo | que ela **suma**, senão mistura gerações |
| **Fichas** (pós-TEC-275) | **repete** — lote persistido, sem modelo | que ela **fique**, é o que diz "esta já saiu" |

Texto é regenerado; ficha é reproduzida de estado persistido. **É essa diferença, e não o `message_id`, que define o escopo certo da liberação.**

### O segundo sintoma tem a mesma raiz e não some sozinho

Quando a parte 1 é suprimida e a parte 2 sai, o laço faz `continue` e `entrega_parcial` nunca é marcada. O recorder grava o texto **inteiro** e o turno devolve `"respondido"`, sem log. A transcrição que o corretor lê no handoff afirma que o texto novo saiu completo.

O comentário daquele `continue` chama isso de *"o caso legitimo da retentativa do sweeper"* — e com a D1 abaixo aquela retentativa deixa de existir. O que sobra ali é anomalia, não caminho normal.

### Nenhuma implementação sobrescreve `send`

`OutboundPort` é um Protocol estrutural, mas todas as implementações reais (`WhatsAppOutbound`, `NoopOutbound`, os dublês dos testes) herdam de `GuardedOutbound` e definem apenas `_deliver`. Mudar o corpo de `GuardedOutbound.send` alcança todas elas sem tocar em nenhuma.

## Decisões

### D1 — A liberação é por GRUPO de kind, não por mensagem

Uma falha retentável libera a reserva do kind que falhou **e as dos kinds do mesmo grupo**. Um grupo é o conjunto de kinds que carregam **uma resposta regenerável**: hoje, `reply` e `reply_2`.

As fichas não formam grupo, e é decisão, não omissão: o lote delas é reproduzido de estado persistido pela TEC-275, então não há duas gerações para misturar, e a reserva é o que impede o lead de receber a mesma ficha duas vezes.

### D2 — O grupo mora num módulo próprio do domínio de saída, e o port importa

O port **não** ganha as constantes dentro dele. O repo já tem um padrão para isto, e é o oposto: `KIND_DA_CONFIRMACAO_DE_OPTOUT` mora em `domain/optout/deteccao.py` — o módulo que possui o comportamento — e tanto `port.py` quanto `turno.py` o importam de lá.

Seguindo esse padrão, nasce `src/mobia/domain/outbound/kinds.py`, com uma responsabilidade só: **o vocabulário de kinds de saída e quais deles formam uma mesma resposta regenerável.** `KIND_DA_RESPOSTA` e `KINDS_DA_RESPOSTA` saem de `turno.py` para lá; `port.py` importa os grupos; `turno.py` importa os kinds.

Os testes que hoje fazem `from mobia.domain.agente.turno import KINDS_DA_RESPOSTA` continuam funcionando sem alteração — o nome segue no namespace do módulo por causa do import, exatamente como o comentário de `turno.py` já registra para o kind de opt-out.

A alternativa — um parâmetro `irmaos=` em `send`, preenchido pelo chamador — foi descartada: **um chamador que esquecesse o parâmetro recairia exatamente no defeito de hoje, em silêncio.** E o docstring do `OutboundPort` já argumenta que guarda mora no port justamente para quem herda ganhar de graça.

O ganho decisivo do arranjo é que **o grupo e a lista de partes viram a mesma constante**. Não existe mapa paralelo para dessincronizar: quem acrescentar um `reply_3` tem de editar aquela tupla, e o grupo acompanha.

**Custo aceito:** um módulo novo, pequeno. Ele paga por não inverter a dependência (`port.py` não pode importar de `domain/agente`, que já importa dele) e por eliminar uma classe inteira de erro do chamador.

### D3 — O cancelamento recebe o mesmo tratamento, porque já divide a cláusula

`EnvioRetentavel` e `asyncio.CancelledError` compartilham o mesmo `except` hoje, e o comentário de lá explica por quê: o que fazer é idêntico, e duas cópias divergiriam.

A exposição também é idêntica — o turno morre, o sweeper reprocessa, e a chamada nova ao modelo gera texto B. A TEC-227 já escolheu duplicata sobre perda para o cancelamento; liberar as irmãs é o mesmo lado da mesma escolha. **Nada na cláusula se separa.**

### D4 — Parte suprimida antes de uma entregue deixa de ser caminho normal

O ramo `not entrou and not entregue` faz `continue` hoje. Passa a marcar `entrega_parcial` e parar, como o ramo `entregue` já faz.

Com a D1, a retentativa do sweeper não produz mais esse estado. O que ainda produz é uma **reserva presa** — a liberação que falha por deadlock ou conexão caída, que `port.py` já antecipa e loga como `outbound.liberacao_falhou`. Isso é anomalia, e a transcrição não pode afirmar que o texto saiu inteiro por causa dela.

Sai um log próprio, distinto de "nada saiu", como o segundo cenário Gherkin da card pede.

### D5 — `marcar_desambiguacao` ganha a guarda que falta

A guarda de `marcar_perguntados` tem quatro condições; a de `marcar_desambiguacao` tem três — falta `not entrega_parcial`.

O argumento que a TEC-140 escreveu para `marcar_perguntados` vale palavra por palavra aqui: `entrega_parcial` não diz **onde** dentro do texto a quebra caiu, então a pergunta pode ter saído inteira, pela metade, ou nem ter existido na parte entregue. Marcar quando ela ficou na parte suprimida queima, para sempre e em silêncio, a única pergunta do episódio. Repetir a pergunta é irritante e reversível; queimá-la não é.

### D6 — O docstring do `OutboundPort` volta a ser verdade

O bullet de `EnvioRetentavel` afirma *"A guarda libera a reserva e propaga... O lead recebe eventualmente"*. Para o caminho de texto em duas partes isso **deixou de ser verdade** na TEC-140. Corrigido o mecanismo, volta a ser — e o texto passa a dizer "as reservas do grupo", não "a reserva".

É o arquivo que o repo elegeu como o contrato; comentário que mente ali é o pior lugar para ele morar.

## Arquivos

| Arquivo | O quê |
|---|---|
| `src/mobia/domain/outbound/kinds.py` | **Criar.** `KIND_DA_RESPOSTA`, `KINDS_DA_RESPOSTA` e os grupos (D2) |
| `src/mobia/domain/outbound/port.py` | liberação das irmãs na cláusula retentável/cancelamento (D1, D3); docstring do Protocol (D6) |
| `src/mobia/domain/agente/turno.py` | importa os kinds do módulo novo; o ramo da D4; a guarda da D5 |
| `tests/integration/` | os dois cenários Gherkin da card, mais D3, D4, D5 e os dois testes de fronteira |

## Testes

Os dois cenários da card são o critério de aceite:

1. **Falha retentável na parte 2 não mistura gerações** — parte 1 entregue, parte 2 retentável, mensagem reprocessada: as duas partes que o lead recebe na segunda passada vêm da **mesma** geração.
2. **Parte suprimida antes de uma entregue não é gravada como entregue** — a transcrição carrega só o que saiu, e um log distingue o caso de "nada saiu".

Somam-se:

3. **A liberação não alcança as fichas** — uma falha retentável no caminho de texto não apaga reserva de ficha, e vice-versa. É este teste que impede alguém de "simplificar" a D1 para o `message_id` inteiro e desfazer a TEC-275 sem perceber.
4. **A continuação da TEC-275 continua sendo tomada** depois de uma falha retentável numa ficha — a prova de que a D1 não regrediu o caminho vizinho.
5. **`marcar_desambiguacao` não marca com entrega parcial** (D5).
6. **Cancelamento libera as irmãs igual ao retentável** (D3).

## Lacunas conhecidas

**L1 — A fresta equivalente no caminho das fichas fica aberta, e é a L4 da TEC-275.** Quando a única ficha entregue é de um imóvel repetido, o `kind` dela pertence à mensagem anterior, a continuação não é tomada, e o turno inteiro roda de novo com a reserva daquela ficha viva: a ficha 1 da geração nova é suprimida — **junto com a prosa, que viaja nela**. É mistura de gerações para fichas.

O conserto **não** é liberar as irmãs: seria quebrar o caminho comum para consertar o raro. É fechar a L4, que já está registrada como card própria no desenho da TEC-275.

**L2 — Reserva presa continua possível.** A D4 faz a transcrição parar de mentir quando isso acontece, mas não impede que aconteça. `port.py` já antecipa e loga; fechar de verdade exigiria um mecanismo de expiração de reserva, fora do escopo desta card.

**L3 — A duplicata que a correção aceita é real e visível.** Liberada a reserva de `reply`, a retentativa reenvia a parte 1 da geração nova, e o lead lê dois textos parecidos em sequência. É deliberado: é o lado que o precedente TEC-134/TEC-227 já escolheu, e é preferível à corrupção silenciosa. Nada nesta card tenta suprimir essa duplicata.

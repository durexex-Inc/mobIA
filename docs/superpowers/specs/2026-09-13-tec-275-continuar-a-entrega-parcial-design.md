# TEC-275 — A retentativa de uma apresentação parcial continua a entrega em vez de refazer o turno

**Status:** desenhado em 2026-09-13.

**Card:** [TEC-275](https://eduardodurieuxlopes.atlassian.net/browse/TEC-275) — Tarefa, prioridade High, épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155). Origem: o defeito que a correção `5806c06` da TEC-163 introduziu. Os cinco defeitos que deram nome à card estão fechados na `main`; este desenho trata só do que sobrou.

## Objetivo

O lead recebe as três fichas e, no turno seguinte, não existe lista contra a qual "gostei do segundo" possa ser resolvido. A reação dele não cai no imóvel errado — ela não cai em lugar nenhum.

Isso acontece quando a entrega falha no meio de forma retentável e a varredura reprocessa a mesma mensagem.

## O que a exploração provou

Os dois caminhos abaixo estão exercitados por teste em `tests/integration/test_recomendacao_e_reacao.py` (commit `a4e1a2d`), **vermelhos de propósito**. Ambos terminam com `ler_pendentes` vazio depois de o lead ter recebido as três fichas.

| Retentativa | Quem fecha as linhas | Valor gravado |
|---|---|---|
| `reagir` funciona | `gravar_reacoes`, antes de reenviar qualquer ficha | `NEUTRO` |
| `reagir` estoura | `conciliar_apresentacao`, pelo `apresentado_em < agora` | `SEM_RESPOSTA` |

**São dois caminhos, não um.** A correção que a versão anterior da card propunha — distinguir apresentações dentro de `conciliar_apresentacao` — fecha o segundo e deixa o primeiro de pé. É esse fato que descarta o desenho óbvio.

### A combinação que produz os dois

Dois fatos deliberados de `_apresentar` se combinam mal:

- `gravar_recomendacoes` grava **o lote inteiro com um único `agora`**, ANTES do laço de entrega (a L1 da TEC-162: gravar antes é o que salva o conjunto escolhido de uma falha de rede no meio);
- `conciliar_apresentacao` fica **fora do `try`**, depois do laço, para não apagar linha de ficha que a retentativa ainda vai entregar.

Quando a ficha 2 levanta `EnvioRetentavel`, as três linhas já existem com `agora_1`, o lead viu só a primeira, e nenhuma conciliação rodou. Na retentativa o turno reentra pelo topo e o `ON CONFLICT DO NOTHING` preserva o carimbo antigo — as três ficam `< agora_2`.

### O que funciona e não deve ser mexido

Na retentativa a ficha 1 é suprimida como duplicata (a reserva dela sobreviveu) enquanto a da ficha 2 foi liberada pelo `EnvioRetentavel`. **O lead recebe cada ficha exatamente uma vez somando as duas passadas.** Esse lado não tem defeito e nenhuma decisão abaixo o altera.

## Decisões

### D1 — A segunda passada é continuação da entrega, não um turno novo

Reentregar a mesma apresentação não é apresentar de novo, e também não é o lead ter tido chance de reagir. Hoje o turno não distingue os dois, e é dessa falta que os dois caminhos nascem.

A continuação **não rebusca, não chama o classificador e não chama `reagir`**. Ela termina a entrega do conjunto que a primeira passada escolheu e retorna.

Isso fecha os dois caminhos de uma vez, porque nenhum dos dois chega a rodar — e não por uma guarda em cada um, que é o que tornaria a correção frágil.

### D2 — A apresentação passa a ser um fato da mensagem

`Recomendacao` é chaveada por `(channel, conversation_key, imovel_id)` e **não tem `message_id`**. Sem ele, "a apresentação desta mensagem" não é consultável — só inferível pelo `apresentado_em` mais recente da conversa, que é inferência e não fato.

Migration acrescenta duas colunas a `recomendacoes`:

| Coluna | Tipo | Por quê |
|---|---|---|
| `message_id` | FK para `messages`, **nullable** | Dá dono à apresentação. Nullable porque as linhas existentes não têm um, e inventar um seria mentira. |
| `preco_centavos` | inteiro, nullable | Ver D3. Nullable pela mesma razão que `message_id`. |
| `kind` | `String(32)`, nullable | Ver D9. |

### D3 — `preco_centavos` é o único campo da ficha que não sai do catálogo

Dos dez campos de `Ficha`, nove vêm da linha de `imoveis`. O décimo é o preço, e `fichas_do_catalogo` o recebe **do dict do candidato, não da linha** — de propósito: a linha tem `preco_venda` e `preco_aluguel` e não diz qual usar, porque a operação buscada só existe dentro de `porta_de_busca`. Ler a coluna aqui faria toda busca de aluguel mostrar preço de venda ao lead (D7 do desenho da TEC-162).

Persistir o preço **já resolvido** evita guardar a operação e refazer a escolha. É o valor que o lead viu, que é exatamente o que uma continuação precisa reproduzir.

**Custo aceito:** o preço mostrado ao lead passa a morar em dois lugares. A mitigação é semântica, não técnica — a coluna guarda *o que foi apresentado*, um fato histórico, e não *o preço do imóvel*, que continua só em `imoveis` e pode mudar depois sem que a linha de apresentação deixe de estar certa.

### D4 — Três ramos, e o do meio é o que resolve o caso da prosa

No topo de `executar_turno`, antes da passagem de reação:

| Estado | O que o lead viu | Ramo |
|---|---|---|
| Nenhuma linha com este `message_id` | — | Turno normal |
| Linhas, nenhuma reserva de ficha | Nada | **Apaga as órfãs** e roda o turno inteiro |
| Linhas + reservas parciais ou totais | Parte ou tudo | **Continuação** |

O ramo do meio existe por um caso limite real: **se a ficha que falha é a primeira, nada chegou ao lead** — nem as fichas, nem a prosa do agente, que viaja junto com a ficha 1 (D5 da TEC-162) e não está persistida em lugar nenhum se não chegou a sair. Continuar uma entrega em que nada saiu não é continuar; é recomeçar.

A consequência que fecha o problema: **a continuação nunca precisa da prosa**, porque só existe se algo já saiu, e o que sai primeiro é a ficha 1 com a prosa.

As linhas órfãs precisam ser apagadas, e não ignoradas: o `ON CONFLICT DO NOTHING` da passada nova preservaria o carimbo velho, e o UNIQUE por conversa impediria a linha nova de nascer.

O ramo de baixo cobre também o caso "tudo entregue e o turno morreu depois do laço": a continuação entrega zero fichas, concilia e retorna. Um ramo, não dois.

### D5 — A ordem do lote é a mesma regra de `ler_pendentes`

A posição N é o ordinal N (D7 da TEC-163). A continuação reconstrói o lote ordenando por `apresentado_em, score_match DESC, imovel_id` — **a mesma ordenação de `ler_pendentes`**, cujo docstring já argumenta por que ela reproduz a ordem de apresentação real.

Reusar a regra em vez de escrever uma segunda é o ponto: duas cópias podem divergir, e o preço da divergência aqui é a reação do lead grudando no imóvel errado.

Esta decisão governa a ORDEM em que a continuação entrega. Ela **não** governa qual `kind` cada ficha usa — ver D9.

### D6 — A continuação concilia com o carimbo ORIGINAL

`conciliar_apresentacao` recebe hoje o `agora` do lote. A continuação passa o `apresentado_em` **persistido**, não um `now()` novo.

Metade do conserto está aqui: com o carimbo original, as linhas do próprio lote deixam de ser `apresentado_em < agora` e o Caminho 2 não tem o que fechar. E o ramo que apaga (`apresentado_em == agora`) volta a casar as linhas do lote, que é o que permite aplicar a D7 abaixo.

### D7 — Conjunto incompleto: entrega o que restou

`fichas_do_catalogo` derruba id sem linha, e a D6 da TEC-162 chama isso de caminho normal — o imóvel saiu do catálogo entre a busca e agora. Entre duas passadas separadas por uma volta da varredura, isso deixa de ser hipotético.

A continuação **entrega as fichas que ainda existem e apaga a linha das que sumiram**, pelo mesmo ramo `nao_entregues` que a conciliação já tem. O lead recebe duas de três e não é avisado: a lista de pendentes fica com o que ele de fato viu, que é a invariante que esta card existe para proteger. Sai log com os ids faltantes, como `apresentacao.fichas_sumiram_do_catalogo` já faz.

Avisar seria pior: o lead pode nunca ter visto a ficha que sumiu, e avisar sobre um imóvel que ele não chegou a ver é confuso.

### D8 — A linha da ficha recusada é apagada no instante da recusa

**Decisão de apoio, e a menos óbvia deste desenho.**

Hoje a linha da ficha recusada é apagada depois do laço, na conciliação. Se o turno morre no meio do laço, essa limpeza nunca acontece — e aí "existe reserva" deixa de significar "o lead recebeu", porque uma recusa permanente **também deixa reserva** (o `except` que libera cobre só `EnvioRetentavel` e `CancelledError`; falha permanente mantém a reserva de propósito).

Sem isso a D4 fica sobre areia: a continuação leria a reserva de uma ficha recusada como entrega feita, e a linha de um imóvel que o lead nunca viu sobreviveria como pendente — **o defeito nº 2 da própria card, de volta por uma porta estreita**.

A correção é mover só a metade que apaga para dentro do `except EnvioRecusado`. A metade que **fecha** pendentes antigas continua depois do laço, porque depende de `houve_entrega`, que só se conhece no fim. A que apaga não depende de nada que o resto do laço produza.

### D9 — O `kind` é gravado na linha, não reconstruído pela posição

`kind` é posicional (`KINDS_DAS_FICHAS[posicao]`), e a tentação é reconstruí-lo re-indexando o lote na continuação. **Isso está errado, e é a D8 que o quebra:** quando a linha de uma ficha recusada é apagada, as linhas restantes re-indexam e todas as posições seguintes deslocam. O lote reconstruído diria `ficha_1` para o imóvel que saiu como `ficha_2`, e a continuação leria a reserva errada — reenviando o que já foi, ou pulando o que falta.

O mesmo vale, sem a D8, para o imóvel que sumiu do catálogo (D7): o lote reconstruído é menor que o apresentado, e re-indexar desloca tudo depois do buraco.

`gravar_recomendacoes` grava o `kind` de cada linha. Ela já recebe os candidatos na MESMA ordem e com o MESMO filtro que o laço de entrega usa (`escolhidos` restrito a `encontrados`), então a posição que ela enxerga é a que o laço vai enumerar.

Com a coluna, a pergunta "esta ficha já saiu?" vira uma junção direta com `outbound_dispatches` por `(message_id, kind)` — um fato, e não uma inferência posicional que a primeira deleção invalida.

## Arquivos

| Arquivo | O quê |
|---|---|
| `alembic/versions/` | migration com as três colunas da D2 |
| `src/mobia/domain/agente/models.py` | as três colunas em `Recomendacao` |
| `src/mobia/domain/agente/repositorio.py` | leitor do lote por `message_id`; `gravar_recomendacoes` passa a gravar `message_id`, `preco_centavos` e `kind`; o `delete` da D8 |
| `src/mobia/domain/agente/turno.py` | os três ramos da D4; a continuação; a conciliação com carimbo original (D6); a deleção antecipada (D8) |
| `tests/integration/test_recomendacao_e_reacao.py` | os dois testes vermelhos que já existem passam a ser o critério |

## Testes

Os dois vermelhos de `a4e1a2d` são o critério de aceite — eles afirmam que as três linhas continuam pendentes depois da retentativa, e devem ficar verdes.

Somam-se:

1. **Continuação com imóvel sumido do catálogo** (D7) — o lead recebe as que restaram e a lista de pendentes tem só essas.
2. **Ramo "nada saiu"** (D4) — a ficha 1 falha de forma retentável, a retentativa roda o turno INTEIRO e as linhas órfãs não sobrevivem.
3. **Recusa permanente seguida de morte do turno** (D8) — a linha da ficha recusada não sobrevive como pendente.
4. **Continuação com tudo já entregue** (D4) — entrega zero fichas, concilia, e as pendentes continuam pendentes.
5. **Recusa na ficha 1 e falha retentável na ficha 3** (D9) — o caso que a reconstrução posicional erra. A linha da ficha 1 já não existe (D8), e a continuação tem de enviar a ficha 3 com o `kind` dela, não com o da posição para a qual ela deslizou. Sem a coluna `kind` este teste reprova; é ele que justifica a D9.

## Lacunas conhecidas

**L1 — O percurso por `sweep_stalled` → `process_message` não é exercitado.** Os testes chamam `executar_turno` duas vezes sobre a mesma linha de `messages`, que é o que o reprocessamento faz com o turno. O caminho da varredura está confirmado por leitura (`sweep_stalled` reenfileira `process_message`, e `FAILED` está em `CLAIMABLE_STATUSES`), não por execução.

**L2 — `message_id` nullable deixa as linhas antigas sem dono.** Uma apresentação anterior a esta card que esteja pendente no momento do deploy não é continuável: cai no ramo "turno normal". É o comportamento de hoje, não uma regressão, e some sozinho conforme as conversas avançam.

**L3 — Duas mensagens da mesma conversa processadas concorrentemente não são cobertas.** O desenho assume processamento serial por conversa. Se duas mensagens da mesma conversa estiverem em voo ao mesmo tempo, a continuação de uma pode conciliar sobre linhas da outra. Nada neste desenho piora esse cenário — a conciliação de hoje já é por conversa — mas ele também não o fecha.

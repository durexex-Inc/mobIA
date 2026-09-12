# TEC-163 — Registrar a recomendação e realimentar os filtros com a reação

**Status:** desenhado em 2026-09-12.

**Card:** [TEC-163](https://eduardodurieuxlopes.atlassian.net/browse/TEC-163) — História, Should (MoSCoW), prioridade High. Origem: RF-10, RN-10.3 e RN-10.4 (SRS v1.0). Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155).

**A história:** *"Como Marina, que já descartou dois imóveis por serem longe demais, quero que as próximas sugestões levem isso em conta, para não continuar recebendo mais do mesmo."* O contorno que a card registra — e que esta implementação substitui — é o lead repetir o critério explicitamente: *"funciona, mas é exatamente o tipo de atrito que o produto promete eliminar"*.

**Desbloqueada pela [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162)**, que entregou a apresentação.

**Esta card foi encomendada por escrito pela TEC-162.** O docstring de `_apresentar`, em `turno.py`, registra que uma falha parcial na entrega perde o conjunto escolhido e o turno seguinte pode reapresentar os mesmos imóveis — e nomeia a correção: *"A correcao de verdade e persistir o conjunto escolhido -- a `Recomendacao` da TEC-163. Ate la, isto e custo herdado e nao surpresa."* A peça A abaixo é esse pagamento, e é por isso que o plano a entrega antes de tudo.

## Objetivo

Fazer valer a RN-10.3 e a RN-10.4: toda apresentação vira uma `Recomendacao` com o motivo do match; a reação do lead é registrada; e a reação realimenta os filtros da mesma conversa, com o lead sempre sabendo do ajuste.

**O que a card entrega**, em três peças que o plano executa nesta ordem:

| Peça | Entrega | Fecha |
|---|---|---|
| **A** | A tabela, a persistência do conjunto apresentado, e `motivo_match` | RN-10.3, e a L1 da TEC-162 |
| **B** | A captura da reação e a resolução de "gostei do segundo" | CA-10.1, metade da RN-10.4 |
| **C** | A realimentação do filtro e o aviso ao lead | metade da RN-10.4, cenário 3 |

**A ordem não é arbitrária.** A peça A é independente das outras duas, tem valor sozinha e conserta um defeito declarado. Se a B travar por algum motivo que este desenho não previu, a card ainda terá entregue a tabela, a persistência e o conserto da dívida — e a B vira card própria com o problema já medido.

**O que ela não entrega:** exibição da taxa de conversão no dashboard (a própria card exclui, E8); realimentação de dimensões que não sejam bairro (ver a L4).

## O estado de hoje

Não existe tabela de recomendação, nem modelo, nem migration. `_apresentar` entrega até 3 fichas e não registra nada além do log e das linhas de `outbound_dispatches`.

**Não existe entidade `Conversa`.** O SRS a especifica e o sistema nunca a teve: `conversation_summaries`, `lead_qualification` e `conversation_intent` se chaveiam no par `(channel, conversation_key)`. Três tabelas divergem do modelo de dados do SRS e nenhuma escreveu a emenda.

A margem do orçamento do prompt é **6,2 tokens** — medida em 11/09/2026, e o número de hoje sai de `pytest -q -k margem_do_orcamento -s`. O histórico registra que um campo de schema como `perguntou` custou ~18,5. Qualquer desenho que peça campos novos ao classificador principal está morto antes de começar, e é isso que empurra a D6.

## Decisões

### D1 — A card se entrega em três peças, e a A vai primeiro

Ver a tabela do objetivo. A A não depende da B nem da C, e paga a L1 da TEC-162 sozinha.

### D2 — A tabela se chaveia no par `(channel, conversation_key)`, não em `conversa_id`

```sql
CREATE TABLE recomendacoes (
    id                UUID PRIMARY KEY,
    channel           VARCHAR(32)  NOT NULL,
    conversation_key  VARCHAR(64)  NOT NULL,
    imovel_id         UUID         NOT NULL REFERENCES imoveis(id),
    score_match       NUMERIC(4,3) NOT NULL,
    motivo_match      TEXT         NOT NULL,
    reacao_lead       VARCHAR(16),
    motivo_descarte   VARCHAR(80),
    apresentado_em    TIMESTAMPTZ  NOT NULL,
    UNIQUE (channel, conversation_key, imovel_id)
)
```

**Não é escolha desta card.** É o que o sistema faz desde `conversation_summaries`, e seguir o SRS aqui exigiria criar uma entidade `Conversa` que nenhuma das outras três tabelas usa — introduzindo um segundo jeito de identificar conversa, que é pior que a divergência. A emenda da RN-10.3 declara isso, e declara que está três tabelas atrasada.

`reacao_lead` é `VARCHAR(16)` com `StrEnum` do lado Python, no molde de `TipoImovel` e `StatusImovel`: não existe um único tipo `ENUM` do Postgres neste repositório, e esta não vai ser a primeira.

### D3 — O `UNIQUE` torna o cenário 4 verdade por construção

`UNIQUE (channel, conversation_key, imovel_id)` faz *"os já apresentados não são repetidos"* ser garantia de schema em vez de disciplina de consulta. O `id` surrogate fica, no molde de `imoveis` (PK `id`, UNIQUE em `codigo`).

### D4 — `motivo_match` é por BUSCA, não por imóvel

O instinto é carregar um motivo em cada candidato. Mas **todos os candidatos de uma busca casaram o mesmo filtro**; o que varia entre eles é o score, que já tem coluna própria. Um motivo por candidato seria a mesma frase repetida três vezes, **paga em tokens no `tool_result` de todo turno que busca** — e o `tool_result` viaja no contexto.

A ferramenta devolve **um** campo por busca: os critérios que de fato entraram no `WHERE`. O turno renderiza a frase em Python na hora de gravar.

**Consequência declarada:** os imóveis de uma mesma apresentação terão `motivo_match` idêntico. Para o propósito que o SRS dá ao campo — medir conversão por imóvel — isso é correto: o motivo explica por que aquele conjunto apareceu, e o que distingue os imóveis é o `score_match`. Se algum dia o motivo precisar variar por imóvel, ele terá de vir de algo que varie por imóvel, e hoje não existe. Ver a L3.

### D5 — `motivo_match` é derivado, nunca escrito pelo modelo

Código monta a frase a partir do que a busca já sabe: quais filtros bateram, e se houve relaxamento. É a postura da RN-09.4 e do RT-01 — dado factual sai de código, nunca do modelo.

**Um motivo inventado ficaria gravado no banco como se fosse fato.** Explicabilidade falsa é pior que explicabilidade pobre: a pobre se reconhece, a falsa não.

### D6 — A reação vem de uma segunda chamada dedicada, não do schema principal

`classificador.reagir(contexto, apresentados)`, método novo no protocolo, no molde exato de `desambiguar`, com `SISTEMA_DA_REACAO` e schema próprios.

**Por que não pelo schema principal.** O teto fixo mede quatro parcelas — `SISTEMA_DO_AGENTE`, o schema compilado, os rótulos de `montar_prompt` e a definição em `tools=` — e a margem é de 6,2 tokens. Esta card precisaria de dois a três campos (reação, qual imóvel, motivo do descarte), na ordem de 50 tokens. As três saídas do manual estão fechadas: subir o teto fixo acima do derivado o torna decorativo, subir `contexto_headroom_de_tokens` custa 180 tokens por turno, e não há linha barata para cortar — cada uma veio de uma card.

`SISTEMA_DA_DESAMBIGUACAO` **não** entra na subcontagem, porque é outra chamada. `SISTEMA_DA_REACAO` fica igualmente fora. O custo vira dinheiro e latência nos turnos em que dispara, em vez de reserva de contexto em todos — inclusive nos que nunca viram um imóvel.

**Alternativa recusada: schema condicional** (um schema maior só nos turnos pós-apresentação). Dois schemas para manter, e divergência entre eles é o defeito que o comentário de `COLUNA_DE_PRECO` existe para impedir. Mais invalidação de cache do prefixo nos turnos que usassem o grande.

**Alternativa recusada: determinístico em código.** A CA-10.1 é sobre referência **natural**, e o lead escreve "o do Campeche", "aquele de 2 quartos", "esse aí não". Cobertura frágil exatamente no critério de aceite.

### D7 — O modelo devolve ordinal, nunca UUID

Ele recebe os imóveis numerados — `1. Apartamento na Trindade, R$ 380 mil` — e devolve, por ordinal, a reação e o motivo.

**É a disciplina da TEC-161 aplicada na entrada.** Um UUID inventado é indistinguível de um verdadeiro até bater no banco; um ordinal fora de 1..N é rejeitado por comparação com um inteiro. O modelo nunca produz identificador que o código não consiga conferir.

### D8 — A chamada dispara no máximo uma vez por apresentação

O gatilho é existirem linhas com `reacao_lead IS NULL` nesta conversa, e a chamada **sempre as resolve todas**: o imóvel que o lead não mencionou sai `NEUTRO`. `SEM_RESPOSTA` fica para quando uma apresentação nova supera linhas ainda pendentes.

Sem isso, um lead que mudasse de assunto por três turnos pagaria três chamadas.

### D9 — A reação é capturada ANTES da busca do mesmo turno

```
turno começa
  ├─ há linhas pendentes? → reagir() → grava as reações
  ├─ classificar() ─ o laço de tool use roda aqui
  │     └─ a porta de busca lê as exclusões da tabela
  └─ apresenta, e grava as recomendações novas
```

**A alternativa — gravar depois e valer do turno seguinte — quebra o cenário 3.** O lead escreve *"não gostei desses, tem outros?"*: reação e nova busca no **mesmo turno**. Capturando depois, a busca daquele turno não sabe do descarte e devolve mais do mesmo, que é literalmente a dor da história. Não é trade-off; é o caso central quebrado.

**Consequência declarada:** o turno que segue uma apresentação passa a ter duas chamadas ao modelo antes da busca, e três se o desambiguador entrar. A chamada de reação não carrega catálogo nem laço de ferramenta, então deve ser a mais barata das três — mas "deve ser" não é número. Ver a L1.

### D10 — `bairros_excluidos` na forma dobrada

`FiltroDeBusca` ganha `bairros_excluidos: tuple[str, ...] = ()`, dobrada.

**A TEC-160 acabou de pagar caro por essa lição.** `adjacentes_de` comparava região crua contra tabela dobrada, e a metade de bairros da RN-09.3 quase foi para produção desligada — com 1534 testes verdes, porque todos usavam literal já dobrado. Toda comparação de bairro neste sistema é entre formas dobradas, sem exceção.

### D11 — O estado do ajuste é consulta sobre a tabela, não coluna nova

A tabela já guarda `(channel, conversation_key)`, `imovel_id`, `reacao_lead` e `motivo_descarte`. O filtro realimentado é uma consulta sobre ela: sem coluna nova, sem estado duplicado, sem problema de sincronia. O cenário 4 — não repetir os já apresentados — sai da mesma tabela de graça.

A consulta mora em `domain/agente/repositorio.py`, ao lado de `gravar_intencao` e `ler_intencao`. **Quem liga a recomendação ao filtro é `ferramenta_de_busca.py`, e só ele** — a invariante que a TEC-265 escreveu e a TEC-160 respeitou. A busca continua sem saber que recomendação existe.

### D12 — A exclusão sobrevive ao relaxamento, por dois mecanismos com motivos diferentes

O relaxamento da RN-09.3 amplia para bairros adjacentes. O Campeche descartado tem a Lagoa da Conceição como vizinha; sem cuidado, **o relaxamento desfaz a exclusão que o lead acabou de pedir**.

**O `WHERE` exclui sempre, relaxado ou não.** É necessário mesmo sem relaxamento: se o lead pediu "zona sul" e o Campeche foi excluído, o filtro de zona casa o Campeche pelo outro lado do `OR`. Só a condição de exclusão, em `AND`, o segura.

**E `alargar` também subtrai os excluídos dos adjacentes.** Não é redundância: sem isso, `relaxou_bairro` sairia `True` num relaxamento cujo único bairro novo era um excluído — e o lead ouviria *"incluí bairros vizinhos"* tendo recebido zero bairro novo. É a classe de mentira que a revisão final da TEC-160 pegou em `relaxou_bairro=bool(adjacentes)`.

Dito de outro jeito: **o `WHERE` garante que o imóvel excluído não volta; o `alargar` garante que o aviso não mente.** Um protege o lead do resultado, o outro da frase.

**Esta decisão só apareceu porque os dois avisos ficaram separados** (ver a D16). Enquanto eram uma mensagem composta, a interação estava escondida atrás da redação.

### D13 — `motivo_descarte` guarda a CATEGORIA, não a frase do lead

`motivo_descarte` recebe um de `DISTANCIA`, `PRECO`, `TAMANHO`, `OUTRO` — não *"achei muito longe do meu trabalho"*.

**A regra exige isso, e o SRS já aponta para lá.** A RN-10.4 conta "dois descartes **por distância**", o que só é computável se o motivo for comparável; e a observação do campo no modelo de dados é literalmente *"Realimenta o filtro"*, que texto livre não faz. Quem categoriza é a chamada de reação — o modelo lê "muito longe" e devolve `DISTANCIA` —, e o código conta.

**A frase do lead não se perde:** ela está na mensagem, que a linha do tempo já guarda. Duplicá-la aqui criaria uma segunda cópia que envelhece sozinha, e o campo passaria a ter dois propósitos incompatíveis — ser lido por humano e ser contado por código.

`varchar(80)` fica como o SRS escreveu, com folga enorme para um enum de quatro valores. O tipo não muda; o que a emenda declara é o **domínio**.

### D14 — O pedido explícito levanta a exclusão

Se o lead nomear um bairro excluído num turno seguinte, ele sai da exclusão para aquela busca. Exclusão é inferência nossa a partir de dois descartes; nomear o bairro é declaração dele, e **declaração vence inferência**.

### D15 — O aviso do ajuste é mensagem própria, nomeia os bairros, e sai quando nasce ou muda

`TEXTO_DO_FILTRO_AJUSTADO` e `KIND_DO_FILTRO_AJUSTADO = "filtro_ajustado"`.

**Mensagem própria** pelo mesmo motivo do aviso da TEC-160: no caminho de apresentação a prosa vira prefixo da legenda e `legenda_de` corta o prefixo antes da ficha. Aviso que some em silêncio quebra "nunca silencioso" justamente no turno em que ele existe.

**Ordem no turno:** identificação → ajuste → ampliação → até 3 fichas. Ordem narrativa: quem fala, o que fiz com o que você me disse, o que ainda precisei esticar, o resultado. O ajuste vem antes da ampliação porque é resposta ao lead, e a ampliação é iniciativa nossa.

**Nomeia os bairros, e aqui divirjo da D11 da TEC-160 de propósito.** Lá os bairros eram escolha nossa, tirados de uma tabela, e a lista podia ter quatro. Aqui são os bairros que **o lead descartou** — dois ou três — e nomeá-los é a confirmação de que ele foi ouvido. *"Tirei o Campeche da busca, que voce descartou"* faz o trabalho que *"ajustei o filtro"* não faz.

**Sai quando nasce ou muda, não em toda busca.** "Sempre informado" lido como "em toda busca" viraria a mesma frase repetida enquanto a exclusão valesse — ruído que ensina o lead a ignorar o aviso.

### D16 — O aviso de ampliação da TEC-160 fica intocado

O desenho considerou fundir os dois avisos determinísticos numa mensagem composta — "o que mudou na busca" — que manteria a RN-04.2 sem emenda. **Recusado por decisão do mantenedor:** a TEC-160 foi revisada e mergeada dias atrás, e reabrir aquele código para absorver outro aviso troca risco novo por elegância.

As três variantes do aviso de ampliação, o kind `criterio_ampliado` e a lógica que as escolhe ficam exatamente como estão.

**Duas consequências, e a segunda é um ganho.** A primeira: o pior caso passa a ter três mensagens de texto, e a RN-04.2 precisa da emenda E-03. A segunda: com os avisos separados, a interação entre exclusão e relaxamento ficou visível — é a D12, e ela não teria aparecido se as duas frases estivessem fundidas numa redação só.

### D17 — O `score` chega ao turno pela porta, não pelo `tool_result`

**Encontrado ao escrever o plano, e ele derruba a D4 se não for resolvido.**

`score_match` é `NOT NULL`, e a D4 justifica o `motivo_match` idêntico entre imóveis dizendo que *"o que distingue os imóveis é o `score_match`"*. Mas `_candidato_serializavel` **não expõe `score`**: a D7 da TEC-265 o removeu de propósito — *"`score` no prompt convida o modelo a dizer '97% de compatibilidade' ao lead — dado inventado com aparência de número"*. O turno só vê o que passou pelo `tool_result`, e ali não há score.

Gravar `0.0` em toda linha tornaria a coluna decorativa **e a D4 falsa**: sem score, nada distingue os imóveis de uma recomendação, e o motivo idêntico deixaria de ser aceitável.

**Recusado: passar o `score` pelo `tool_result`.** Desfaria a D7 da TEC-265 pelo motivo exato que ela nomeia.

**A solução:** `porta_de_busca` é uma closure criada **por turno** — `porta_de_busca(session_factory, embedador=embedar)` é chamada dentro do turno, e o objeto morre com ele. A porta guarda os scores da última busca num dicionário capturado, por `imovel_id`, e o turno o lê na hora de gravar. O score nunca entra no contexto do modelo, e a coluna recebe o número real.

**Por que isso não é estado escondido perigoso:** a closure é por turno, não global; dois turnos concorrentes têm portas distintas. E o turno já depende da porta para buscar — não há acoplamento novo, só um valor a mais atravessando um canal que já existe.

**Consequência declarada:** a porta passa a ter estado, o que ela não tinha. O teste que a cobre precisa afirmar que duas portas distintas não compartilham scores, senão a próxima card que a tornar reutilizável introduz vazamento entre conversas sem ninguém notar.

## Os quatro cenários do Gherkin

| Cenário da card | Onde é verificado |
|---|---|
| 1 — Resolver referência natural ("gostei do segundo") | Integração, peça B |
| 2 — Registrar o motivo do match e o momento | Integração, peça A |
| 3 — Descartes realimentam o filtro, e o lead é informado | Integração + turno, peça C |
| 4 — "Tem mais alguma coisa?" não repete nem descarta | Integração, peças A e B |

## O que a card entrega

1. Migration `0022_recomendacoes.py` e o modelo `Recomendacao`.
2. `_apresentar` grava uma linha por ficha, **antes** da entrega.
3. Os critérios da busca no `tool_result` (um campo por busca) e a renderização do `motivo_match`.
4. `SISTEMA_DA_REACAO`, o schema da reação, e `classificador.reagir`.
5. A gravação das reações por ordinal, e a resolução para `imovel_id`.
6. `FiltroDeBusca.bairros_excluidos`, a condição no `WHERE`, e a subtração em `alargar`.
7. A consulta de exclusão em `domain/agente/repositorio.py`, ligada por `ferramenta_de_busca.py`.
8. `TEXTO_DO_FILTRO_AJUSTADO`, `KIND_DO_FILTRO_AJUSTADO` e o envio.
9. As três emendas ao SRS, e as três linhas no índice.

## Testes

| Onde | O quê |
|---|---|
| Unit | a frase do `motivo_match`, renderizada dos critérios |
| Unit | a regra dos dois descartes, pura, sobre uma lista de recomendações |
| Unit | ordinal → `imovel_id`, incluindo **ordinal fora de faixa não derruba os outros** |
| Unit | o aviso do ajuste nomeia os bairros, é ASCII e não tem número |
| Integração | o `UNIQUE` impede a mesma recomendação duas vezes na conversa |
| Integração | `_apresentar` grava uma linha por ficha, antes da entrega (a L1 da TEC-162) |
| Integração | **cenário 1**: "gostei do segundo" marca o imóvel certo com interesse |
| Integração | **cenário 2**: a recomendação registra motivo do match e momento |
| Integração | **cenário 3**: dois descartes por distância restringem o bairro, e o lead é informado |
| Integração | **cenário 4**: "tem mais alguma coisa?" não repete nem descarta os anteriores |
| Integração | **a exclusão sobrevive ao relaxamento** — imóvel em bairro excluído não volta por adjacência |
| Integração | e `relaxou_bairro` sai `False` quando o único adjacente era excluído |
| Integração | pedido explícito do bairro levanta a exclusão |
| Turno | ordem: identificação → ajuste → ampliação → fichas |
| Turno | o aviso do ajuste **não repete** enquanto não muda |
| Turno | falha de `reagir()` não derruba o turno |
| Orçamento | `margem_do_orcamento` continua em 6,2 — nada desta card entra no prompt principal |

**Degradações, todas no molde de "derrubar a dimensão, não o turno":**

| Falha | O que acontece |
|---|---|
| `reagir()` falha | Log; linhas continuam pendentes; sem ajuste; o turno segue. O lead perde o ajuste, não o atendimento. |
| Ordinal fora de 1..N | Aquela reação é descartada e logada; **as outras do mesmo turno valem**. |
| `motivo_descarte` ilegível | Vale como `DESCARTE`, mas **não conta** para o limiar de distância — sem motivo, contar estreitaria a busca pela razão errada. |

**`recomendacoes` ENTRA em `TABELAS` no conftest.** Ao contrário de `bairros_adjacentes`, que é dado de referência, esta é escrita pelos testes: sem o `TRUNCATE`, as recomendações de um teste viram histórico do próximo e o ajuste dispara onde ninguém pediu — mesmo raciocínio que o conftest já escreveu para `imoveis` e `lead_score_audit`. **Custo declarado: ~1.540 `TRUNCATE ... CASCADE` a mais por suíte**, e essa contenção de lock é a causa conhecida dos flakes desta máquina. A alternativa é teste que passa sozinho e falha em conjunto, que é pior.

**Basenames únicos** entre `tests/unit/` e `tests/integration/`: `test_recomendacao_regras.py` (unit) e `test_recomendacao_e_reacao.py` (integração).

## As emendas ao SRS

**`RN-10.3` — Emenda E-01 (TEC-163, 12/09/2026).** Declara que `conversa_id UUID FK → Conversa` vira o par `(channel, conversation_key)`, porque `Conversa` não é entidade neste sistema e nunca foi — `conversation_summaries`, `lead_qualification` e `conversation_intent` já o fazem, e a emenda está três tabelas atrasada. Declara também que `motivo_match` é **por busca**, idêntico entre os imóveis da mesma apresentação, e que o `UNIQUE (channel, conversation_key, imovel_id)` torna o "não repetir" garantia de schema.

**`RN-10.4` — Emenda E-01 (TEC-163, 12/09/2026).** Fixa o que a regra deixa em aberto: limiar de **dois** descartes por distância; "restringir o bairro" é excluir das buscas seguintes os bairros dos imóveis descartados; `motivo_descarte` guarda a **categoria** (`DISTANCIA`, `PRECO`, `TAMANHO`, `OUTRO`) e não a frase do lead, porque "realimenta o filtro" exige valor comparável; descarte sem categoria legível **não conta**; **pedido explícito levanta a exclusão**; *"sempre informado"* é **quando nasce ou muda**; e **a exclusão sobrevive ao relaxamento da RN-09.3**.

**`RN-04.2` — Emenda E-03 (TEC-163, 12/09/2026).** O teto de mensagens de **texto** sobe de 2 para até **3**. O teto existe contra parede de texto, e três avisos determinísticos curtos — identificação, ajuste, ampliação — não são isso. **Declarado junto:** o teto fica empatado de novo. A quarta trilha não deve pedir a E-04; deve agrupar os avisos determinísticos num mecanismo só. Esta emenda é a última barata.

## Lacunas conhecidas

### L1 — A latência do turno pós-apresentação não está medida

Duas chamadas antes da busca, três com o desambiguador. O plano mede a chamada de reação e registra o número; se ela empurrar o pior caso para perto do `job_timeout`, isso vira lacuna com número em vez de frase de conforto.

### L2 — O teto da RN-04.2 fica empatado em três

Mesma lacuna que a L5 da TEC-160, um degrau acima. A diferença é que agora está escrito o que fazer: a próxima trilha agrupa, não pede a E-04.

### L3 — `motivo_match` é idêntico entre imóveis da mesma busca

Ver a D4. Aceitável para medir conversão; insuficiente se algum dia alguém quiser saber por que **aquele** imóvel, e não o vizinho na mesma lista.

### L4 — Só o bairro se realimenta

A RN-10.4 autoriza bairro. Dois descartes por preço ou por tamanho não ajustam nada. Generalizar exige regra própria por dimensão e emenda — escopo bem maior que esta card.

### L5 — `SEM_RESPOSTA` depende de uma apresentação nova

Linhas pendentes só viram `SEM_RESPOSTA` quando outra apresentação as supera. Conversa que termina logo depois de uma apresentação deixa linhas `NULL` para sempre — o que é honesto (ninguém sabe se o lead viu), mas quem for contar conversão precisa saber que `NULL` e `SEM_RESPOSTA` significam coisas diferentes.

### L6 — A emenda do par não corrige as três tabelas anteriores

A E-01 da RN-10.3 declara a divergência para o sistema, mas as fichas de `conversation_summaries`, `lead_qualification` e `conversation_intent` na seção 8 continuam dizendo `conversa_id`. Corrigi-las é edição do modelo de dados que esta card não tem motivo para fazer, e o SRS só se emenda pela regra que a card toca.

## Fora de escopo

- Exibição da taxa de conversão por imóvel no dashboard — a própria card exclui (E8).
- Realimentação de dimensões que não sejam bairro (L4).
- Refatorar o aviso de ampliação da TEC-160 (D16).
- Corrigir as fichas das três tabelas anteriores no modelo de dados do SRS (L6).

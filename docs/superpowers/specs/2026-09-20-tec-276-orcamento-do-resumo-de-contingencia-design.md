# TEC-276 — O resumo de contingência mostra quantos imóveis couberem

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-276](https://eduardodurieuxlopes.atlassian.net/browse/TEC-276) — épico TEC-173
**Branch:** `feat/tec-276-orcamento-do-resumo-de-contingencia`
**Origem:** RF-15, RN-15.2 (SRS v1.0); consequência da TEC-176.

## Objetivo

Fazer o resumo de contingência usar os 1.500 caracteres que tem, em vez de gastar 2 imóveis de orçamento dimensionado para um pior caso que nenhum lead produz.

## A medição que a card pediu, refeita — e ela muda o desenho

Três medições, três resultados. O comentário no código diz uma coisa, a revisão final da TEC-176 mediu outra, e a reconstrução desta card mediu uma terceira:

| combinação | tabela no código | medido nesta card |
| --- | --- | --- |
| `imoveis=2, lista=1` | 1452 (48 de folga) | **1425** (75 de folga) |
| `imoveis=2, lista=2` | estoura (1520) | **cabe** (1493) |
| `imoveis=3, lista=1` | estoura (1529) | estoura (1503) |

A discordância é o problema que a card existe para fechar: o comentário pede que alguém re-derive os tetos, e três pessoas derivam três números. Nenhum dos três é confiável enquanto a construção do pior caso viver em prosa.

**E a medição matou a solução que a card imaginava.** As regras de negócio dizem "os tetos são **reajustados** a partir do número que a medição produzir". O número é **2** — o mesmo de hoje, porque 3 imóveis estouram por **3 caracteres**. Reajustar o teto fixo entregaria a reprodutibilidade e nada mais; o terceiro critério de aceite ("um lead típico vê mais do que dois imóveis") seria impossível de satisfazer.

O que o mesmo experimento mostrou do outro lado:

| lead típico (região curta, 1 recusado, 1 sem resposta) | tamanho | folga |
| --- | --- | --- |
| 2 imóveis (hoje) | 923 | **577** |
| 10 imóveis | 1228 | 272 |
| 15 imóveis | 1418 | 82 |
| 17 imóveis (o que a implementação entrega) | 1494 | 6 |
| 20 imóveis | estoura | — |

**O corretor perde 577 caracteres de contexto no dia ruim para pagar uma margem que só o pior caso do banco usa.**

## D1 — A lista de imóveis deixa de ter teto e passa a ter orçamento

`montar` monta o texto com `n` imóveis e mede o resultado; sobe `n` enquanto couber nos 1.500. O maior que coube é o que sai.

Isso troca a garantia de lugar, e é a parte importante: **"cabe por construção" deixa de depender de uma tabela e passa a ser propriedade do algoritmo.** Hoje a garantia é "alguém mediu um pior caso e escolheu 2"; ela morre em silêncio no dia em que alguém acrescentar uma palavra a um marcador. Depois desta card, a garantia é "o texto que sai foi medido antes de sair" — e continua valendo qualquer que seja o texto dos blocos.

O pior caso degrada sozinho para 2 imóveis (1446, com 54 de folga), sem ninguém dimensionar nada. O lead típico passa a ver **17** — medido pelo caminho novo depois de implementado, e não estimado antes.

**A busca sobe do zero, e não desce do topo.** Medido: uma montagem custa 0,011 ms (10 imóveis) a 0,084 ms (200). Descendo do topo, o custo acompanha o tamanho do dossiê — 200 imóveis são ~17 ms, quase todos gastos em candidatos que estouram. Subindo, o custo acompanha o **orçamento**: uma linha de imóvel não tem menos de ~30 caracteres, então nunca há mais de ~40 candidatos, independentemente do dossiê. É ~1 ms no pior caso, e a conta não piora quando o catálogo crescer.

A monotonicidade é o que autoriza parar no primeiro que estoura: cada imóvel a mais só acrescenta caracteres.

## D2 — `TETO_POR_LISTA_DE_ATENCAO` continua fixo em 1

As listas de atenção não entram no orçamento. Não é esquecimento: distribuir a folga entre imóveis e pontos de atenção exige decidir qual dos dois o corretor prefere ver, e isso é decisão de produto que a card não toma. A história da card é sobre imóveis ("quero que o resumo me mostre tantos imóveis quanto couberem"), e é o que esta implementa.

Fica declarado como lacuna: mesmo com o orçamento em uso, o que sobra depois dos imóveis poderia virar um segundo campo recusado em vez de mais um imóvel.

## D3 — A medição vira teste, e o comentário para de repetir números

A tabela de prosa sai do código. No lugar entram dois testes:

* **o pior caso do banco cabe** — dossiê com todo campo no máximo que a coluna aceita, 40 imóveis, 50 itens de 32 caracteres por lista de atenção; `montar` não levanta e o texto cabe nos 1.500;
* **o lead típico vê mais de dois imóveis** — e o texto cabe.

O pior caso é **construído a partir dos tetos que o próprio módulo já deriva** (`TETO_REGIAO`, `TETO_CANAL`, `TETO_CONVERSA`, `TETO_CODIGO` e os de enum), e não de literais escolhidos à mão. É isso que torna a medição reproduzível: quem mudar `LeadQualification.regiao` para `String(200)` muda o teste junto, sem editar o teste.

O comentário no código passa a citar os testes. Nenhum número de folga fica escrito em prosa — foi o que envelheceu três vezes.

## D4 — O que não muda

* **O limite de 1.500 caracteres** (RN-15.2) e o conteúdo dos seis blocos — fora do escopo pela card.
* **Os tetos de campo de valor único** (`TETO_REGIAO`, `TETO_INTENCAO`, …) ficam como estão: eles cortam campo por campo, e sem eles um `regiao` de 120 caracteres entraria inteiro mesmo quando o orçamento estivesse apertado. O orçamento decide **quantos imóveis**, não o tamanho de cada campo.
* **`imoveis()` em `dossie.py`** mantém a assinatura com `teto`: é o que o orçamento vai variar.
* **O modo redigido** (`renderizar`) não tem teto nenhum e continua sem — o modelo recebe o dossiê inteiro.

## Testes

* O pior caso do banco cabe e não levanta.
* O lead típico vê mais de dois imóveis — a asserta é contra o número **2**, não contra 17: prender 17 faria o teste reprovar na primeira vez que alguém acrescentar uma palavra a um bloco, que é exatamente o acoplamento que esta card remove.
* Um dossiê com 200 imóveis não estoura nem demora — a busca é limitada pelo orçamento.
* Um dossiê sem imóvel nenhum continua montando.
* Dossiê cujo pior caso não cabe nem com zero imóveis continua levantando `ResumoAcimaDoLimite` — a rede de segurança de `gerar_resumo` depende disso.
* Os imóveis mostrados continuam sendo os **mais recentes** (Important 3 da TEC-176): o orçamento muda quantos, não quais.

## O que este desenho não entrega

A folga que sobra depois dos imóveis continua sem uso (D2). E o resumo de contingência continua sendo o modo ruim: mais imóveis visíveis não o tornam redigido.

# TEC-225 — A estimativa de tokens passa a enxergar densidade

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-225](https://eduardodurieuxlopes.atlassian.net/browse/TEC-225)
**Branch:** `feat/tec-225-estimativa-ciente-de-densidade`
**Origem:** revisão final da branch `feat/tec-127-janela-contexto`.

## Objetivo

Fazer a estimativa barata de `_contar_se_valer` parar de subcontar. Hoje ela é `len/4` — uma constante de caracteres por token **do inglês** — e é ela que decide se o contexto cabe no teto quando fica abaixo do limiar.

## O que foi medido, e por que muda o tamanho da card

Medido em 20/09/2026 com o contador que o próprio repo usa (`ContadorAnthropic`, `messages.count_tokens`, `claude-sonnet-5`). A razão é **marginal** — medida pela inclinação entre um texto e o mesmo texto oito vezes —, o que cancela a sobrecarga fixa da chamada:

| conteúdo | chars/token | bytes/token |
| --- | --- | --- |
| **português sem acento** | **2,34** | 2,34 |
| **português acentuado** | **2,38** | 2,45 |
| inglês | 3,15 | 3,15 |
| URL | 1,85 | 1,85 |
| base64 | ~0,99 | ~0,99 |
| emoji | 0,35 | 1,41 |

### A card subestima o problema, e a docstring do limiar está errada

`Settings.limiar_de_contagem_efetivo` afirma hoje:

> português acentuado (~3.2-3.7 chars/token) fica coberto com folga

**Medido: 2,38.** O intervalo 3,2–3,7 é o do **inglês** (3,15 medido), não o do português. A card herdou essa afirmação e classifica o português como "não escapa, coberto pela margem".

A razão de segurança do limiar em 0,6 é 2,4 chars/token. Com o português real em 2,34–2,38, **a folga é de 2,6% — e não folga nenhuma.** A língua principal do produto já está na borda do escape, numa faixa estreita mas real de tamanhos de contexto.

### O critério de escape, e o que ele diz sobre cada conteúdo

Um conteúdo escapa da contagem real quando a estimativa diz "cabe" e o real estoura. Isso acontece exatamente quando **`estimativa/real` fica abaixo da fração do limiar (0,6)**.

Medido, com a estimativa de hoje e a proposta abaixo:

| conteúdo | `hoje/real` | `proposto/real` | escapa hoje? | escapa depois? |
| --- | --- | --- | --- | --- |
| português | 0,59 | **1,02** | **sim** | não |
| português acentuado | 0,60 | **1,23** | na borda | não |
| inglês | 0,76 | 1,32 | não | não |
| emoji puro | 0,09 | **1,06** | **sim** | não |
| uma dúzia de URLs | 0,46 | **0,80** | **sim** | não |
| misto realista | 0,53 | **1,15** | **sim** | não |
| base64 | 0,25 | 0,43 | **sim** | **sim** |

O português em **0,59 contra o corte de 0,60** confirma por um segundo caminho, independente da aritmética, que a margem de hoje é ilusória.

## Decisões

### D1 — O divisor errado é a causa raiz

Trocar `len/4` por uma base de **2,3 caracteres por token**, que é o português medido.

Isso sozinho tira português, inglês e URL da lista de escapes: a condição de escape deixa de ser "conteúdo abaixo de 2,4 chars/token" e passa a ser "abaixo de 1,38", e URL roda a 1,85.

**Não é afinação de constante, é conserto de premissa.** O 4 nunca descreveu o texto que este produto processa.

### D2 — O termo de densidade cobre o emoji

A fórmula passa a ser:

```
estimativa = caracteres_ascii / 2,3 + caracteres_nao_ascii * 3
```

O `3` é o emoji medido: cada emoji é **um** caractere Python e custa cerca de 2,9 tokens (0,35 chars/token). Cobrá-lo por caractere é o que o `len/4` nunca fez — para `len`, um emoji e uma vogal valem igual.

O acento do português paga esse mesmo preço de 3, o que superestima um pouco (1,23 contra 1,02 do texto sem acento). É superestimar, não subcontar, e a D3 mostra que a folga de latência aguenta.

### D3 — O ganho de latência não se perde, e isso é medido

O limiar é 6.564 tokens. Sob a fórmula nova, ele só é alcançado por volta de **15.100 caracteres** — contra 26.256 hoje.

Medido sobre o corpus de eval do repo (154 falas de lead em 56 conversas): fala mediana de 61 caracteres, p90 de 93. Somando a parte fixa da estimativa (`SISTEMA` de 168 caracteres, resumo no teto de 1.500 da RN-15.2, estado de ~400) e supondo resposta do agente três vezes a fala do lead:

| janela | caracteres | estimativa nova | folga até o limiar |
| --- | --- | --- | --- |
| 20 falas, mediana | 4.508 | 1.960 | 3,3× |
| 20 falas, p90 | 5.788 | 2.517 | 2,6× |
| 40 falas, mediana | 6.948 | 3.021 | 2,2× |
| **40 falas, p90** | **9.508** | **4.134** | **1,6×** |

**O pior caso realista fica 1,6× abaixo do limiar.** O turno normal continua não pagando round trip nenhum, que é o ganho que motivou a estimativa existir.

### D4 — Base64 continua escapando, e isso é declarado e não escondido

Com a fórmula nova, base64 fica em 0,43 — abaixo do corte de 0,60. Ele é ASCII puro, então nenhum termo de densidade de codepoint o alcança; pegá-lo exigiria uma heurística de "sequência longa sem espaço", que é detector novo com falso-positivo próprio (uma URL longa também é sequência sem espaço).

**Fica como risco remanescente, documentado no mesmo lugar onde o risco de hoje está documentado.** A card não o pede: o critério de pronto dela nomeia emoji e URLs, e os dois ficam cobertos.

A melhora ainda assim é real: de 0,25 para 0,43.

### D5 — O segundo item da card NÃO está obsoleto, e o `headroom` sobe para 1.600

> **Esta decisão substitui uma versão anterior deste desenho, que declarava o segundo item da card obsoleto. Aquela versão estava errada, e o parágrafo abaixo registra por quê — não por rigor de processo, mas porque o erro é instrutivo: eu confiei em dois testes sem conferir com que régua eles mediam.**

O que a primeira versão argumentou: que o `headroom` não era mais "400 e um chute", porque subira quatro vezes com razão escrita (TEC-145, TEC-250, TEC-257, TEC-265), tinha 96 linhas de comentário decompondo cinco parcelas, e era coberto por dois testes — `test_diferenca_entre_o_contado_e_o_enviado` e `test_a_margem_do_orcamento_do_prompt_e_deliberada`.

**O furo:** aqueles dois testes medem as parcelas com `len/4` — o mesmo proxy que esta card acabou de derrubar. Eles passam porque a régua é a mesma dos dois lados, não porque a reserva cubra o que precisa cobrir.

Medido em 20/09/2026, cada parcela contra o contador real (`ContadorAnthropic`, claude-sonnet-5):

| parcela | `len/4` | contador real |
| --- | --- | --- |
| − `montagem.SISTEMA` (contado, não enviado) | −42,0 | −77,0 |
| + `SISTEMA_DO_AGENTE` (campo `system=`) | 305,5 | 541,0 |
| + schema compilado | 372,8 | 798,0 |
| + rótulos de `montar_prompt` | 19,2 | 41,0 |
| + ferramenta de busca (`tools=`) | 131,2 | 242,0 |
| **= subcontagem** | **786,8** | **1.545,0** |

**A reserva de 1.060 é 485 tokens menor que a lacuna real.** Um contexto medido no teto efetivo de 10.940 envia cerca de 12.485 tokens — e o teto de 12.000 da RN-02.5 é critério de aceite.

**Decisão: `contexto_headroom_de_tokens` passa de 1.060 para 1.600**, cobrindo os 1.545 medidos com 55 tokens de folga. É a primeira vez que esse número sai de uma medição com o contador real, e não de aritmética sobre o proxy.

**O custo, declarado:** o teto efetivo cai de 10.940 para 10.400 — 540 tokens, cerca de 1.240 caracteres de conversa a menos por chamada. O CLAUDE.md avisa que essa reserva sai do mesmo contexto que guarda a conversa do lead, e aqui ela sai mesmo. A alternativa era continuar estourando o teto em silêncio.

**O que esta card NÃO faz:** trocar o proxy de `_decomposicao` pela fórmula nova. Os dois testes de orçamento continuam medindo em unidades de `len/4`, e passam a ser o que de fato são — um alarme contra **crescimento do prompt**, não uma validação da reserva. A prosa deles tem de dizer isso, porque hoje ela afirma medir "o mesmo proxy do módulo de montagem", o que deixou de ser verdade.

### D5b — O que era a D5 antiga, e continua valendo

A card manda, como segundo item, conferir o `headroom`, dizendo que ele está em **400 tokens** e que é "um chute fundamentado, não uma medição". E declara dependência da TEC-134, que "é quem define a forma real da requisição".

Nada disso vale mais:

- O `headroom` está em **1.060**, depois de quatro subidas registradas (400→800 na TEC-145, →850 na TEC-250, →880 na TEC-257, →1.060 na TEC-265), cada uma com a razão escrita.
- O campo tem hoje **96 linhas de comentário** decompondo as cinco parcelas que a reserva cobre.
- A TEC-134 **existe**: `ClassificadorAnthropic._chamar` monta `system=` separado com `cache_control`, array de mensagens, schema compilado e `tools=`.
- A diferença entre o contado e o enviado **já é medida por teste** — `test_diferenca_entre_o_contado_e_o_enviado` e `test_a_margem_do_orcamento_do_prompt_e_deliberada`.

Tudo isso continua verdade, e é por isso que a D5 acima **não** refaz a decomposição nem reabre o histórico: o que faltava não era decompor a reserva, era medi-la com o contador certo. O trabalho das quatro cards anteriores fica de pé; o que muda é o valor, e agora com medição em vez de aritmética sobre proxy.

### D6 — O caminho sem modelo está pior que o normal, e o desenho só viu isso ao ler o código

`_estimar_pessimista` existe para o modo sem modelo — o caminho de estouro de deadline, onde **não há limiar** e a estimativa é a palavra final. A docstring dele diz, com todas as letras, que ele "corrige para errar para cima", porque "devolver contexto acima do teto não é" a direção segura do erro.

Ele é construído sobre os **dois** números errados:

```python
_CHARS_POR_TOKEN_NO_PIOR_CASO = 3.2
_FATOR_PESSIMISTA = 4 / _CHARS_POR_TOKEN_NO_PIOR_CASO   # = 1,25
```

O `4` é o divisor do inglês; o `3,2` é o "pior caso do português" que a medição derrubou. O efeito líquido é `len/3,2`, contra um português real de 2,34.

**Medido: o modo pessimista subconta o português em 27%** (razão 0,73). O caminho que existe para errar para cima erra para baixo, e é justamente aquele onde nada corrige depois.

O conserto: o fator passa a ser derivado do **pior caso plausível medido sob a fórmula nova**, que é a URL em 0,80 — base64 fica de fora pela D4. `1 / 0,80 = 1,25`.

**O número não muda; a derivação muda inteira.** Hoje 1,25 sai de dois valores errados que se cancelam por acaso; depois, sai de uma razão medida. E o comentário tem de dizer isso, porque um `1,25` que parece o mesmo mas significa outra coisa é o tipo de constante que envelhece em silêncio.

### D7 — A prosa que passa a mentir

- **`Settings.limiar_de_contagem_efetivo`**: o número do português (3,2–3,7 → 2,34–2,38), a conclusão de que ele "fica coberto com folga", e o parágrafo que declara emoji e base64 como risco aceito "até existir um estimador que leve densidade de caracteres não-ASCII em conta" — este desenho é esse estimador.
- **`_contar_se_valer` e `_estimar`**: a docstring cita `len/4` e o mesmo intervalo do português.
- **`_CHARS_POR_TOKEN_NO_PIOR_CASO` e `_FATOR_PESSIMISTA`**: o comentário de 12 linhas que os acompanha declara o piso de 3,2 e repete a lista de riscos do limiar. Muda inteiro com a D6.
- **`test_conteudo_curto_em_caracteres_nunca_aciona_a_contagem_real`**: a própria nota dele manda invertê-lo em vez de consertá-lo quando este dia chegar. **É substituído, não deletado** — a card exige.
- **Referência cruzada morta:** a docstring de `test_limiar_de_contagem_cede_a_vez_para_a_contagem_real` cita um `test_limiar_nao_protege_conteudo_denso_em_emoji` "logo abaixo", e esse teste não existe com esse nome.

## Testes

1. **Emoji aciona a contagem real** — critério de pronto da card.
2. **Uma dúzia de URLs aciona a contagem real** — critério de pronto da card.
3. **Português de tamanho moderado continua NÃO pagando o round trip** — o critério que protege a latência.
4. **A fórmula não subconta**, exercitada por conteúdo de cada faixa de densidade, com os valores medidos aqui como referência.
5. **O teste da lacuna é substituído**: o que hoje afirma que conteúdo denso nunca aciona a contagem passa a afirmar que aciona.
6. O backstop de `estimativa >= teto` continua funcionando (ele só é alcançável com `CONTEXTO_LIMIAR_DE_CONTAGEM` acima do teto, e o teste que o exercita já faz isso).
7. **O modo sem modelo erra para cima** (D6): a estimativa pessimista de um texto em português fica **acima** da contagem real, não abaixo. O teste que existe hoje — `test_a_estimativa_sem_modelo_supoe_o_piso_de_caracteres_por_token` — prende a razão contra o piso de 3,2 e passa a prender contra o número medido.

## Fora de escopo

- Cobrir base64 (D4).
- **Trocar o proxy `len/4` de `_decomposicao`** pela fórmula nova, e recalibrar a partir dali os dois tetos dos testes de orçamento. É a correção na raiz, e é card própria: mexe na maquinaria que o CLAUDE.md cerca de ritual, e o `headroom` medido da D5 já fecha o buraco sem ela.
- Mexer na fração 0,6 do limiar: com a estimativa consertada, ela passa a fazer o que promete.
- Trocar o contador real por tokenizador local. O repo proíbe explicitamente, e com razão: o teto é critério de aceite.

## O que a mudança do `headroom` não quebra, conferido

O limiar deriva do teto efetivo, então ele cai junto: de 6.564 para 6.240. Os três testes da D1/D2 sobrevivem com a mesma folga qualitativa:

| teste | estimativa | limiar novo | resultado |
| --- | --- | --- | --- |
| emoji aciona | 7.283 | 6.240 | aciona ✅ |
| URLs acionam | 7.350 | 6.240 | aciona ✅ |
| português moderado não paga | 3.633 | 6.240 | não aciona ✅ |

E os três testes de `config.py` continuam passando: `teto_efetivo == teto − headroom` é identidade; `subcontagem(786,8) < 793` não depende do `headroom`; `subcontagem < headroom × 0,75` fica com mais folga (1.200 contra 786,8), não menos.

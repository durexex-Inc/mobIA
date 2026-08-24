# TEC-127 — Montar a janela de contexto enviada ao modelo

- **Data:** 2026-08-24
- **Jira:** [TEC-127](https://eduardodurieuxlopes.atlassian.net/browse/TEC-127) · Épico [TEC-123](https://eduardodurieuxlopes.atlassian.net/browse/TEC-123)
- **Origem:** RF-02, RN-02.2, RN-02.4, RN-02.5 (SRS v1.0)
- **Status:** aprovado, aguardando plano de implementação

## Problema

Marina volta dois dias depois e quer continuar de onde parou, sem repetir o
orçamento e a região que já informou. Para isso o modelo precisa receber, a cada
turno, três coisas: as mensagens recentes na íntegra, um resumo do que veio
antes, e o estado estruturado de qualificação já conhecido.

Nada disso existe. A TEC-126 deixou `messages` como linha do tempo consultável e
o índice `ix_messages_timeline` construído exatamente para a busca das mais
recentes por conversa — mas não há resumo, não há estado, e **não há nenhuma
chamada de modelo no projeto**. A TEC-122 chegou a deixar um teste que asserta
que a rota de ingestão não tem nada de LLM. Esta história é onde essa fronteira
muda de lugar.

É também o que destrava o resto do produto: os épicos TEC-133 (roteamento por
intenção), TEC-144 (qualificação e score) e TEC-155 (catálogo e busca) todos
dependem de existir uma janela de contexto montada.

## Abordagem: resumo com marca d'água

O resumo guarda até onde ele cobre. O contexto é sempre `resumo + tudo o que veio
depois da marca, na íntegra`. A regeneração acontece **dentro do turno**, antes
da montagem.

A propriedade que isso compra: **não existe lacuna**. O que ainda não foi
resumido entra literal. O custo: um turno a cada vinte paga uma chamada de modelo
a mais.

### A invariante das vinte

O critério de aceite diz que o prompt contém as vinte mensagens mais recentes na
íntegra. Isso impõe um limite a quanto a marca pode avançar:

> **A marca nunca avança além de deixar vinte mensagens literais.**

Sem essa regra, a regeneração colaria a marca no presente e o turno seguinte a
cada resumo teria uma ou duas mensagens literais — quebrando o critério
exatamente onde ele mais importa.

Então o gatilho é por acúmulo, não por proximidade: quando existem **quarenta**
mensagens depois da marca, a regeneração dobra as vinte mais antigas delas no
resumo e deixa vinte literais. Entre uma regeneração e a próxima o prompt carrega
de vinte a quarenta mensagens na íntegra.

```
60 msgs, marca em 40  →  resumo(1..40) + literais 41..60   (20)
70 msgs, marca em 40  →  resumo(1..40) + literais 41..70   (30)
80 msgs, marca em 40  →  40 literais: dispara
                      →  resumo(1..60) + literais 61..80   (20)
```

"As vinte mais recentes na íntegra" é portanto um **piso**, nunca um teto: o
prompt sempre as contém, às vezes contém mais, e nunca deixa de cobrir nada — o
que está entre a marca e o presente está literal, e o que é anterior à marca está
no resumo.

Alternativas descartadas:

- **Regeneração assíncrona por job ARQ.** Latência constante, sem pico — mas
  entre o gatilho disparar e o job terminar, as mensagens que saíram da janela
  recente não estão em lugar nenhum: nem literais, nem resumidas. O modelo perde
  contexto de forma silenciosa e intermitente, que é a pior forma.
- **Assíncrono com compressão inline só no estouro.** Herda a lacuna do
  assíncrono e ainda assim tem o pico de latência. Duas falhas diferentes para
  depurar quando o contexto sair errado.

## Modelo de dados

Ambas as tabelas são chaveadas por `(channel, conversation_key)` — a mesma chave
denormalizada da TEC-126. `conversations` de primeira classe continua sendo
TEC-129 e TEC-130.

### `conversation_summaries`

| Coluna | Tipo | Nota |
|---|---|---|
| `channel`, `conversation_key` | pk composta | |
| `resumo` | `bytea` | cifrado — ver abaixo |
| `watermark_created_at` | `timestamptz` | até onde o resumo cobre |
| `watermark_message_id` | `uuid` | desempate entre mensagens no mesmo instante |
| `mensagens_cobertas` | `integer` | quantas mensagens o resumo dobrou |
| `modelo` | `varchar(64)` | qual modelo gerou este resumo |
| `updated_at` | `timestamptz` | |

**O resumo é cifrado.** Nenhum critério de aceite pede isso; cai do princípio da
TEC-126. Um resumo destila as mesmas frases que `text_body` guarda — deixá-lo em
claro ao lado de uma coluna cifrada seria manter a fechadura e tirar a porta. AAD
`{channel}:{conversation_key}:resumo`: não há `message_id` aqui, e a amarração
continua impedindo mover ciphertext de uma conversa para outra.

**A marca d'água é um par ordenável, não uma contagem.** Contagem quebra quando
uma linha é apagada ou quando duas mensagens chegam fora de ordem. O par
`(created_at, id)` casa com `ix_messages_timeline (channel, conversation_key,
created_at DESC)`: a busca do que falta resumir vira `WHERE (created_at, id) >
(marca)` e usa o índice direto.

### `lead_qualification`

Os nove campos que a [TEC-145](https://eduardodurieuxlopes.atlassian.net/browse/TEC-145)
já especifica, todos nullable, mais `updated_at`:

`intencao`, `faixa_preco_min`, `faixa_preco_max`, `regiao`, `tipo_imovel`,
`quartos`, `vagas`, `urgencia`, `forma_pagamento`, `tem_imovel_para_vender`.

Esta história **lê** e injeta. Quem escreve é a TEC-145 — que é bloqueada pela
TEC-134, que depende desta. O produtor chega duas histórias depois do consumidor,
e é o mesmo padrão do `MessageRecorder` na TEC-126: a costura nasce pronta e
testada, o escritor pluga depois.

### Por que o resumo é cifrado e o estado não

É uma inconsistência aparente e foi decidida de propósito.

TEC-147 decide quando o lead está qualificado, TEC-150 calcula o score de 0 a
100 e TEC-158 filtra o catálogo por faixa de preço e região. Os três consultam
esses campos em SQL. Cifrar `lead_qualification` mataria isso e forçaria carregar
a tabela inteira para a aplicação a cada filtro.

E são categorias diferentes de dado. A cifra da TEC-126 protege o que a Marina
**escreveu** — a frase, com tudo que ela contém sem querer. `lead_qualification`
guarda o que o sistema **concluiu**: atributos estruturados de um schema fechado,
sem texto livre.

A alternativa honesta, se essa distinção não se sustentar numa revisão de LGPD, é
cifrar e aceitar que a busca da TEC-158 filtre em memória. Melhor decidir isso
agora do que na TEC-150.

## Montagem do contexto

`montar_contexto(channel, conversation_key) -> ContextoMontado`, em
`src/mobia/domain/context/`. Devolve as partes em ordem explícita, não uma string
pronta: quem chama decide como renderizar, mas a ordem pertence ao domínio,
porque é ela que determina o custo.

### A ordem existe por causa do cache

Prompt caching é casamento de prefixo — qualquer byte que muda invalida tudo
depois dele. As partes mudam em ritmos diferentes:

```
sistema   fixo                          ─┐ estável por ~20 turnos
resumo    muda a cada regeneração       ─┘ ← breakpoint de cache
mensagens crescem no fim a cada turno
estado    muda a cada extração (TEC-145 em diante)
```

O estado vai **por último**. Ele parece informação de sistema e a tentação é
colocá-lo no topo — mas aí cada campo extraído invalidaria o resumo e as vinte
mensagens junto. Entre regenerações a lista de mensagens só cresce no fim, então
um breakpoint depois do resumo mantém sistema e resumo quentes por vinte turnos.

Conversa curta não atinge o mínimo cacheável de ~1024 tokens e simplesmente não
cacheia. É aceitável: é também a conversa em que o contexto é barato.

### Contagem de tokens

O teto de 12.000 tokens é medido com `messages.count_tokens` da própria API —
nunca `tiktoken`, nunca heurística de caracteres como fonte de verdade.

Mas é um round trip, e o teto só importa perto dele. Então: estimativa barata
(`len/4`) decide se vale contar, e a contagem real roda apenas quando a
estimativa passa de ~10.000. Turno normal não paga round trip; turno perto do
limite paga um e acerta.

### O laço do estouro

Limitado, nunca `while`:

1. Avança a marca — dobra as mensagens literais mais antigas no resumo. É a mesma
   operação da regeneração, disparada por token em vez de por contagem.
2. Reconta.
3. Ainda estourou? Re-resume o próprio resumo.
4. Reconta.

O passo 1 **pode** violar a invariante das vinte, e é o único lugar onde isso é
permitido. Vinte mensagens que somam mais de 12.000 tokens existem — vinte áudios
transcritos longos chegam lá. Quando o piso e o teto se contradizem, o teto vence:
ele é o limite físico da chamada, o piso é uma preferência de qualidade. O log
`contexto.piso_violado` registra quando isso acontece, porque é sinal de que a
conversa tem um formato que ninguém previu.

No máximo três iterações. Se ainda não couber, descarta as mensagens literais
mais antigas e loga `contexto.truncado` com quantas caíram. Um `while` aqui é um
caminho para gastar dinheiro em círculo com um resumo que não encolhe.

A ordem importa: dobrar mensagem em resumo é perda normal; re-resumir resumo é
perda em cascata. A segunda só acontece quando a primeira não bastou.

## Falha do modelo não derruba o turno

A Marina está esperando. Quando a chamada de resumo falha, o caminho degradado é:
usa o resumo antigo, corta mensagens literais até caber nos 12.000, e loga
`contexto.degradado` com o motivo.

O teto é critério de aceite e não cede. O que cede é a completude — e cede
**ruidosamente**. É a mesma filosofia do `_try_enqueue` da TEC-122 e do
`MessageRecorder` da TEC-126: o caminho principal sobrevive, o efeito secundário
engole a própria falha e grita no log.

## Portas e a primeira dependência de LLM

`ResumidorPort` como `Protocol`, com `ResumidorAnthropic` concreto e um dublê nos
testes. A suíte não toca a rede.

- Dependência nova: `anthropic` no `pyproject.toml`.
- `Settings.anthropic_api_key`, sem default utilizável — mesmo tratamento que a
  TEC-126 deu à chave de cifra, que recusa subir em produção com o valor de
  desenvolvimento.
- `Settings.modelo_resumo`, default `claude-opus-5`.

**O resumo roda no modelo padrão do projeto, sem rebaixamento.** A tentação era
usar Haiku 4.5: resumir histórico parece mecânico e custaria cerca de um quinto
($1/$5 por 1M contra $5/$25, aproximadamente US$ 0,011 por regeneração contra
US$ 0,053).

A razão de não fazer isso é a posição do resumo na arquitetura. Ele não é uma
saída que alguém lê e descarta — é **entrada de todo turno seguinte**, para
sempre. Um resumo que perde o orçamento que a Marina mencionou não erra uma vez:
erra em todas as respostas dali em diante, e erra de forma que ninguém percebe,
porque o modelo seguinte responde com confiança sobre um contexto empobrecido.
Economizar quatro centavos por vinte mensagens não paga esse risco.

O julgamento também não tem como ser verificado hoje: a suíte de avaliação que
mediria a qualidade do resumo só chega na TEC-210. Rebaixar antes de existir a
régua é apostar sem placar.

O modelo fica em configuração de qualquer forma — se a TEC-210 mostrar que Haiku
sustenta a qualidade, a troca é uma variável de ambiente, não uma migração. A
direção barata da decisão é a reversível.

## Lacuna registrada, não fechada

A chamada de resumo gasta token e **não é mensagem de ninguém**.
`message_telemetry` tem FK para `messages.id`; encaixar um resumo ali exigiria
inventar uma linha de mensagem que nunca existiu.

Esta história loga `resumo.gerado` com modelo, tokens, custo e latência de forma
estruturada, e para por aí. Persistir gasto de LLM que não é resposta ao lead
precisa de decisão própria — é irmã da
[TEC-220](https://eduardodurieuxlopes.atlassian.net/browse/TEC-220) e do painel
de custo do E8. Criar tabela para isso aqui seria decidir sozinho uma coisa que o
E8 vai querer opinar.

## Estrutura de módulos

Novos:

```
src/mobia/domain/context/montagem.py       montar_contexto, ContextoMontado
src/mobia/domain/context/models.py         ConversationSummary, LeadQualification
src/mobia/domain/context/resumo.py         ResumidorPort, ResumidorAnthropic
src/mobia/domain/context/estado.py         leitura de lead_qualification
src/mobia/infra/anthropic.py               cliente e contagem de tokens
alembic/versions/0005_resumo_e_qualificacao.py
tests/features/test_janela_de_contexto.py
tests/integration/test_montagem.py
tests/unit/test_estouro.py
```

Alterados: `app/config.py`, `pyproject.toml`, `.env.example`, `README.md`.

## Testes

Os quatro cenários Gherkin viram testes com um `ResumidorPort` dublê — nenhum
teste chama a API de verdade.

| Cenário | O que prova |
|---|---|
| Conversa longa cabe no limite | 60 mensagens → 20 literais + resumo das 40, total ≤ 12.000 |
| Estado estruturado não é reconstruído | orçamento conhecido aparece no contexto; nenhum campo é derivado do texto |
| Resumo é comprimido ao estourar | contexto de 13.500 → cabe em 12.000 depois do laço |
| Resumo é regerado na cadência | 40 literais disparam regeneração; 39 não |

E a invariante que o primeiro cenário sozinho não pegaria:

- Em qualquer ponto entre duas regenerações, o prompt contém **pelo menos** as
  vinte mensagens mais recentes na íntegra. O teste percorre a conversa mensagem
  a mensagem de 41 a 80 e asserta o piso em cada passo — é o único jeito de pegar
  a regressão em que a marca cola no presente.

Integração adicional, cobrindo o que os critérios implicam mas não enunciam:

- `SELECT resumo` cru devolve bytes, não texto legível.
- AAD rejeita resumo movido de outra conversa.
- Falha do resumidor degrada com log e ainda respeita o teto.
- O laço do estouro termina — resumidor que devolve sempre o mesmo tamanho não
  causa laço infinito, cai no truncamento com log.
- A marca d'água usa o par ordenado: duas mensagens no mesmo `created_at` não
  fazem o resumo pular nem repetir nenhuma.

## Fora de escopo

Extração dos campos de qualificação (TEC-145 e o épico TEC-144), classificação de
intenção (TEC-134), o agente que de fato responde ao lead, unificação de
histórico entre canais (TEC-129), encerramento por inatividade (TEC-130),
persistência de telemetria de chamadas que não são resposta (irmã da TEC-220),
suíte de avaliação da qualidade do resumo (TEC-210).

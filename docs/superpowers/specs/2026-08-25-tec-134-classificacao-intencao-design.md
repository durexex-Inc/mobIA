# TEC-134 — Classificar a intenção do lead a cada turno

- **Data:** 2026-08-25
- **Jira:** [TEC-134](https://eduardodurieuxlopes.atlassian.net/browse/TEC-134) · Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133)
- **Origem:** RF-03, RN-03.1, RN-03.2 (SRS v1.0); métrica de acurácia em 4.4 e RNF-26
- **Status:** aprovado, aguardando plano de implementação

## Problema

Ricardo é investidor e quer que o atendimento perceba, já na segunda mensagem,
que ele não está comprando para morar — para não ser interrogado sobre varanda e
número de quartos. Sem classificação de intenção não há roteamento, e sem
roteamento o sistema é um chatbot único.

Mas há um problema maior por trás desse. Depois de quatro histórias, **o sistema
nunca respondeu a ninguém.** TEC-122 recebe, TEC-125 deduplica, TEC-126 registra,
TEC-127 monta o contexto — e o `NoopOutbound` continua não enviando nada, o
`MessageRecorder` continua sem produtor e `montar_contexto` continua sem
consumidor. O `_deliver` do `GuardedOutbound` levanta `NotImplementedError` desde
o primeiro dia.

Esta história fecha o circuito.

## Escopo: o que foi devolvido a outras histórias

O ticket, como escrito, contém dois pedaços que pertencem a outros donos. Ambos
foram devolvidos antes do desenho, e o registro fica aqui porque quem ler o
ticket sozinho vai estranhar a ausência.

**O critério 4 é a TEC-210, palavra por palavra.** Ambos dizem "suíte de 50
conversas sintéticas" e "acurácia de intenção de pelo menos 90%" rodando no CI.
Não é sobreposição parcial. E a TEC-210 é bloqueada pela TEC-161, então a TEC-134
não teria como cumprir o próprio critério.

**O cenário 1 tem dependência circular.** Ele exige que "a próxima pergunta do
agente seja sobre ticket ou expectativa de retorno" e que "o agente não pergunte
sobre número de quartos". Escolher qual campo perguntar é
[TEC-145](https://eduardodurieuxlopes.atlassian.net/browse/TEC-145) — que é
bloqueada pela TEC-134. O critério depende de comportamento que depende dele.

Aqui entra: classificação com confiança, persistida, e uma resposta que de fato
chega ao lead. O formato dessa resposta (600 caracteres, uma pergunta por turno)
é TEC-140; a escolha inteligente do campo é TEC-145; a régua de 90% é TEC-210.

## Abordagem: um turno, uma chamada

O job `process_message` para de mandar ACK e passa a rodar o turno:

```
claim → montar_contexto → uma chamada ao modelo
      → grava conversation_intent
      → reserva o envio
      → entrega à Meta
      → MessageRecorder grava a fala do agente
      → PROCESSED
```

Uma única chamada devolve intenção, confiança e resposta por saída estruturada.
Duas chamadas separadas dariam medição isolada de cada peça, mas dobrariam custo e
latência num caminho que já paga o resumo da TEC-127 a cada vinte mensagens. E o
schema **garante** que intenção e confiança venham, que é literalmente a regra de
negócio; uma tool call não garante — o modelo pode simplesmente não chamar.

## O que muda no `GuardedOutbound`, e por quê

O `GuardedOutbound` reserva antes de entregar: grava em `outbound_dispatches`,
commita, e só então chama `_deliver`. A docstring é explícita sobre a troca —
*"Queda entre a reserva e a entrega perde aquele envio; queda depois nunca
duplica."*

Isso foi decidido quando o que se perdia era um **ACK**. Perder um ack não custa
nada. Agora o que se perde é **a resposta ao lead**, e ela se perde em silêncio e
para sempre: a reserva está commitada, o sweeper reenfileira, o worker reivindica,
e a guarda responde "já entreguei isso". A Marina escreve, o sistema gera a
resposta, o POST estoura por timeout, e ela nunca recebe nada sobre aquele turno.

**A reserva passa a ser liberada quando a falha é retentável.** Erro de rede ou
5xx da Meta apagam a linha de `outbound_dispatches` antes de propagar, e a
retentativa funciona. Erro 4xx mantém a reserva, porque retentar não ajuda.

A troca inverte de lado: passa a ser possível o lead receber a mesma resposta duas
vezes, se o POST chegou e só a leitura da resposta falhou. Entre a Marina receber
duas vezes e a Marina nunca receber, numa conversa de qualificação, a duplicata
ganha — ela é visível, constrangedora e recuperável; o silêncio é invisível, e o
lead vai embora achando que ninguém respondeu.

### A ordem dentro do turno

Gravar a fala do agente acontece **depois** da entrega.

Gravar antes significa que uma queda no meio deixa uma fala fantasma no histórico
— texto que o lead nunca viu, que entra no contexto do próximo turno e depois é
dobrado permanentemente no resumo da TEC-127. O agente passa a acreditar que disse
algo que não disse.

Gravar depois significa que a mesma queda deixa a resposta entregue e ausente da
linha do tempo, e o turno seguinte pode se repetir. **Prefiro o agente se repetir
a ele inventar memória.** Repetição o lead perdoa e o operador vê; memória
inventada contamina tudo o que vem depois e ninguém percebe.

## Modelo de dados

### `conversation_intent`

Chaveada por `(channel, conversation_key)`, como `conversation_summaries`:

| Coluna | Tipo | Nota |
|---|---|---|
| `channel`, `conversation_key` | pk composta | |
| `intencao` | `varchar(20)` | um dos sete valores |
| `confianca` | `numeric(3,2)` | 0,00 a 1,00 |
| `modelo` | `varchar(64)` | qual modelo classificou |
| `updated_at` | `timestamptz` | |

Gravada em **todo** turno, inclusive quando a intenção não muda — o critério diz
que a classificação acontece a cada turno, e uma linha que não é reescrita não
distingue "continua COMPRA" de "não foi classificado".

**Não vai em `lead_qualification`**, apesar de aquela tabela já ter uma coluna
`intencao`. A TEC-127 registrou por escrito que a dona daquela tabela é a TEC-145,
e confiança é artefato do classificador, não critério de qualificação — não faz
sentido ao lado de quartos e vagas.

## O classificador

Uma chamada com `output_config.format`, schema estrito, `additionalProperties:
false`:

```
intencao   enum: COMPRA | ALUGUEL | INVESTIMENTO | VENDER_IMOVEL
                 SUPORTE_CONTRATO | INDEFINIDA | FORA_DE_ESCOPO
confianca  number, 0..1
resposta   string
```

O `ContextoMontado` da TEC-127 vira o prompt — este é o primeiro consumidor real
dele. O system prompt é fixo e vai na frente, casando com o breakpoint de cache
que a TEC-127 desenhou: sistema e resumo ficam quentes por vinte turnos.

`Settings.modelo_agente`, separado de `modelo_resumo`, default `claude-opus-5`.
São trabalhos diferentes e a TEC-210 vai querer afinar um sem tocar no outro.

### A confiança é autoavaliação, não probabilidade

O critério exige "INVESTIMENTO com confiança de pelo menos 0,8", e a TEC-135 vai
ramificar em "abaixo de 0,6 desambigua". As duas tratam o número como medida.

**Ele não é.** É o modelo dizendo o quanto acha que acertou, e modelos são
sistematicamente mal calibrados nisso — em geral para cima. Serve como sinal
grosseiro e vale usar, mas o limiar de 0,6 da TEC-135 precisa ser calibrado contra
dados reais, e quem tem esses dados é a TEC-210 com as 50 conversas anotadas.

Estes números são **provisórios até existir a régua**. Sem esse registro, alguém
daqui a dois meses vai depurar por que a desambiguação nunca dispara sem saber que
o limiar nunca foi medido.

## A entrega à Meta

`WhatsAppOutbound(GuardedOutbound)` implementa o `_deliver` que estava
`NotImplementedError` desde a TEC-122: `POST` na Cloud API com
`messaging_product`, o `wa_id` do lead como destino e o corpo em texto. O
`phone_number_id` já está em toda mensagem de entrada como
`recipient_external_id` — só falta o token.

`httpx` entra nas dependências de produção. Hoje existe apenas como dependência de
desenvolvimento (cliente de teste do FastAPI), e o `anthropic` traz `httpx2`, que é
outro pacote — depender do transitivo de outra biblioteca para falar com a Meta
seria frágil.

### A janela de 24 horas

A Meta só aceita mensagem livre dentro de 24h da última fala do lead; fora disso
exige template aprovado. No fluxo normal isso nunca ocorre — respondemos a uma
mensagem que acabou de chegar. Mas o sweeper reenfileira mensagens paradas, e uma
que ficou `FAILED` por 25 horas volta fora da janela.

**Não pré-checamos o relógio.** Duplicar a contagem da Meta cria duas fontes de
verdade que divergem. A Meta recusa, o código captura o erro específico, loga
`outbound.fora_da_janela`, mantém a reserva e marca a mensagem como `PROCESSED` —
ela não falhou, ela expirou, e isso é diferente. Template é outra história.

## Erros, e o que o lead recebe em cada um

| Falha | Comportamento | Lead recebe |
|---|---|---|
| Rede ou 5xx da Meta | Libera a reserva, propaga → `FAILED`, sweeper retenta | eventualmente sim |
| 4xx da Meta | Mantém a reserva, `PROCESSED`, log de erro | não |
| Fora da janela de 24h | Mantém a reserva, `PROCESSED`, log de aviso | não |
| Erro da API do modelo | Propaga → `FAILED`, sweeper retenta | eventualmente sim |
| `ContextoIrreducivel` | Loga, `PROCESSED`, sem resposta | **não, e nada avisa** |

**Por que 4xx vira `PROCESSED` e não `FAILED`.** A tentação é marcar como falha
para que o erro fique visível. Mas `FAILED` é o que o sweeper procura: ele
reenfileira, o worker reivindica, e o turno **roda inteiro de novo** — inclusive a
chamada paga ao modelo. Só o envio é suprimido pela guarda, no fim. Um payload
permanentemente inválido custaria cinco chamadas ao modelo para chegar
exatamente onde já estava.

A visibilidade vem do nível do log, não do estado da linha: 4xx loga em `error`
com o código que a Meta devolveu, e é isso que o alerta observa. `PROCESSED` aqui
significa "este turno acabou", não "deu tudo certo".

## Lacunas registradas, não fechadas

**Uma mensagem grande demais faz o lead ser ignorado em silêncio.** Quando
`montar_contexto` levanta `ContextoIrreducivel` — uma única mensagem que não cabe
no teto de 12.000 tokens nem depois de descartar o resumo — o turno termina sem
resposta.

Inventar uma resposta de contorno aqui esbarraria na TEC-139 (identificar-se como
assistente) e na TEC-140 (formato humanizado): escrever cópia sem essas regras é
decidir o tom do produto de contrabando. A lacuna fica visível no log e no spec, e
o dono natural é a TEC-135, que já trata o caso de o agente não ter o que dizer.

**Moderação de entrada e saída não existe.** A TEC-210 exige moderação em 100% dos
turnos. Este é o primeiro turno que existe, e ele vai ao ar sem nenhuma.

## Estrutura de módulos

Novos:

```
src/mobia/domain/agente/__init__.py
src/mobia/domain/agente/models.py        ConversationIntent
src/mobia/domain/agente/schemas.py       Intencao (enum), RespostaDoAgente
src/mobia/domain/agente/classificador.py ClassificadorPort, ClassificadorAnthropic
src/mobia/domain/agente/turno.py         executar_turno
src/mobia/domain/outbound/whatsapp.py    WhatsAppOutbound
alembic/versions/0006_conversation_intent.py
tests/unit/test_classificador.py
tests/integration/test_turno.py
tests/integration/test_whatsapp_outbound.py
tests/features/test_classificacao_de_intencao.py
```

Alterados: `pyproject.toml`, `.env.example`, `app/config.py`,
`domain/outbound/port.py` (liberação da reserva), `workers/jobs/process_message.py`,
`workers/main.py`, `tests/conftest.py`, `README.md`.

## Testes

Nenhum toca a rede: dublê para o classificador e para o HTTP da Meta.

| Cenário Gherkin utilizável | O que prova |
|---|---|
| Reconhecer intenção de investimento | "quero investir em imóveis para renda" → INVESTIMENTO, confiança ≥ 0,8 |
| Reconhecer intenção de aluguel | "procuro apartamento para alugar na Trindade" → ALUGUEL, confiança ≥ 0,8 |
| Intenção e confiança ficam registradas | `conversation_intent` tem COMPRA e 0,91 depois do turno |

Os que provam as decisões desta história, e que os cenários sozinhos não pegariam:

- **Falha retentável libera a reserva** e a retentativa entrega. Hoje isso é
  impossível — é o teste que prova a mudança no `GuardedOutbound`.
- **4xx não libera a reserva e não vira `FAILED`** — o teste asserta o estado
  `PROCESSED`, porque marcar falha aqui faria o sweeper pagar cinco chamadas ao
  modelo por um payload que nunca vai ser aceito.
- **A fala do agente é gravada depois da entrega**: queda no meio deixa o lead com
  a resposta e a linha do tempo sem ela, nunca o contrário.
- **Fora da janela de 24h vira `PROCESSED`**, não `FAILED` — expirar não é falhar.
- **`ContextoIrreducivel` não derruba o worker** e loga.
- Casos-semente de classificação, como teste comum e **sem gate de acurácia**.
  Medem que o classificador funciona, não que ele atinge 90% — essa é a TEC-210.

## Fora de escopo

Suíte de avaliação e gate de 90% no CI (TEC-210), desambiguação com confiança
baixa (TEC-135), mudança de intenção no meio da conversa (TEC-136), extração dos
campos de qualificação (TEC-145), escolha de qual campo perguntar (TEC-145),
formato humanizado da resposta (TEC-140), identificação como assistente virtual
(TEC-139), templates da Meta para fora da janela de 24h, moderação de conteúdo
(TEC-210), canal web (TEC-124).

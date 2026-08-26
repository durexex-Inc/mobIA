# TEC-135 — Desambiguar quando a confiança fica abaixo de 0,6

- **Data:** 2026-08-26
- **Jira:** [TEC-135](https://eduardodurieuxlopes.atlassian.net/browse/TEC-135) · Épico [TEC-133](https://eduardodurieuxlopes.atlassian.net/browse/TEC-133)
- **Origem:** RF-03, RN-03.2 (SRS v1.0)
- **Status:** aprovado, aguardando plano de implementação
- **Depende de:** TEC-134 (mergeado — classificador, `conversation_intent` e o turno do agente)

## Problema

Marina escreveu "queria ver umas casas aí". Ela ainda não decidiu se compra ou
aluga, e o texto não distingue as duas coisas. O TEC-134 classifica assim mesmo:
devolve um palpite — digamos `COMPRA` — com confiança 0,45, e escreve uma
resposta coerente com esse palpite. A resposta que sai já pergunta sobre entrada
e financiamento.

O custo não é um turno perdido. É que a partir dali a conversa inteira corre na
trilha errada: o resumo da TEC-127 registra que ela quer comprar, a qualificação
da TEC-145 vai extrair critérios de compra, e o corretor recebe no handoff um
lead de compra que na verdade queria alugar. O contorno — deixar o corretor
corrigir — é o que o próprio ticket chama de Should: funciona, e desperdiça a
conversa toda.

Uma pergunta aberta resolve num turno o que uma suposição silenciosa estraga em
vinte.

## Escopo: o que este card não entrega

O Gherkin do ticket fala em "seguir pela trilha de aluguel" e em "conduzir pela
qualificação genérica". **Nenhuma trilha existe.** Quem ler o critério de aceite
sozinho vai procurá-las no código e não vai achar:

- Roteamento por intenção é a [TEC-137](https://eduardodurieuxlopes.atlassian.net/browse/TEC-137).
- Escolher qual pergunta de qualificação fazer é a [TEC-145](https://eduardodurieuxlopes.atlassian.net/browse/TEC-145).
- O formato humanizado da resposta (limite de caracteres, uma pergunta por turno)
  é a [TEC-140](https://eduardodurieuxlopes.atlassian.net/browse/TEC-140).
- Mudança de intenção depois de uma classificação confiante é a
  [TEC-136](https://eduardodurieuxlopes.atlassian.net/browse/TEC-136) — o próprio
  ticket já a exclui.
- Calibrar se 0,6 é o número certo é a
  [TEC-210](https://eduardodurieuxlopes.atlassian.net/browse/TEC-210).

O que este card entrega, e o que os testes provam: **abaixo do limiar sai uma
pergunta em vez de uma suposição, isso acontece uma vez por episódio de
ambiguidade, e a intenção efetiva da conversa passa a ser `INDEFINIDA` enquanto a
confiança não subir.** O observável do cenário 3 é a intenção persistida mudar
para `ALUGUEL` e a resposta voltar a ser uma resposta normal; o do cenário 4 é o
desambiguador não ser chamado de novo.

## Abordagem: uma segunda chamada, só no caminho ambíguo

O TEC-134 fechou o turno em **uma** chamada, que devolve intenção, confiança e
resposta juntas. Esse é justamente o problema aqui: quando o código descobre que
a confiança foi 0,45, a resposta já veio escrita — e escrita assumindo o palpite,
que é o que o card proíbe.

O turno passa a ter um ramo:

```
montar_contexto
  → classificar                                    (chamada 1, inalterada)
  → grava intenção crua; limpa ou mantém o marcador  [transação 1, antes da entrega]
  → decidir_desambiguacao(confiança, marcador)
      ├─ não  → texto = resposta da chamada 1
      └─ sim  → desambiguar(contexto)              (chamada 2) → texto = pergunta
  → reserva + entrega
  → grava a fala do agente
  → se desambiguou: grava desambiguado_em            [transação 2, depois da entrega]
  → PROCESSED
```

Duas alternativas foram consideradas e descartadas.

**A regra só no prompt** — instruir o modelo a perguntar quando não tiver certeza,
sem ramo no código — é a mais barata e torna o critério de aceite inasserível. O
cenário *"confiança exatamente 0,6 não desambigua"* não teria ramo nenhum para
testar: viraria um `assert` sobre a boa vontade do modelo. A suíte deste repo
prova critério de aceite com teste executável.

**Um campo a mais no schema** — o modelo devolveria `resposta` e
`pergunta_de_desambiguacao` na mesma chamada, e o código escolheria qual enviar.
Mantém a latência constante, mas paga tokens de saída em **todo** turno por um
texto descartado na esmagadora maioria deles, e pede ao modelo que escreva uma
pergunta pressupondo dúvida mesmo quando ele tem certeza.

A segunda chamada concentra o custo extra no turno raro e deixa o limiar no
código, onde dá para testá-lo. O preço, dito com todas as letras: no turno
ambíguo a resposta da chamada 1 é **descartada**, a chamada 2 monta e paga o
**mesmo contexto de entrada inteiro de novo** — este projeto não declara
nenhum `cache_control`, e mesmo que declarasse, `system` precede `messages`
no corpo da requisição, então trocar o system prompt invalidaria qualquer
prefixo que estivesse quente — e a latência dobra. Como entrada domina a
contagem de tokens, o turno ambíguo não desperdiça só a saída da chamada 1:
paga o contexto de entrada (até `contexto_teto_de_tokens`) duas vezes. E é
exatamente o turno em que o lead já estava indeciso.

## Modelo de dados

`conversation_intent` ganha uma coluna, na migração **0007**:

| Coluna | Tipo | Semântica |
|---|---|---|
| `desambiguado_em` | `timestamptz NULL` | `NULL` = episódio limpo. Preenchido = a pergunta já foi feita neste episódio. |

Timestamp e não booleano porque ocupa o mesmo espaço e responde "quando" numa
investigação — é o que `updated_at` já faz na mesma tabela.

### O ciclo do marcador

O limite de uma pergunta vale **por episódio de ambiguidade**, não por conversa:

| Confiança | Marcador | Efeito |
|---|---|---|
| ≥ 0,6 | qualquer | grava a intenção e **limpa** o marcador — o episódio acabou |
| < 0,6 | `NULL` | desambigua, e marca **depois da entrega** |
| < 0,6 | preenchido | não pergunta de novo; segue com `INDEFINIDA` |

Uma conversa de quarenta turnos que fica clara, muda de assunto e fica ambígua de
novo pode perguntar de novo. O que a regra proíbe é insistir na **mesma**
ambiguidade — e uma classificação confiante no meio é a evidência de que a
ambiguidade anterior foi resolvida.

## O limiar e a decisão

O 0,6 hoje não existe em código: está em comentário no `models.py` e no spec do
TEC-134. Passa a ser constante de domínio, em `domain/agente/schemas.py`, ao lado
do enum que ele qualifica:

```python
LIMIAR_DE_DESAMBIGUACAO = Decimal("0.6")   # fechado por cima: 0,6 não desambigua
```

`Decimal` e não `float` porque a coluna é `numeric(3,2)` e a comparação é de
igualdade na borda: `0.6` em ponto flutuante binário não é 0,6, e o cenário do
limite exato é critério de aceite.

A decisão mora em `domain/agente/desambiguacao.py`, função pura, sem I/O: recebe
confiança e marcador, devolve se deve perguntar. É o que faz o cenário do limite
ser um teste de unidade de três linhas em vez de um teste de integração com fake
de modelo, banco e outbound.

## A intenção efetiva

`conversation_intent` continua registrando **fielmente** o que o classificador
devolveu: com confiança 0,45 e palpite `COMPRA`, a linha guarda `COMPRA` e `0,45`.
A tabela é o registro do classificador, e é desse par que a TEC-210 vai precisar
para medir se 0,6 é o limiar certo — `INDEFINIDA` gravado por cima destruiria o
dado.

Quem consome não lê a coluna. `IntencaoDaConversa` ganha uma propriedade
`efetiva`, que devolve `INDEFINIDA` sempre que a confiança está abaixo do limiar.
O TEC-136 e o TEC-137 leem por ela.

Isso atende o cenário 4 sem nenhum caso especial: ambiguidade persistente **já é**
`INDEFINIDA` por construção — ninguém precisa escrever `INDEFINIDA` na coluna
quando o lead responde e continua vago.

O risco assumido é um consumidor futuro ler `intencao` direto e rotear por um
palpite de 0,45. A mitigação é a propriedade ser o caminho óbvio e a coluna
carregar a advertência na docstring do modelo.

## A ordem das gravações

Duas transações sobre a mesma linha, em momentos diferentes do turno, e a razão
de cada uma é a mesma que o TEC-134 já defendeu para a fala do agente.

**A intenção é gravada antes da entrega.** Ela é sobre a mensagem do lead, que
existe independentemente de a resposta sair.

**O marcador é gravado depois da entrega.** Ele afirma *"eu já perguntei"*, e isso
só é verdade se a pergunta chegou. Gravá-lo antes queimaria a única chance de
desambiguar num 5xx da Meta: o sweeper reprocessa, encontra o marcador, e a
Marina fica em `INDEFINIDA` para sempre sem ninguém ter perguntado nada.

Por consequência, o marcador é escrito no mesmo ponto em que a fala do agente é
gravada — só quando `send()` devolveu `True`. Os três desfechos sem entrega
confirmada (`expirado`, `recusado`, `reentrega_suprimida`) **não** marcam.

## O port do classificador

`ClassificadorPort` ganha um segundo método, `desambiguar(contexto)`, em vez de um
port novo: os fakes dos testes ficam num objeto só e a implementação real
compartilha cliente e contexto.

Ela usa um system prompt próprio — uma pergunta, aberta, sem menu numerado, sem
assumir intenção — em **texto puro**, sem schema estrito, com `max_tokens` curto.
A saída é uma frase; não há campo para validar, e o schema estrito do TEC-134
existe porque intenção e confiança são regra de negócio, o que não se aplica aqui.

## Falhas

Nenhuma política nova. `RespostaInvalida` na chamada 2 propaga como a da chamada 1
já propaga hoje: o `process_message` marca `FAILED`, grava `last_error` pelo
critério de dono do tipo, e o sweeper retenta. Como o marcador só é escrito depois
da entrega, a retentativa desambigua de verdade em vez de encontrar o marcador e
desistir.

## Telemetria e custo

A fala gravada pelo `MessageRecorder` leva os tokens da **chamada 2**, que é o
texto que o lead recebeu, com `subagent="desambiguador"`.

A chamada 1 foi paga e sua resposta foi descartada. Ela continua visível no log
`agente.turno_gerado`, com o próprio custo. **O custo de um turno ambíguo está
inteiro nos logs, repartido em duas linhas, e só uma delas vira linha no banco.**
Fica registrado aqui para a TEC-210 não subestimar o custo por turno ao somar pela
tabela de mensagens.

## Testes

Os quatro cenários do ticket viram `tests/features/test_desambiguacao_de_intencao.py`,
no formato que o TEC-134 estabeleceu. Somados a:

- `tests/unit/test_desambiguacao.py` — a função pura: `0.6` exato não desambigua,
  `0.59` desambigua, marcador preenchido bloqueia, `≥ 0,6` limpa.
- `tests/unit/test_classificador.py` — o `desambiguar`: system prompt próprio,
  `max_tokens` curto, propagação de `RespostaInvalida`.
- `tests/integration/test_turno.py` — a ordem das gravações, e o marcador
  **ausente** nos três desfechos sem entrega confirmada.
- `tests/integration/test_repositorio_intencao.py` — persistência e limpeza do
  marcador; a propriedade `efetiva` nos dois lados do limiar.
- migração 0007 reversível; `alembic check` limpo.

## Garantias

- Abaixo de 0,6 o lead recebe uma pergunta, nunca uma resposta que assume a
  intenção.
- O limiar é fechado por cima: exatamente 0,6 segue sem perguntar.
- Uma pergunta por episódio de ambiguidade. Uma classificação confiante abre um
  episódio novo.
- Falha de entrega não queima a chance de perguntar.
- A tabela continua registrando o que o classificador devolveu, sem edição.

## Lacunas conhecidas

- **Nada garante que a chamada 2 devolva uma pergunta aberta.** O teste do cenário
  1 prova que o código chamou o desambiguador e enviou o texto dele — não que o
  modelo escreveu uma boa pergunta em vez de um menu numerado. Medir qualidade de
  saída é a TEC-210.
- **O limiar continua não calibrado.** 0,6 é o número do SRS, e a confiança é
  autoavaliação do modelo, não probabilidade calibrada. Este card só o tira de um
  comentário e o coloca num lugar onde a TEC-210 possa mexer.
- **Um turno ambíguo custa duas chamadas ao modelo, cada uma pagando o contexto
  de entrada inteiro.** Não há `cache_control` neste projeto para amortizar a
  repetição. Se a taxa de ambiguidade em produção for muito maior que a
  esperada, a abordagem do campo a mais no schema volta à mesa.
- **Nada limita quantos episódios de ambiguidade uma conversa pode ter.** Uma
  conversa que oscila em torno do limiar pode desambiguar várias vezes ao longo de
  muitos turnos. O reset exige uma classificação confiante no meio, o que torna o
  caso improvável, mas ele não é impossível.
- **O orçamento de tempo do worker não sobra folga para o turno ambíguo.** O
  turno paga `resumir` (às vezes) + `classificar` (sempre) + `desambiguar` (só
  no turno ambíguo) em sequência no mesmo cliente Anthropic, 120s de pior caso
  cada (60s por tentativa, uma retentativa). `resumir` + `classificar` sozinhos
  já somam os 240s de `job_timeout`; com `desambiguar` o pior caso soma 360s,
  sem contar `count_tokens` nem o POST para a Meta. Não é uma correção que este
  card decidiu fazer — mudar `job_timeout` ou `sweep_inflight_after_seconds`
  exige medir a taxa real de retentativa em produção, não uma extrapolação de
  pior caso. Ver os comentários em `infra/anthropic.py` e
  `workers/main.py::WorkerSettings.job_timeout`.
- **A garantia de "uma pergunta por episódio" vale por sequência de turnos, não
  por conversa.** Não há serialização por conversa: `claim_message` tranca por
  *mensagem*, o `FOR UPDATE SKIP LOCKED` do sweeper é por linha, não há lock
  consultivo, e `WorkerSettings` não define `max_jobs` — o default do arq é 10.
  Duas mensagens do mesmo lead chegando segundos uma da outra (rotina no
  WhatsApp) podem rodar em paralelo: as duas leem `desambiguado_em IS NULL`,
  as duas desambiguam, as duas entregam — o lead recebe duas perguntas. A
  guarda de saída não ajuda porque as duas passagens carregam `message_id`
  diferentes. O dano acontece na entrega, antes do marcador ser escrito, então
  nem um `UPDATE ... WHERE desambiguado_em IS NULL` condicional evitaria isso —
  a correção real precisa serializar por conversa *antes* da segunda chamada
  ao modelo, o que é um card à parte. A
  [TEC-128](https://eduardodurieuxlopes.atlassian.net/browse/TEC-128)
  ("Agrupar rajada de mensagens com debounce de 6 segundos") é o card que
  endereça isso.

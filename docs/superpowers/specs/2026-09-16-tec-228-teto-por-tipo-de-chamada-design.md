# TEC-228 — Teto por tipo de chamada, derivado de medição

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-228](https://eduardodurieuxlopes.atlassian.net/browse/TEC-228) — High (a rever, ver abaixo), épico TEC-133
**Branch:** `feat/tec-228-teto-por-tipo-de-chamada`
**Origem:** re-review da onda final da TEC-134. Faz par com a TEC-227.

## A medição mudou a card

A card mandava **medir antes de escolher os números**, e a medição inverteu a tese dela.

**Medido em 16/09/2026**, 5 amostras por cenário (3 para o investidor), com os prompts e os `max_tokens` de produção importados dos módulos, contra a API real:

| chamada | `max_tokens` | mediana | máximo | saída real |
| --- | --- | --- | --- | --- |
| `count_tokens` | — | 0,25s | 0,28s | — |
| `desambiguar` | 300 | 1,43s | 1,69s | 41 tokens |
| `resumir` | 2000 | 2,87s | 3,72s | ~242 tokens |
| `classificar` | 1500 | 6,25s | 7,49s | ~460 tokens |
| `investidor` | 1500 | 8,05s | 9,26s | ~600 tokens |

### O `resumir` não é o perigoso — é o segundo mais rápido

A card afirma que *"uma geração legítima de 2000 tokens em opus pode se aproximar de 60 segundos"*. Duas coisas estão erradas nessa frase hoje:

1. **Não roda em opus.** `modelo_resumo` é `claude-sonnet-5` desde a troca por custo, e o comentário de `config.py` registra que a troca do resumo não foi medida.
2. **Não gera 2000 tokens.** A saída real é ~242. O `max_tokens=2000` é um teto que nunca se atinge, e a latência é governada pelos tokens de **saída**, não pelo teto.

### A aritmética do estouro estava sobre o teto, não sobre a realidade

O comentário de `infra/anthropic.py` conclui que um turno pode somar 360s contra os 240s do `job_timeout`. A conta está certa e a premissa não: ela multiplica o **teto** (60s × 2 tentativas × 3 chamadas), não a latência medida. Com números reais, o pior caminho de um turno soma **~21s**, ou ~42s contando a retentativa — folgado dentro dos 240s.

### Um alarme falso que vale registrar

Na primeira passada, o cenário do investidor apareceu com 18,56s de mediana e **2 de 5 amostras cortadas** no teto de 1500 tokens. Era artefato da medição: eu havia alimentado o prompt do investidor com uma conversa de **aluguel**, e o descasamento fez o modelo divagar até o teto. Refeito com uma conversa de investidor de verdade: 8,05s, ~600 tokens, **zero cortes em 3 amostras**.

Fica registrado porque a lição é sobre o método, não sobre o código: **medição com entrada descasada produz defeito que não existe**, e quase virou card.

## A card deixa de ser High

Ela é High por um risco que era do opus. A **forma** continua errada — um teto único para chamadas que vão de 0,25s a 9,3s —, mas não há incêndio: nada chega perto dos 60s atuais, e o `job_timeout` tem folga de ordem de grandeza. A prioridade deveria cair, e isso vai no comentário da card.

## Decisões

### D1 — Teto por requisição, um cliente só

`AsyncAnthropic.messages.create()` aceita `timeout=` por chamada — confirmado na versão instalada. Não é preciso um cliente por tipo, e o `lru_cache` de `get_client()` continua valendo.

O cliente mantém um teto de construção como piso de segurança, para que uma chamada nova que esqueça o override não herde os dez minutos do SDK.

### D2 — Os números vêm da medição, com folga de ~3× sobre o máximo

| chamada | teto | máximo medido | folga |
| --- | --- | --- | --- |
| `count_tokens` | 5s | 0,28s | 18× |
| `desambiguar` | 12s | 1,69s | 7× |
| `resumir` | 25s | 3,72s | 6,7× |
| `classificar` | 25s | 7,49s | 3,3× |
| `investidor` | 35s | 9,26s | 3,8× |

**A folga não é arbitrária, e a razão dela é uma limitação da própria medição:** as amostras repetiram o mesmo prompt de sistema, então provavelmente pegaram *prompt cache*. São otimistas para o primeiro turno de uma conversa, que é justamente o caso frio. Três vezes o máximo medido absorve isso sem chegar perto do `job_timeout`.

O `count_tokens` fica em 5s por ser ida-e-volta de rede e não geração: 18× o máximo medido ainda é menos de um décimo do menor teto de geração.

As chamadas de geração pequenas ganham teto pequeno **porque a falha delas é barata**: `desambiguar` perde a pergunta de desambiguação daquele turno, não a conversa.

### D3 — A soma do pior caminho vira teste

Pior caminho de um turno: `resumir` + `classificar` + `investidor` = 85s de teto; com `max_retries=1`, 170s; mais `count_tokens`, ~180s. Cabe nos **240s** do `job_timeout` com 60s de sobra.

Hoje a mesma conta dá 360s e **não cabe** — o que o comentário do código já admite e nenhum teste impede.

O teste soma as constantes e compara com `job_timeout`, importando as duas pontas em vez de repetir os números. É o que torna a relação explícita: quem subir um teto sem olhar o orçamento vê vermelho.

### D4 — O log do estouro do `resumir`, e o critério da card já está meio atendido

A card pede que o timeout do `resumir` deixe de ser indistinguível de outras degradações. **Ele já é distinguível hoje:** `contexto.degradado` carrega `reason=type(exc).__name__`, e o SDK levanta `APITimeoutError` — então filtrar timeouts das demais degradações é uma consulta por campo, não um problema em aberto.

O que falta é diferente e menor: saber **em que teto** a chamada morreu. Com teto por tipo, `APITimeoutError` passa a significar coisas distintas conforme a chamada, e quem lê o log não tem como saber se o estouro foi contra 25s ou contra 35s. A adição é o teto no payload.

**Não se cria evento próprio.** Um nome novo obrigaria todo consumidor de `contexto.degradado` a conhecer os dois, para uma distinção que um campo já faz — e o comentário daquele bloco argumenta exatamente nessa direção quando a TEC-237 escolheu acrescentar `motivo` em vez de um evento novo.

### D5 — A medição entra no repositório

`evals/relatorios/`, no molde dos relatórios que já existem lá, com data, modelo, máquina, as amostras cruas e as limitações — inclusive o alarme falso do investidor. Sem isso, quem mexer nos tetos daqui a seis meses recomeça do palpite, que é o estado que esta card existe para encerrar.

## Lacunas declaradas

**A medição é de uma máquina, num momento, com 5 amostras.** Não é p95 de produção, e não pretende ser: é a ordem de grandeza que faltava para escolher teto. A folga de 3× existe porque ela é o que é.

**O prompt cache provavelmente ajudou.** Repetir o mesmo `system` cinco vezes é o melhor caso de cache, e produção também o usa (`cache_control`) — mas não no primeiro turno de cada conversa.

**A qualidade do resumo continua sem instrumento.** A troca opus→sonnet não foi medida nesse eixo, e esta card mede **latência**, não qualidade. O comentário de `config.py` já diz que se o resumo regrediu nada acusaria; isto continua verdade depois desta card.

**Os tetos não protegem contra provedor lento de verdade.** Se a API degradar como um todo, 25s viram estouro onde antes havia 60s — ou seja, esta card **aumenta** a taxa de falha tipada nesse cenário, em troca de falhar mais cedo e mais barato. É a escolha que a TEC-227 já fez ao preferir erro tipado a cancelamento.

## Testes

- Unitário: a soma dos tetos do pior caminho, vezes as tentativas, cabe no `job_timeout` (D3).
- Unitário: cada tipo de chamada usa o seu teto — que o override chega ao SDK, e não que o número está certo.
- O log de degradação carrega o teto.

## Fora de escopo

- Medir qualidade de resumo (não há corpus nem critério; o `config.py` registra que a TEC-140 seria o lugar e não existe).
- Mexer em `max_retries`.
- O cliente de moderação, que já tem teto próprio desde a TEC-233.
- Subir o `job_timeout`.

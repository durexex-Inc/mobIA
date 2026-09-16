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

O `count_tokens` fica em 5s por ser ida-e-volta de rede e não geração. A folga de 18× soa exagerada e não é: 18× um máximo de 0,28s ainda dá 5s, menos da metade do menor teto de geração. **Folga em percentual não é folga em segundos**, e o orçamento se paga em segundos.

As chamadas de geração pequenas ganham teto pequeno **porque a falha delas é barata**: `desambiguar` perde a pergunta de desambiguação daquele turno, não a conversa.

`reagir` não foi medido e não está na tabela. Herda o número de `desambiguar` por ter a mesma forma — 300 tokens de saída, sem ferramenta, uma requisição só. Fica dito, em vez de escondido num número com aparência de medido.

### D3 — A soma do pior caminho vira teste, e ela não é a que eu escrevi primeiro

**A primeira versão desta decisão contava três chamadas e estava errada.** O turno paga até **cinco fatias**, e duas delas custam **duas requisições cada**:

| fatia | onde | requisições |
| --- | --- | --- |
| `count_tokens` | `montar_contexto` | 1 |
| `resumir` | `montar_contexto`, a cada ~40 mensagens | 1 |
| `reagir` | `turno.py:1463` | 1 |
| chamada 1 — `classificar` ou `qualificar_investidor` | `turno.py:1544` | até 2 (laço de `tool_use`) |
| chamada 2 — `desambiguar` ou `qualificar_investidor` | `turno.py:2035` / `2049` | até 2 |

O laço é o `for tentativa in (1, 2)` de `_chamar`: quando o modelo pede a ferramenta de busca, a mesma fatia bate no provedor duas vezes. As duas chamadas de investidor são exclusivas entre si — a de `2049` só dispara quando a `1544` **não** foi a do investidor —, então o pior par é `classificar` com busca seguido de `qualificar_investidor` com busca.

**O comentário de `infra/anthropic.py` também subconta.** Ele diz 360s; com cinco fatias e o laço de busca, o pior caso de hoje é **840s** contra os 240s do `job_timeout` — pior do que o próprio código admite.

### D4 — `max_retries = 0` no cliente do turno, e é ela que fecha a conta

Os tetos por tipo sozinhos **não bastam**:

| | por tentativa | com `max_retries=1` | contra 240s |
| --- | --- | --- | --- |
| hoje, tudo a 60s | 420s | **840s** | estoura |
| tetos da D2, retry 1 | 162s | **324s** | ainda estoura |
| tetos da D2, retry 0 | 162s | **162s** | 78s de folga |

`APITimeoutError` é retentado — `_should_retry_exception` do SDK trata `APIConnectionError` como retentável e o timeout herda dele —, então a retentativa dobra tudo. **É ela que come metade do orçamento.**

Zerar não é decisão nova deste documento: **a moderação já a tomou, e citou esta card pelo nome.** O comentário de `MAX_TENTATIVAS_DA_MODERACAO = 0` diz *"uma segunda tentativa dobraria o teto para ganhar pouco"* e *"Reduzir a chance de o turno estourar e a TEC-228"*. O que muda aqui é só o alcance: o mesmo argumento vale para o cliente que faz as cinco fatias, não só para o que modera as duas pontas.

A medição sustenta o argumento: as chamadas levam de 0,25s a 9,3s. Um estouro contra 25s não é lentidão — é pane. Retentar uma pane custa outros 25s pelo mesmo desfecho.

**O que se perde, dito sem rodeio.** A retentativa não servia só para timeout: ela cobria 429, 5xx e queda de conexão, onde retentar é barato e costuma funcionar. Sem ela, um 429 deixa de ser reparado dentro da requisição e passa a ser reparado pelo **sweeper**, que refaz o turno inteiro — mais caro, porque repaga as chamadas que já tinham dado certo. A troca é deliberada: um orçamento que fecha vale mais que uma retentativa barata num caminho raro, e o sweeper garante que nada se perde.

**`TIMEOUT_SEGUNDOS` fica**, como piso de construção. Ele deixa de governar as cinco fatias e passa a governar só quem não pede teto próprio.

### D5 — O log do estouro do `resumir`, e o critério da card já está meio atendido

A card pede que o timeout do `resumir` deixe de ser indistinguível de outras degradações. **Ele já é distinguível hoje:** `contexto.degradado` carrega `reason=type(exc).__name__`, e o SDK levanta `APITimeoutError` — então filtrar timeouts das demais degradações é uma consulta por campo, não um problema em aberto.

O que falta é diferente e menor: saber **em que teto** a chamada morreu. Com teto por tipo, `APITimeoutError` passa a significar coisas distintas conforme a chamada, e quem lê o log não tem como saber se o estouro foi contra 25s ou contra 35s. A adição é o teto no payload.

**Não se cria evento próprio.** Um nome novo obrigaria todo consumidor de `contexto.degradado` a conhecer os dois, para uma distinção que um campo já faz — e o comentário daquele bloco argumenta exatamente nessa direção quando a TEC-237 escolheu acrescentar `motivo` em vez de um evento novo.

### D6 — A medição entra no repositório

`evals/relatorios/`, no molde dos relatórios que já existem lá, com data, modelo, máquina, as amostras cruas e as limitações — inclusive o alarme falso do investidor. Sem isso, quem mexer nos tetos daqui a seis meses recomeça do palpite, que é o estado que esta card existe para encerrar.

### D7 — O maior termo do orçamento não era da Anthropic

A D4 fechou a conta em 162s e **ela ainda estava incompleta**. Um turno que busca chama o OpenAI: `turno.py` injeta o embedador na porta de busca, e `busca.py` o usa para vetorizar a `consulta_texto` que o modelo escreveu. O cliente de `infra/embeddings.py` tinha `TIMEOUT_SEGUNDOS = 50.0` e `MAX_TENTATIVAS = 1` — **100s por busca, até duas buscas por turno, 200s**. Sozinho, mais que todas as chamadas de modelo somadas.

| termo | pior caso |
| --- | --- |
| Anthropic, com os tetos da D2 e sem retentativa | 162s |
| embed da busca, antes | 200s |
| moderação das duas pontas | 10s |
| POST para a Meta | 10s |
| **total** | **382s** contra `job_timeout` 240 |

Escrever um teste de orçamento que omitisse os 200s repetiria exatamente o defeito que esta card encontrou no comentário antigo: somar a própria parcela e chamá-la de total.

**A consulta do turno ganha o mesmo tratamento, o indexador não.** `embedar_do_turno` manda 10s sem retentativa; `embedar` continua com 50s e uma retentativa, porque na indexação o lote é grande, a varredura tem o tempo dela e retentar vale o que custa. Duas funções e não um parâmetro opcional: um default deixaria o caro como padrão, e quem esquecesse de passá-lo no turno voltaria aos 100s em silêncio.

**Os 10s não foram medidos, e isso está escrito no código.** Não há `OPENAI_API_KEY` nesta máquina, então a sonda não rodou. O número é o dobro do teto que a medição deu para `count_tokens` — a chamada de forma mais parecida que este projeto tem medida: ida-e-volta de rede, payload minúsculo, sem geração, 0,28s de pior caso. O dobro porque é outro provedor e nenhuma amostra o cobre. **É o número menos sustentado desta card**, e medir é outra card.

Com ele, o total fecha em **202s**, com 38s de folga para o banco.

### D8 — O orçamento inteiro mora no teste, e não em nenhum módulo

Nenhum dos quatro módulos conhece a conta toda, e cada um deles já teve um comentário que somava a própria parcela e a chamava de total — foi assim que `infra/anthropic.py` chegou a afirmar 360s quando o real era 840s, e foi quase assim que esta card fechou 162s sem notar 200s.

`tests/unit/test_orcamento_do_turno.py` importa cada termo de quem o define e o `job_timeout` do `WorkerSettings` de verdade. **Nenhum número está escrito lá.** O que ele protege é a relação: subir qualquer teto sem olhar o orçamento fica vermelho.

Um segundo teste afirma que a folga cobre pelo menos 30s de banco — caber por 1s seria caber e estourar na primeira consulta. Os 30s são declarados e não medidos, como os 20s que a varredura de follow-ups reserva pelo mesmo motivo.

### D9 — As duas chamadas de fora do turno ficam no piso, e isso tem consequência

Há **seis** sítios que chamam a Anthropic, não os três que a card lista (e mais o OpenAI da D7). Além das cinco fatias do turno e da moderação (que já tem cliente próprio desde a TEC-233), duas vivem fora do turno:

- `followup/prosa.py:216` — a frase de abertura do follow-up, no job de varredura.
- `handoff/resumo.py:207` — o resumo do dossiê, no job `gerar_resumo`.

**Nenhuma das duas foi medida, e nenhuma disputa o orçamento do turno.** Elas ficam no `TIMEOUT_SEGUNDOS` de construção. Inventar teto medido para chamada que ninguém mediu seria exatamente o palpite que esta card existe para encerrar.

**Mas o `max_retries` as alcança, e aí está o efeito colateral.** `sweep_followups.py` deriva o `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS = 90` de uma conta que cita `TIMEOUT_SEGUNDOS`/`MAX_TENTATIVAS` pelo nome: `240 - 130 - 20 = 90`, em que os 130 são "os dois clientes externos" com os 120s de pior caso do cliente do modelo. Com retry 0 esse termo cai para 60, os externos custam ~70, e a conta daria `240 - 70 - 20 = 150`.

**O número fica em 90 assim mesmo.** Subir para 150 mudaria quantos follow-ups uma varredura entrega — efeito visível para o lead, decidido por uma card que fala de timeout. Um teto mais apertado que o necessário é seguro (o que sobra continua devido e entra na varredura seguinte, cinco minutos depois), e o comentário de lá passa a dizer que os 90 são conservadores por escolha, não derivados da fórmula. Subir é outra card.

O comentário daquele bloco avisava: *"Mexer num dos dois sem refazer a soma acima volta a deixar o teto frouxo."* Refeita — e na direção segura.

## Lacunas declaradas

**A medição é de uma máquina, num momento, com 5 amostras.** Não é p95 de produção, e não pretende ser: é a ordem de grandeza que faltava para escolher teto. A folga de 3× existe porque ela é o que é.

**O prompt cache provavelmente ajudou.** Repetir o mesmo `system` cinco vezes é o melhor caso de cache, e produção também o usa (`cache_control`) — mas não no primeiro turno de cada conversa.

**A qualidade do resumo continua sem instrumento.** A troca opus→sonnet não foi medida nesse eixo, e esta card mede **latência**, não qualidade. O comentário de `config.py` já diz que se o resumo regrediu nada acusaria; isto continua verdade depois desta card.

**O teto do embed é palpite, e é o único.** Todo outro número desta card saiu de medição contra a API real. O de `TETO_DA_CONSULTA_DO_TURNO` não: não há `OPENAI_API_KEY` nesta máquina. Ele é o dobro do teto que a medição deu para a chamada de forma mais parecida (`count_tokens`), e está declarado como não medido no comentário do próprio código. **É o termo mais frágil do orçamento, e é o segundo maior.**

**Os tetos não protegem contra provedor lento de verdade.** Se a API degradar como um todo, 25s viram estouro onde antes havia 60s — ou seja, esta card **aumenta** a taxa de falha tipada nesse cenário, em troca de falhar mais cedo e mais barato. É a escolha que a TEC-227 já fez ao preferir erro tipado a cancelamento.

## Testes

- Unitário: a soma das cinco fatias, com o laço de busca contado em dobro e as tentativas do cliente, cabe no `job_timeout`. Importa as duas pontas em vez de repetir os números, para que subir um teto sem olhar o orçamento fique vermelho (D3, D4).
- Unitário: cada tipo de chamada manda o SEU teto ao SDK — que o override chega, não que o número está certo.
- Unitário: as duas chamadas de fora do turno **não** mandam teto, e por isso caem no piso de construção (D9).
- Unitário: a folga sobre o `job_timeout` cobre pelo menos 30s de banco — caber por 1s seria caber e estourar na primeira consulta (D8).
- Unitário: o turno injeta `embedar_do_turno` na porta de busca, e **não** o `embedar` da indexação (D7).
- Integração: o log de degradação carrega `teto_s` quando a causa foi `APITimeoutError`, e `None` quando não foi — um campo que afirmasse teto numa falha de schema mentiria sobre o que aconteceu (D5).

## Fora de escopo

- Medir qualidade de resumo (não há corpus nem critério; o `config.py` registra que a TEC-140 seria o lugar e não existe).
- O cliente de moderação, que já tem teto próprio desde a TEC-233.
- Subir o `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS` da varredura de follow-ups (D9).
- Medir as duas chamadas de fora do turno.
- Medir o embed da busca e derivar o teto dele (D7) — bloqueado por falta de chave nesta máquina.
- Reclamar a folga que a D4 abriu na varredura de follow-ups.
- Subir o `job_timeout`.

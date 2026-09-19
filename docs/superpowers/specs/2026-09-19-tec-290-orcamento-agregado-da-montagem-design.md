# TEC-290 — O orçamento agregado da montagem, e a conta volta a fechar

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-290](https://eduardodurieuxlopes.atlassian.net/browse/TEC-290) — épico TEC-133
**Branch:** `feat/tec-290-orcamento-agregado-da-montagem`
**Origem:** TEC-229, que corrigiu o grafo de chamadas e deixou o orçamento estourado de propósito.

## Objetivo

Fazer a soma dos quatro clientes externos caber no `job_timeout` com a reserva de banco de pé, e fazer com que ela **pare de crescer** quando alguém mexer na configuração da montagem.

Hoje a conta é 327s contra 240s. Os dois testes que somam estão `xfail(strict=True)` apontando para esta card.

## A decisão: o caminho 3, puro

A card lista três caminhos sem escolher. Medidos os três antes de decidir, dois quase não fecham:

| variante | soma | folga | fecha? |
| --- | --- | --- | --- |
| hoje | 327s | −87s | não |
| **2** — `contexto_max_iteracoes` 3→**0** (desliga o laço) | 237s | 3s | **não** |
| **2** — 3→1 + `count_tokens` 5→2 + `resumir` 25→12 | 214s | 26s | **não** |
| **2** — o acima + `classificar` 25→15, `investidor` 35→20 | 164s | 76s | sim |
| **3** — deadline agregado de 35s na montagem | **207s** | **33s** | **sim** |
| **3** — deadline de 40s | 212s | 28s | não |
| **1** — `job_timeout` 300 (sweep 360) | 327s | −27s | **não** |
| **1** — `job_timeout` 360 (sweep 420) | 327s | 33s | sim |

O critério de "fecha" é o do `test_a_folga_paga_o_banco`: `job_timeout - soma >= 30`.

Três fatos que a card não registra e que decidiram a escolha.

**O caminho 2 sozinho não fecha.** Zerar `contexto_max_iteracoes` — isto é, desligar o laço de estouro inteiro — deixa folga de 3s. Para o caminho 2 fechar é preciso descer também em `classificar` e `investidor`, que são as únicas chamadas com folga medida abaixo de 4x (9,26s medidos contra 35s, na medição de 16/09/2026). Seria cortar na carne da única medição que o orçamento tem.

**O caminho 1 custa mais que a janela do sweeper.** `job_timeout = 360` arrasta `job_completion_wait` para ~370, e o comentário de `job_timeout` em `workers/main.py` exige do deploy uma carência SIGTERM→SIGKILL acima disso — hoje ~265s, passaria a ~395s. Essa configuração **não mora neste repo**, nenhum teste a cobre, e se o SIGKILL chegar antes a linha fica em PROCESSING com `attempts` congelado — o que o próprio comentário chama de "pior que cancelar na hora".

**O caminho 3 tem um teto duro de 38s.** Fora da montagem o turno paga `reagir` (12s) + `classificar` × 2 (50s) + `investidor` × 2 (70s) = 132s, mais 40s dos outros três clientes. Com `job_timeout = 240` e a reserva de 30s, sobram 38s para a fase de montagem inteira. 35s é a escolha; 40s já não cabe.

Contra os outros dois, o caminho 3 compra a propriedade que a card nomeia: **o pior caso para de crescer com `contexto_max_iteracoes`**. Depois dele o termo dominante é `classificar` + `investidor`, que é irredutível sem decisão de produto.

## D1 — Onde o deadline vive e o que ele cobre

Campo novo em `Settings` (`app/config.py`):

```python
contexto_deadline_de_montagem_segundos: float = 35.0
```

Em `Settings` e não como constante em `infra/anthropic.py` porque `_pior_turno()` já lê `get_settings()`, e os testes de derivação existem para provar que ele lê. Um número solto no módulo de infra voltaria a ser a constante que a TEC-229 acabou de matar.

Dentro de `montar_contexto` (`domain/context/montagem.py`), o deadline envolve **só a fase que fala com o modelo**: da dobra por acúmulo (`deve_regenerar` → `_dobrar`) até o fim do laço `while tokens > teto`, incluindo os quatro sítios que chamam `_truncar_ate_caber`.

As três leituras de banco do início (`ler_resumo`, `literais_apos`, `ler_estado`) ficam **fora**. Elas pertencem à reserva de 30s do banco, e pô-las dentro faria uma lentidão de Postgres consumir orçamento de modelo — duas coisas que o orçamento separa de propósito.

Em `_pior_turno()`, as fatias `(TETO_DO_COUNT_TOKENS, contagens)` e `(TETO_DO_RESUMO, resumos)` saem, e o deadline entra no lugar delas.

**O deadline entra FORA do `* (MAX_TENTATIVAS + 1)`.** Não é detalhe de estilo. Uma retentativa repete uma *requisição* dentro da fase, e a fase já está limitada pelo relógio: multiplicar o deadline por retentativa contaria duas vezes o que o relógio conta uma. Hoje `MAX_TENTATIVAS = 0` e a diferença é invisível — é exatamente por isso que ela precisa estar escrita, e é por isso que um teste a afirma (T4).

**Este é o segundo uso de `asyncio.timeout` no repo, e o primeiro fora do pós-cancelamento.** O único existente está em `workers/jobs/process_message.py`, sob `SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO`, e serve para registrar o FAILED depois que o prazo do ARQ já se foi. O padrão da casa para prazo normal é o `timeout=` do SDK por chamada, com o teto vindo de uma constante `TETO_DO_*`.

Então esta card **abre um segundo padrão** em vez de seguir o que existe, e a razão é a que a card inteira existe para resolver: teto por requisição não limita uma fase que faz N requisições. Está escrito aqui para que a próxima card não conclua que sempre foi assim — e é por isso que o deadline não se chama `TETO_DA_MONTAGEM`: ele não é teto de chamada nenhuma, é relógio de fase.

## D2 — O estouro

`asyncio.timeout` levanta `TimeoutError`. Captura-se **só** ele.

`CancelledError` não é capturado e continua propagando: é o `job_timeout` do ARQ chegando de fora, e a cláusula que a TEC-227 pôs em `process_message` é quem tem de recebê-lo — marcar FAILED, incrementar `attempts`, logar `message.cancelled`. Um `except Exception` largo aqui não pegaria `CancelledError` (é `BaseException`), mas um `except TimeoutError` descuidado pegaria o `TimeoutError` que o `asyncio.wait_for` do ARQ produz para quem chama. Por isso o deadline é o escopo mais estreito possível e a captura é colada nele.

No estouro: `degradado = True`, um `log.warning("contexto.deadline_estourado", ...)` com o canal e o deadline em segundos, e o truncamento sem modelo do D3.

O estado em memória sobrevive porque as variáveis são locais de `montar_contexto`: um `_dobrar` cancelado no meio do `resumir` nunca chegou à atribuição, então `texto_do_resumo` e `literais` ficam com o último valor consistente. Um `_dobrar` cancelado **depois** do `gravar_resumo` deixa no banco um resumo com a marca adiantada enquanto a memória segue com os literais antigos — o turno entrega conteúdo duplicado entre resumo e literais, nunca uma lacuna. Duplicação num caminho degradado é aceitável; lacuna não seria, e é a invariante que a marca d'água existe para comprar.

## D3 — O truncamento sem modelo, e por que ele é pessimista

Esta é a armadilha que a card não enxergou. `_truncar_ate_caber` chama `_contar_se_valer` a cada volta, e `_contar_se_valer` paga um round trip ao modelo quando a estimativa passa do limiar. O caminho degradado pediria ao modelo justamente quando o modelo acabou o tempo.

`_truncar_ate_caber` e `_contar_se_valer` ganham um modo local (`sem_modelo: bool = False`), e o estouro do deadline é o único sítio que o liga.

**A estimativa local não serve como está.** `_estimar` é `len // 4`, e o português acentuado roda a 3,2–3,7 caracteres por token: a estimativa **subconta** em até ~25%. No trânsito normal isso é inofensivo, porque o limiar de 0,6 do teto existe justamente para que o palpite só responda onde errar não muda a decisão. No modo sem modelo ele vira a palavra final — e aí decidir "cabe" com um texto que estoura é o defeito que o modo inteiro existe para não ter.

Então no modo sem modelo a estimativa é **pessimista**, derivada do mesmo piso de 3,2 chars/token que `Settings.limiar_de_contagem_efetivo` já documenta. A consequência é cortar mais literais do que o estritamente necessário: é a direção segura do erro, num caminho que já é degradação declarada.

O que este modo **não** conserta: emoji (~0,3–0,5 chars/token) e blobs base64/URL (~2) continuam descobertos, exatamente como `limiar_de_contagem_efetivo` já declara. Um turno dominado por qualquer um dos dois pode sair medido para menos tokens do que tem, no modo local como no normal. Risco aceito e já documentado; esta card não o move.

**`_estimar` não muda.** A pessimização vive só no ramo `sem_modelo`, e essa fronteira é invariante, não detalhe de implementação: cerca de trinta arquivos de teste rodam `executar_turno` → `montar_contexto` pelo caminho barato da estimativa, nenhum deles com a fixture `sempre_contar`. Mexer em `_estimar` moveria o limiar efetivo dos trinta de uma vez, para um ganho que só o caminho degradado precisa.

`ContextoIrreducivel` continua sendo levantada quando nem uma literal sem resumo cabe. O modo local não muda esse contrato — muda quem mede, não o que se faz com a medida. Ela é capturada num lugar só em produção (`domain/agente/turno.py`, que loga `turno.contexto_irreducivel` e devolve `"sem_resposta"`), e esta card não mexe nisso.

## D4 — Dois testes verdes passam a afirmar o contrário do desenho

A card não previu isto, e é a mudança de contrato mais relevante da branch.

`test_o_pior_turno_segue_contexto_max_iteracoes` e `test_o_pior_turno_segue_o_gatilho_de_regeneracao` afirmam hoje que subir `contexto_max_iteracoes` ou o gatilho **move** o pior caso, com delta exato. Depois desta card isso deixa de ser verdade — e deixa de propósito: é o ganho inteiro do caminho 3, escrito na própria card como *"o pior caso para de crescer com `contexto_max_iteracoes`"*.

Os dois se **invertem** em vez de sumir:

- o pior caso **não** se move quando `contexto_max_iteracoes` sobe;
- o pior caso **não** se move quando `contexto_gatilho_de_regeneracao` dobra;
- o termo da montagem no pior caso é **exatamente** `contexto_deadline_de_montagem_segundos`, e move-se com ele.

Apagá-los perderia a guarda que o arquivo diz existir para impedir a função de voltar a ser constante. Mantê-los como estão seria manter dois testes verdes afirmando o oposto do desenho. Invertê-los guarda a mesma coisa — que a função lê a configuração — sobre a configuração que agora manda.

Saem junto, e o comentário deles já diz que saem "quando a TEC-290 devolver a guarda ao derivado": os dois `xfail(strict=True)`, `SOMA_DE_HOJE_SEGUNDOS`, `JOB_TIMEOUT_DE_HOJE` e `test_o_orcamento_estourado_nao_piora`. O `xfail` estrito faz os dois testes que somam virarem XPASS no instante em que a conta fechar, o que é o mecanismo que a TEC-229 montou para obrigar esta remoção.

## D5 — A prosa que passa a mentir

Cinco sítios, e o quinto está fora do código:

1. `workers/main.py`, comentário de `job_timeout`: a tabela dos 327s e o parágrafo "**Hoje a conta NÃO fecha**" viram a tabela nova, com a linha da montagem sendo o deadline e não a soma das voltas. O parágrafo "Subir este número não é o conserto óbvio" registra qual dos três caminhos foi escolhido e por quê.
2. `infra/anthropic.py`, comentário de `MAX_TENTATIVAS`: afirma "a parcela da Anthropic no pior turno é 287s". Passa a ser 167s. O argumento de zerar a retentativa **não** muda — 167s ainda dobrariam para 334s com uma retentativa, contra 240s —, mas o número citado tem de bater.
3. `infra/anthropic.py`, docstring de `segundos_do_modelo_no_pior_turno`: "Esse teste está `xfail` desde a TEC-229 e não guarda mais nada sozinho" deixa de valer.
4. `tests/unit/test_orcamento_do_turno.py`, docstring de cabeçalho: o parágrafo sobre os 327s e o `xfail`.
5. **SRS.** A emenda E-01 (TEC-161), sob a **RN-09.4**, diz que uma segunda geração cairia *"dentro de um `job_timeout` de 240 s que o pior caso das chamadas atuais já estoura"*. A segunda metade deixa de ser verdade. Entra uma **emenda nova** abaixo da regra, nomeada `Emenda E-02 (TEC-290, 19/09/2026)` — a RN-09.4 só tem a E-01, então a próxima livre é a E-02 —, sem reescrever o texto de 22/08 nem o da E-01. O argumento da E-01 **não cai junto**: a segunda geração continua descartada, agora porque gasta orçamento que voltou a ser escasso, não porque estoura.

`scripts/comentarios_tocados.py` roda antes do PR para pegar o que esta lista não pegou — em particular os `VIZINHO` dentro de `montar_contexto` e de `_pior_turno`, que mudam sem aparecer no diff.

## D6 — O que não muda

`job_timeout` (240), `sweep_inflight_after_seconds` (300), `job_completion_wait` (250), a carência exigida do deploy (~265s) e todos os tetos por chamada de `infra/anthropic.py` ficam exatamente onde estão.

É a razão de ter escolhido o caminho 3 puro, e é o que separa esta branch de uma que precisasse de mudança coordenada fora do repo.

## A superfície que a suíte já prende

Levantada antes de escrever o plano, porque decide o que é mudança de assinatura e o que é mudança de contrato:

- **Nenhum teste importa `_estimar`, `_contar_se_valer` ou `_dobrar`.** A suíte só alcança os três através de `montar_contexto`. Não há assinatura presa a quebrar.
- **`_truncar_ate_caber` é importado e chamado direto** em dois testes de `tests/integration/test_montagem.py`. O parâmetro novo entra com default `False`, e os dois seguem valendo sem edição.
- **As duas invariantes de tempo têm assert próprio**, em `tests/integration/test_worker_startup.py`: `job_timeout < sweep_inflight_after_seconds` e `job_completion_wait > job_timeout`. O D6 não as move, então os dois continuam verdes sem serem tocados — e é essa a evidência de que o caminho 3 não invade o território do caminho 1.
- **Dezessete testes usam `sempre_contar`** (dezesseis em `tests/integration/test_montagem.py`, um em `tests/features/test_janela_de_contexto.py`); são eles que exercitam o laço e a cascata de degraus, e são os que mais sentem o deadline. Os demais rodam pela estimativa barata.

## Testes

| # | afirma | onde |
| --- | --- | --- |
| T1 | a soma dos quatro clientes cabe no `job_timeout` | `test_o_pior_turno_cabe_no_job_timeout`, sem `xfail` |
| T2 | a folga sobre a soma paga os 30s do banco | `test_a_folga_paga_o_banco`, sem `xfail` |
| T3 | o pior caso **não** se move com `contexto_max_iteracoes` nem com o gatilho | os dois testes de derivação, invertidos |
| T4 | o termo da montagem é exatamente o deadline, e não é multiplicado por `MAX_TENTATIVAS + 1` | teste novo em `test_orcamento_do_turno.py` |
| T5 | estourado o deadline, `montar_contexto` devolve contexto abaixo do teto, `degradado=True` e **nenhuma** chamada ao contador depois do estouro | teste novo em `tests/unit/`, com resumidor e contador injetados que dormem |
| T6 | o modo local estima pessimista: um texto que `len//4` diria caber é cortado | teste novo, sobre `_contar_se_valer`/`_truncar_ate_caber` |
| T7 | `CancelledError` de fora atravessa a fase sem virar degradação | teste novo; é o contrato da TEC-227 |

T5 e T7 são o par que importa: um afirma que o deadline pega o que tem de pegar, o outro que ele não pega o que não é dele.

## O que este desenho não entrega

**A folga é de 33s contra um mínimo de 30.** Qualquer teto por chamada que suba depois reabre esta card. O caminho 2 teria deixado 76s e o caminho 1 com `job_timeout = 360` deixaria 33s também — nenhum dos três compra folga larga sem gastar em outro lugar.

**35s é ~1,9x o pior caso medido da montagem** (~18s: 4 resumos de até 3,72s e 11 contagens de até 0,28s, medição de 16/09/2026), abaixo da folga de ~3x que o repo usou para os tetos por chamada. A diferença que justifica: estourar um teto por chamada vira erro tipado, estourar este deadline vira degradação — o turno continua e o lead recebe resposta.

**Nada mede a fase de montagem em produção.** O deadline é declarado a partir do que sobrou depois dos outros termos, não do que a montagem de fato leva. Se ele estourar com frequência, o sinal virá do `contexto.deadline_estourado` no log, e a resposta será uma card nova — provavelmente para reabrir a decisão entre os três caminhos com dado de produção na mão.

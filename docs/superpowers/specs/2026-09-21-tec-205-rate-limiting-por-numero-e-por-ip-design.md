# TEC-205 — Rate limiting por número e por IP

**Status:** desenhado
**Card:** [TEC-205](https://eduardodurieuxlopes.atlassian.net/browse/TEC-205)
**Branch:** `feat/tec-205-rate-limiting-por-numero-e-por-ip`
**Origem:** RNF-16 (SRS v1.0); RT-04. Épico TEC-200 (Segurança, privacidade e conformidade).

## Objetivo

Impedir que um único número de WhatsApp, ou um único IP no widget web, gere volume suficiente para estourar o orçamento de LLM ou monopolizar a fila. O excedente espera; ele não recebe erro.

## O estado antes desta card, conferido no código durante o desenho

Ponto de partida, **não o estado de hoje**. As citações `arquivo:linha` abaixo valem para o código de então; os arquivos vão crescer durante a implementação e alguns números já não vão apontar para a mesma linha depois — não "conserte" para o número atual, porque a frase descreve o passado.

- **Não existia rate limiting de nenhuma espécie.** Nem em `src/`, nem em teste, nem em configuração. O que havia de mais parecido era `antispam_permite_envio` (`domain/outbound/antispam.py:39`), um teto absoluto de mensagens automáticas sem resposta — limite de cadência de saída, não de volume de entrada. Os demais achados de `grep` por `rate|limit|throttle|backoff` eram sobre *receber* 429 de terceiros (Meta, Anthropic), não sobre emitir.
- **Nenhuma chave Redis era escrita à mão.** O único namespace ocupado era `arq:`, da própria biblioteca (`arq:job:msg:<uuid>`, `arq:queue`). Todo acesso a Redis no repo passava pela API do ARQ; nenhum `SET`, `INCR`, `ZADD` ou `EXPIRE` aparecia em `src/`. Não havia, portanto, convenção de prefixo a seguir — esta card institui a primeira.
- **Não existia middleware algum.** `grep` por `middleware|add_middleware|BaseHTTPMiddleware` em `src/` dava zero. `create_app()` (`app/main.py:31-55`) só fazia `include_router` e declarava `/health`; até o `correlation_id` era setado dentro do handler (`api/routes/whatsapp.py:50`), não por middleware.
- **O widget web não existia** — é o TEC-124. A única menção em `src/` era um comentário em `app/logging.py:59-62` antecipando que o widget traria id de sessão ou e-mail. `IngestionService.ingest` já aceitava `channel: str = "whatsapp"` (`domain/messages/service.py:43-45`), então o ponto de extensão existia; o endpoint, não.
- **O mecanismo de atraso já existia, e é o do debounce.** `enqueue_process_message(pool, message_id, *, atraso_segundos)` difere via `_defer_by` do ARQ (`infra/queue.py:19-48`), e `IngestionService.ingest` já escolhia entre atrasar e não atrasar por mensagem (`domain/messages/service.py:55` e `:72`), conforme a RN-01.6 da TEC-128.
- **A invariante de três termos da TEC-128 estava fixada em teste.** `debounce_de_rajada_segundos + job_timeout < sweep_inflight_after_seconds` — hoje `6 + 240 < 300`, folga de 54s — documentada em `workers/main.py:231-244` e fixada por `test_job_timeout_cabe_dentro_da_janela_do_sweeper` (`tests/integration/test_worker_startup.py`). Qualquer espera nova introduzida antes do job entra nessa conta.
- **O padrão de evento era tabela append-only por domínio**, nunca uma tabela genérica. `ModerationEvent` (`domain/moderacao/models.py:24`) é o exemplar mais próximo: `id` UUID, `channel`, `conversation_key`, colunas do evento, `message_id` **sem FK**, `created_at` com `server_default=func.now()`, índice com `created_at DESC`. Não havia outbox (`grep outbox` em `src/` = zero).
- **Não havia configuração sem deploy**, e a lacuna já estava declarada duas vezes, nas duas apontando para o épico RF-19: `domain/followup/cadencia.py:15-19` e `domain/outbound/antispam.py:31-35`.

## Decisões

### D1 — O limite por IP nasce como middleware, e o webhook da Meta fica isento

O card pede 100 req/min por IP "no widget web", e o widget é o TEC-124, que não existe. Havia três saídas: entregar só a função e deixar a aplicação para o TEC-124; cortar o IP do escopo desta card; ou aplicar o limite por IP a todas as rotas HTTP desde já.

A escolhida é a terceira, com uma isenção nomeada. `POST /webhooks/whatsapp` fica **fora** do limitador por IP, porque o tráfego dali chega todo do IP da Meta: 100 req/min naquele ponto não conteria abuso, derrubaria operação legítima — e derrubaria da pior forma possível, já que o handler responde 200 em todo caminho de rejeição justamente para a Meta não re-entregar (`api/routes/whatsapp.py:41-49`). Um 429 ali contrariaria a convenção declarada do arquivo e provocaria exatamente o retry que o desenho da TEC-122 evita.

Com a isenção, o middleware protege as rotas administrativas que já existem — o que torna o critério de aceite do IP exercitável hoje, contra rota real — e o widget nasce protegido no dia em que o TEC-124 registrar o router.

**Consequência aceita:** as rotas administrativas passam a ter teto de 100 req/min por IP. Elas já exigem token de administrador (`api/deps.py:15-41`), então o limite não é a defesa principal delas; é efeito colateral de um middleware que se aplica por omissão em vez de por opt-in. A alternativa — lista de rotas incluídas — erra para o lado de esquecer o widget, que é o erro caro.

### D2 — O excedente por número é adiado, não recusado, e o atraso é fixo

O critério de aceite diz que a vigésima primeira mensagem "entra em backoff" e que "nenhum processamento de LLM é disparado por ela imediatamente". Não diz que ela some. Como `enqueue_process_message` já difere pelo `_defer_by`, o backoff é a troca do atraso: a mensagem excedente é enfileirada com `atraso_de_backoff_segundos` no lugar de `debounce_de_rajada_segundos`. Ela é persistida, vira `QUEUED`, e o turno acontece depois.

O atraso é **fixo e configurável**, não "até a janela abrir". Adiar até o evento mais antigo sair dos 60s seria mais preciso, mas pode chegar a 60s — e a folga da invariante da TEC-128 é de 54s. A versão precisa obrigaria a mexer em `sweep_inflight_after_seconds` e reabrir aquela conta; a fixa cabe embaixo dela.

**A invariante ganha um quarto termo.** `atraso_de_backoff_segundos` substitui `debounce_de_rajada_segundos` no caminho do excedente, então a conta que precisa valer é:

```
max(debounce_de_rajada_segundos, atraso_de_backoff_segundos) + job_timeout < sweep_inflight_after_seconds
```

Com os defaults propostos: `max(6, 30) + 240 = 270 < 300`. A folga cai de 54s para 30s. Isso não fica em prosa: entra como `model_validator` em `Settings`, que recusa subir quando a conta não fecha — do mesmo jeito que `_recusar_horario_de_envio_impossivel` já faz para a janela de envio.

**Por que o adiamento basta como proteção de orçamento.** Adiar não reduz o número de mensagens; reduz o número de *turnos*. O colapso de rajada da TEC-128 (`superada_por_mais_nova`, `domain/messages/rajada.py:22`) já faz a mensagem superada fechar como `"agrupado"` sem chamar o LLM. Empurrar o excedente para 30s adiante engorda o grupo e o LLM é chamado uma vez por grupo, não uma vez por mensagem. O limitador por número é, portanto, uma segunda camada sobre um mecanismo que já corta a maior parte do custo — e é assim que ele deve ser lido quando alguém for medir seu efeito.

### D3 — Janela deslizante em ZSET, com o relógio por parâmetro

O critério de aceite fala em "20 mensagens no último minuto". Janela fixa por `INCR`/`EXPIRE` é mais barata, mas mede "neste minuto de relógio", não "nos últimos 60 segundos": deixa passar até o dobro do limite quando a rajada cruza a borda, e faz o teste do vigésimo primeiro envio depender de onde a borda caiu. Num repo com o histórico de flake deste, comprar flake para economizar dois comandos de Redis é mau negócio.

A escolha é janela deslizante em ZSET, um round-trip com pipeline de quatro comandos:

```
ZREMRANGEBYSCORE chave -inf (agora - janela)
ZADD             chave agora <membro único>
ZCARD            chave
EXPIRE           chave ceil(janela)
```

O `ZADD` vem antes do `ZCARD` de propósito: a requisição em avaliação conta. Com limite 20, a vigésima primeira produz `ZCARD = 21 > 20` e é bloqueada — que é a leitura literal do Gherkin.

Memória: o zset guarda no máximo `limite` membros por chave (20 ou 100) e expira sozinho após a janela. O `EXPIRE` é incondicional a cada consumo, então chave de quem parou de bater some sem varredura.

`agora` entra como parâmetro opcional. Sem isso, o teste do limite precisaria dormir ou mexer no relógio do processo; com isso, os cenários de borda são unitários e determinísticos, no molde de `tests/unit/test_antispam.py`.

### D4 — Falha do limitador é *fail-open*

Se o Redis não responde, `consumir` registra e devolve `permitido=True`. O precedente é a moderação, que devolve `None` em `ModeracaoIndisponivel` e deixa passar (`domain/messages/bloqueio.py:125-132`): um guarda indisponível não pode virar uma negação de serviço que o próprio guarda existia para evitar.

Na prática o caso é quase teórico para o limite por número, porque o enqueue usa o mesmo Redis — um Redis morto já derruba o processamento antes de o limitador opinar. Para o middleware de IP, que roda antes de qualquer enqueue, o fail-open é o que impede o Redis de virar ponto único de falha da API inteira.

### D5 — O evento é tabela própria, uma linha por chave por janela

O critério de aceite — "Quando o evento é consultado / Então constam o número, o momento e o volume" — pede algo consultável, não uma linha de log. Segue o padrão do repo: tabela append-only própria, `rate_limit_events`.

| coluna | tipo | nota |
| --- | --- | --- |
| `id` | UUID, PK | |
| `escopo` | String(8) | `numero` ou `ip` |
| `chave` | String(64) | `conversation_key` ou o IP |
| `channel` | String(32), not null | `whatsapp` ou `web` no escopo `numero`, herdado do `channel` da ingestão; `http` no escopo `ip`, porque ali o bloqueio é de uma requisição à API e não de uma mensagem de canal nenhum |
| `volume` | Integer | a contagem na janela no instante do disparo |
| `limite` | Integer | o limite vigente naquele instante |
| `message_id` | UUID, nullable, **sem FK** | só existe no escopo `numero` |
| `created_at` | DateTime(tz), `server_default=func.now()` | o relógio é o do Postgres |

`message_id` sem FK pela mesma razão escrita em `domain/moderacao/models.py:36-41`: cascata apagaria evidência. Índice `(escopo, chave, created_at DESC)`, no molde de `ix_moderation_events_lead`.

**`limite` fica na linha porque o limite é configurável.** Um evento que guarda só o volume vira ilegível no dia em que alguém mudar a configuração: "volume 21" não diz se houve abuso sem o 20 ao lado. Guardar os dois faz a linha se explicar sozinha anos depois, que é o que uma tabela de auditoria existe para fazer.

**Uma linha por chave por janela, guardada por `SET NX EX`.** Escrever uma linha por requisição bloqueada transformaria o registro de abuso no próprio vetor de abuso: no widget, um atacante escreveria uma linha por requisição, e a defesa custaria mais que o ataque. A guarda é uma chave `ratelimit:evento:<escopo>:<chave>` com `SET NX EX ceil(janela)`; só quem a cria grava a linha. O `volume` gravado é, por consequência, o do primeiro disparo da janela — `limite + 1` no caso comum, que é literalmente "o volume que disparou o limite".

O volume total continua visível: cada bloqueio emite `ratelimit.blocked` no log estruturado, com a chave e a contagem. A divisão é a que o repo já pratica — a tabela é evidência, o log é operação.

### D6 — Configuração por variável de ambiente; "sem deploy" no sentido forte fica com o RF-19

Quatro campos novos em `Settings`:

| campo | default | nota |
| --- | --- | --- |
| `rate_limit_mensagens_por_minuto` | `20` | zero desliga |
| `rate_limit_requisicoes_por_ip_por_minuto` | `100` | zero desliga |
| `atraso_de_backoff_segundos` | `30.0` | entra no validator de D2 |
| `confiar_em_forwarded_for` | `False` | ver D7 |

Zero desliga, seguindo a convenção de `debounce_de_rajada_segundos` (`app/config.py:166-179`).

O card pede o limite "configurável sem deploy". Por variável de ambiente, mudar o limite é reiniciar o processo, não reconstruir a imagem — o que atende à intenção econômica da regra, mas não à letra. A alternativa considerada foi ler um override de uma chave Redis no mesmo round-trip do limitador, o que entregaria a letra por um `SET`. Foi recusada: criaria precedente de configuração não versionada e não auditada, que é decisão do épico de configuração (RF-19), não desta card. A lacuna é declarada aqui, no comentário da card, e na docstring do módulo — como `cadencia.py` e `antispam.py` já fazem para a mesma lacuna.

### D7 — De onde vem o IP, e por que o default é o que quebra atrás de proxy

`request.client.host` é o IP do socket. Atrás de proxy ou ingress, é o IP do proxy — e aí os 100 req/min passam a ser compartilhados por todos os visitantes do widget. Confiar em `X-Forwarded-For` resolveria isso e abriria o buraco simétrico: qualquer cliente forja o header e escapa do limite, que é exatamente o abuso que a card existe para conter.

`confiar_em_forwarded_for: bool = False` resolve por configuração em vez de por adivinhação. Desligado (o default), usa o socket: não spoofável, correto no deploy de hoje, que não tem proxy. Ligado, usa o **último** salto de `X-Forwarded-For` — o último, e não o primeiro, porque é o único que o proxy imediato escreveu e portanto o único que o cliente não controla.

O default é o inseguro-contra-proxy e não o inseguro-contra-spoof porque as duas falhas não custam o mesmo: atrás de proxy sem a chave ligada, o limite fica *mais* apertado do que se quer e alguém reclama; com a confiança ligada por omissão e sem proxy, o limite simplesmente não existe e ninguém reclama. Falha que se anuncia é melhor que falha silenciosa.

### D8 — O IP sai mascarado no log e inteiro na tabela

`app/logging.py:62` já mascara `sender_external_id`, `recipient_external_id` e `conversation_key`, deixando só os 4 últimos caracteres. A regex `_CORRIDA_DE_DIGITOS` (`\d{10,15}`) não pega um IPv4, porque os pontos quebram a corrida — então um IP logado sob outro nome sairia em claro.

`ip` entra em `_CHAVES_MASCARADAS`. A tabela `rate_limit_events` guarda o valor inteiro, porque é ela que precisa responder "quem foi" numa investigação; o log, que vai para agregador e fica muito mais exposto, sai mascarado. Mesma divisão já aplicada a `conversation_key`.

## Fluxo

**Por número**, dentro de `IngestionService.ingest`, no laço por mensagem, imediatamente antes de `_try_enqueue`:

1. `consumir(pool, chave=f"ratelimit:numero:{conversation_key}", limite=..., janela_segundos=60)`.
2. Permitido → `_try_enqueue(..., atraso_segundos=0.0 if pedido else janela)` — o comportamento de hoje, intocado.
3. Bloqueado → `_try_enqueue(..., atraso_segundos=atraso_de_backoff_segundos)`, log `ratelimit.blocked`, e, se a guarda de janela for ganha, uma linha em `rate_limit_events`.

O opt-out e o pedido de humano continuam furando a janela como hoje (`atraso_segundos=0.0`): eles já eram exceção ao debounce e não faz sentido que um limite de volume atrase justamente o pedido de parar de receber mensagens. **Isto é decisão de produto e está registrada como tal** — um abusador que escreva "pare" cem vezes consome cem turnos sem passar pelo backoff, e a defesa contra isso é a máquina de opt-out, não o limitador.

`IngestionService` é o ponto certo porque é por onde toda ingestão passa, de qualquer canal: o widget do TEC-124 já chamaria `service.ingest(parsed, channel="web")` e herdaria o limite por número sem uma linha a mais.

**Por IP**, no middleware, antes de a rota rodar:

1. Rota isenta (o webhook) → passa direto.
2. Resolve o IP conforme D7. Sem IP resolvível → passa (fail-open).
3. `consumir(pool, chave=f"ratelimit:ip:{ip}", limite=..., janela_segundos=60)`.
4. Bloqueado → `429` com `Retry-After: 60`, log `ratelimit.blocked`, e a linha em `rate_limit_events` sob a mesma guarda de janela.

## Testes

- **O limitador é testado contra Redis real, portanto em `tests/integration/test_rate_limit.py`**, não em `tests/unit`. Um dublê de Redis provaria só o dublê: o que este desenho afirma — que quatro comandos num pipeline produzem uma janela deslizante correta — é afirmação sobre o Redis, não sobre a nossa aritmética. Com o `agora` injetado, os casos de borda continuam determinísticos sem dormir: abaixo do limite passa, limite+1 bloqueia, liberar quando o evento mais antigo sai da janela, limite zero desliga, e o TTL é renovado a cada consumo.
- **Em `tests/unit`** fica o que é aritmética pura: o `model_validator` da D2, junto dos demais em `tests/unit/test_config.py`, e a resolução do IP da D7 — escolher entre socket e `X-Forwarded-For` é uma função de cabeçalhos e uma flag, sem I/O.
- **Integração, além do limitador**: o middleware devolvendo 429 na requisição 101 e passando na 100; o webhook não sendo afetado por ele; a ingestão adiando o excedente, medida pelo `score` do zset do ARQ como `tests/integration/test_queue.py:87-111` faz; e a guarda de janela gravando uma linha só para muitos bloqueios.
- **Cenários** (`tests/features/test_rate_limiting.py`): os quatro do card, no padrão de docstring Gherkin de `tests/features/test_debounce_de_rajada.py`.

**Um critério de aceite passa sem exercitar nada.** "Lead legítimo não é punido com erro" envia 5 mensagens e afirma que nenhuma é rejeitada — 5 está muito abaixo de 20, então o cenário passaria mesmo que o limitador não existisse. Ele vai ser escrito como o card pede, e a lacuna vai no comentário da card em vez de o teste ser inflado até fingir cobertura que não tem. Quem exercita o backoff de verdade é o primeiro cenário.

## Fora do escopo

- O endpoint do widget web (TEC-124). Esta card entrega o limite por IP aplicado a todas as rotas menos o webhook; a rota do widget, quando existir, já nasce coberta.
- O corte automático de gasto diário por ambiente e o backpressure da fila (épico E10), explicitamente excluídos pelo card.
- Configuração alterável em runtime (RF-19), ver D6.
- Backoff do sweeper para mensagem que falha sempre — é a TEC-209, declarada em `workers/jobs/sweep_stalled.py:44-48`.

## Emendas ao SRS

**RNF-16** diz "excedente entra em backoff" sem dizer de quem. Emenda a acrescentar em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, aninhada sob a RNF-16:

> **Emenda E-01 (TEC-205, 21/09/2026)** — o backoff é do excedente **por número**, que é adiado e processado depois. O excedente **por IP** recebe `429` com `Retry-After`, não backoff: no widget, a requisição é síncrona e não há o que adiar sem deixar o cliente pendurado. A isenção do webhook do WhatsApp ao limite por IP é parte desta emenda — o IP da Meta é compartilhado por todo o tráfego de entrada e limitá-lo não distingue abuso de operação.

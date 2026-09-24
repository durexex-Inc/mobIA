# TEC-180 — Exportar para CRM via webhook com retry

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-180](https://eduardodurieuxlopes.atlassian.net/browse/TEC-180) — épico TEC-173
**Branch:** `feat/tec-180-exportar-para-crm`
**Origem:** RF-16, RN-16.5 (SRS v1.0); `CrmPort` da seção 4.1; modelo de dados da seção 5.1 (`crm_sincronizado_em`)

## O problema

A esteira do handoff termina na notificação ao corretor. `gerar_resumo` redige o resumo e enfileira `notificar_corretor`, que resolve o destinatário, grava `sla_limite_em` e manda e-mail e WhatsApp. **Nada sai deste sistema para lugar nenhum além disso.** O lead qualificado existe em `handoffs` e em `lead_qualification`, e a imobiliária que já opera num CRM precisa mantê-lo à mão, o que hoje só se faz pelo dashboard.

A RN-16.5 pede a porta (`CrmPort`), o webhook HTTP configurável, o payload JSON versionado, três tentativas com backoff exponencial e — a parte que decide o desenho inteiro — **falha permanente que vira alerta, nunca perda silenciosa**.

Não existe nada de CRM na árvore hoje: a única ocorrência da palavra é um comentário em `domain/handoff/contingencia.py` que antecipa esta card como leitora futura dos marcadores do resumo.

## D1 — A porta é `CrmPort`, e a ausência de webhook é `None` no `ctx`, não um adaptador que finge

A forma é a de `CanalDeNotificacaoPort` (`domain/notificacao/canais.py`): um `Protocol` no domínio, o adaptador real ao lado, e o `startup` do worker decidindo qual instância entra no `ctx`. É o que faz o quarto cenário do Gherkin — *"trocar de destino não exige mudança de código"* — sair por construção: a URL é configuração, e um conector nativo futuro é uma classe nova no mesmo `ctx`.

**Sem `CRM_WEBHOOK_URL`, `ctx["crm"]` é `None`** — e não um `CrmNoop` que registra e não entrega. O repo já tomou essa decisão duas vezes, e nos dois casos o adaptador de mentira foi **apagado**: a TEC-280 matou o `EmailRegistrado` e a TEC-281 matou o registrador de WhatsApp, com a razão escrita em `domain/notificacao/canais.py` — *"manter o adaptador que descarta em silêncio preserva o caminho de volta para ele"*. Escrever um agora seria reintroduzir o padrão que duas cards gastaram esforço para remover.

`None` também é o que o job e a varredura conseguem testar em uma linha, sem precisar perguntar a um objeto se ele é de verdade.

## D2 — Webhook não configurado **desliga** a exportação; não impede o worker de subir

Aqui esta card diverge do precedente mais próximo, de propósito. `workers/main.py` recusa subir sem `SMTP_HOST` e `SMTP_REMETENTE`, com o argumento de que "notificação descartada em silêncio não é menos defeito por acontecer em dev".

**A exportação para CRM não é o mesmo caso, e a própria card diz por quê:** ela é `Should` no MoSCoW, e o texto declara que *"o contorno é exportar manualmente ou trabalhar direto no dashboard durante a POC"*. Uma guarda de startup transformaria uma integração opcional em pré-requisito para rodar o sistema — e o efeito prático seria ninguém conseguir subir o worker até existir um CRM, que é o oposto do que "Should" significa.

O que substitui a guarda, para que desligado não vire silêncio:

- **O `startup` loga uma vez**, em `warning`, que a exportação está desligada e por quê. Uma linha na subida do worker, não uma por handoff.
- **A varredura da D8 não roda** com `ctx["crm"] is None`, então não há fila crescendo às escondidas nem alarme falso sobre handoffs que ninguém tentou exportar.

## D3 — As três tentativas se contam no BANCO, e deixar o ARQ contá-las produziria exatamente a perda silenciosa que a RN-16.5 proíbe

Este é o ponto que decide o desenho, e não é intuição: está na fonte do `arq` 0.28.0 instalado, em `arq/worker.py`, dentro de `Worker.run_job`:

```python
max_tries = self.max_tries if function.max_tries is None else function.max_tries
if job_try > max_tries:
    t = (timestamp_ms() - enqueue_time_ms) / 1000
    logger.warning('%6.2fs ! %s max retries %d exceeded', t, ref, max_tries)
    self.jobs_failed += 1
    ...
    return await asyncio.shield(self.finish_failed_job(job_id, result_data))
```

Estourado o teto, **o ARQ não chama a nossa corrotina**. Ele loga um `warning` próprio, com texto dele, e encerra o job.

A consequência, se as três tentativas fossem `max_tries=3` na inscrição do job: a terceira falha levantaria `Retry`, o `job_try` iria a 4, e o job **acabaria sem que uma linha de código nossa rodasse**. Nada marcaria o handoff, nada emitiria o alerta, e o rastro seria uma linha de `warning` da biblioteca, com o nome do job e nenhum `handoff_id`. É a perda silenciosa da RN-16.5 chegando pela porta que ninguém vigia — e chegando *sempre*, não como caso de borda.

Então:

- **A contagem é `handoffs.crm_tentativas`**, coluna durável, lida e escrita pelo job.
- **Na terceira falha o job NÃO levanta `Retry`.** Ele marca a linha, emite o alerta e retorna um rótulo normal. O desfecho permanente é decisão nossa, tomada por código nosso.
- **O job é inscrito com `max_tries` folgado** (o global do worker, 5), e o teto do ARQ vira rede de segurança para o caso que ele deve cobrir — o worker morrer no meio —, nunca o mecanismo da regra.

O número 3 é constante de módulo, e não configuração: `RN-16.5` fixa três, e um `.env` que o mudasse seria um jeito de violar a regra sem tocar em código revisável.

## D4 — O backoff é `Retry(defer=...)`, e não `asyncio.sleep`

Com base de 30 s e fator 2, as esperas são 30 s e 60 s — 90 s somados, que caberiam no `job_timeout` de 240 s. Cabem e ainda assim não servem: um `sleep` segura o slot do worker parado, e `job_timeout` passa a ter 90 s a menos de folga para o trabalho de verdade, num worker que também roda `process_message`.

`Retry(defer=...)` devolve o job à fila com o atraso no score e libera o slot. É o que o `atraso_de_backoff_segundos` já existente em `app/config.py` faz no outro caminho, pelo mesmo motivo.

A base é configurável (`crm_backoff_base_segundos`, default 30.0) pela razão que `indicador_de_digitacao_apos_segundos` registra em `app/config.py`: o teste precisa injetar centésimos de segundo, e três cenários a 30 s reais custariam minutos por execução da suíte. O **fator** e a **contagem** não são configuráveis — são a regra.

## D5 — O payload é remontado a cada tentativa; não existe tabela de payloads

A card diz *"o payload fica na fila de reprocessamento"*. A fila existe; o payload guardado, não. São duas razões, e a primeira é de privacidade:

**`handoffs.resumo` é `LargeBinary` cifrado com AES-GCM**, com AAD amarrado ao id do handoff por `aad_do_resumo_de_handoff` — e o modelo tem um `@validates` que recusa texto claro na coluna, justamente para que ninguém grave em claro por engano. Uma tabela de fila com o payload em JSON teria o resumo **em claro**, fora do esquema de cifra, numa coluna nova que nenhuma das guardas existentes cobre. Seria mover PII para fora da proteção para ganhar conveniência de reprocessamento.

A segunda razão é a de sempre neste repo: duas fontes para o mesmo fato. Um payload congelado envelhece — o resumo pode ter sido regenerado, a prioridade escalado para `ALTA` (emenda E-01 da RN-16.1) — e o CRM receberia, no reprocessamento, um retrato que já não é verdade.

**A "fila de reprocessamento" é, portanto, a própria linha de `handoffs`**, identificada por `crm_sincronizado_em IS NULL`. Isso vira emenda ao SRS (abaixo), porque muda o significado de uma frase da RN-16.5.

Três colunas novas em `handoffs`, contra a única que a seção 5.1 previa:

| coluna | tipo | porquê |
| --- | --- | --- |
| `crm_sincronizado_em` | timestamptz nulável | o que o SRS já pedia. Nulo é "ainda não entregue", nunca "entregue sem hora" |
| `crm_tentativas` | int, default 0 | a D3. Sem ela a varredura não sabe distinguir "nunca tentei" de "tentei três vezes e desisti", e reenfileiraria para sempre — é o mesmo argumento que `sweep_importacoes_travadas` escreve sobre `importacoes` não ter contador e por isso não reenfileirar |
| `crm_ultimo_erro` | varchar nulável | o nome da classe da exceção, e só |

**`crm_ultimo_erro` guarda o nome da classe e nada mais**, pela regra que a TEC-222 fixou para `messages.last_error` e que `workers/jobs/process_message.py` documenta em `_detalhe_para_a_coluna`: a coluna é durável, em claro, fora da máscara de PII do log. O texto de uma exceção de `httpx` pode carregar a URL, e a URL do webhook é segredo de configuração.

## D6 — Idempotência em duas camadas, porque a nossa sozinha não basta

- **Do nosso lado:** o job sai cedo, sem enviar nada, se `crm_sincronizado_em` já estiver preenchido. Cobre o reenqueue duplicado — o mesmo caso que o `_job_id` derivado já cobre enquanto o job está vivo, e que a L3 do desenho da TEC-177 declarou aberto para depois que ele termina.
- **Do lado do consumidor:** cabeçalho `Idempotency-Key` com o `handoff_id`, e o mesmo id dentro do corpo.

A segunda camada existe porque a primeira tem um buraco que ela não consegue fechar: se o CRM grava o lead e a resposta se perde na volta, nós marcamos falha e retentamos um lead que já entrou. Só a chave de idempotência, do outro lado, distingue isso — e é por isso que o quarto cenário do Gherkin (*"o CRM não recebe o mesmo lead duas vezes"*) não é uma promessa que este repositório consiga cumprir sozinho. Fica dito na lacuna L1.

## D7 — Payload versionado por constante, e assinatura HMAC opcional

`VERSAO_DO_PAYLOAD = 1`, no módulo do payload, no campo `versao` do JSON. O consumidor casa por número, não por formato.

A assinatura reusa `compute_signature`, de `infra/signature.py`, que já calcula `sha256=<hexdigest>` com HMAC — a mesma função com que validamos o webhook de entrada da Meta. **O cabeçalho, porém, é nosso**: `X-Hub-Signature-256` é o nome que a Meta usa para o que ela assina, e reaproveitá-lo na saída confundiria os dois sentidos num grep. Sai como `X-Mobia-Signature-256`.

Sem `CRM_WEBHOOK_SECRET`, não vai assinatura. Assinar é do interesse do consumidor, que precisa ter o segredo para verificar; exigi-lo tornaria o webhook mais difícil de plugar sem tornar nada mais seguro para nós.

## D8 — A varredura é quem faz o terceiro cenário do Gherkin passar

*"Dado um payload na fila de reprocessamento, quando o webhook volta a responder, então o envio é concluído"*. Depois de três falhas o handoff fica `crm_tentativas = 3` e `crm_sincronizado_em` nulo — parado. Algo precisa voltar a tentar quando o CRM se recupera, ou "fila de reprocessamento" é só um nome para "desistimos".

`sweep_crm_pendentes`, cron de baixa cadência, reenfileira os handoffs com `crm_sincronizado_em IS NULL` em duas situações, e ambas precisam existir:

1. **`crm_tentativas >= 3`** — a rodada anterior esgotou. A varredura zera o contador e reenfileira, o que dá uma rodada nova de três tentativas. É o cenário do Gherkin.
2. **`crm_tentativas = 0` e handoff criado há mais que a janela** — o enqueue nunca aconteceu. É o caso do Redis fora do ar no instante em que `gerar_resumo` tentou agendar, que o `try/except` de lá engole de propósito para não perder o resumo já gravado. Sem este ramo, esse handoff nunca seria exportado e nada diria isso.

O `SELECT ... FOR UPDATE SKIP LOCKED` com `LIMIT` é o molde de `sweep_importacoes_travadas`, e pelo mesmo motivo: duas varreduras concorrentes não pegam a mesma linha.

**A varredura não tem teto de rodadas.** Um CRM fora do ar por uma semana produz uma rodada por ciclo de cron, para sempre, e cada rodada termina num `error`. É deliberado: o alerta repetido é o sintoma de que alguém precisa olhar, e parar de tentar seria a perda silenciosa com outro nome. O barulho é o produto.

## D9 — O alerta é um evento de log em `error`, com nome estável

`crm.exportacao_falhou_permanente`, nível `error`, com `handoff_id`, `crm_tentativas` e o nome da classe da exceção.

Não há regra de alerta neste repositório — `domain/outbound/port.py` já escreve isso por extenso: *"não existe regra de alerta neste repositório — ela vive no monitoramento externo, que casa por nome"*. Então o que esta card entrega é o **nome**, e o compromisso de não mudá-lo sem motivo. Este parágrafo e o docstring do job são os dois lugares que dizem qual nome observar.

## D10 — A exportação é enfileirada junto da notificação, e independe de o resumo ter sido gerado

Em `gerar_resumo`, ao lado do `enqueue_job` de `notificar`, com o mesmo `try/except` que não propaga — o resumo já está gravado neste ponto, e uma falha de Redis não pode desfazer isso.

**Independe de `gravou`**, pelo mesmo argumento que a D2 da TEC-177 usou para a notificação: o handoff sem resumo é o que mais precisa chegar a uma pessoa, não um caso a pular. O payload leva `resumo: null` e `resumo_fallback`, e o CRM decide o que fazer com isso.

O Gherkin diz *"dado um handoff criado com resumo pronto"*: é o caminho feliz sendo descrito, não uma condição de exclusão. Tratá-lo como exclusão deixaria de fora justamente o handoff degradado.

## Arquivos

```
src/mobia/domain/crm/__init__.py
src/mobia/domain/crm/port.py             # CrmPort, FalhaDeExportacao
src/mobia/domain/crm/payload.py          # montar(), VERSAO_DO_PAYLOAD
src/mobia/domain/crm/webhook.py          # CrmWebhook, sobre httpx
src/mobia/domain/crm/repositorio.py      # leitura do handoff e as tres marcas
src/mobia/workers/jobs/exportar_crm.py
src/mobia/workers/jobs/sweep_crm_pendentes.py
src/mobia/workers/jobs/gerar_resumo.py   # + o enqueue da D10
src/mobia/workers/main.py                # ctx["crm"], functions, cron_jobs
src/mobia/app/config.py                  # url, secret, timeout, backoff
src/mobia/domain/handoff/models.py       # as tres colunas da D5
alembic/versions/0043_exportacao_para_crm.py
.env.example
```

`payload.py` é separado de `webhook.py` porque é função pura sobre um dossiê — mesmo corte que `domain/handoff/dossie.py` e `contingencia.py` fazem, e que permite testar o formato sem rede.

## Testes

- **`tests/unit/`** — o formato e a versão do payload; o cálculo do backoff por tentativa; a assinatura com e sem segredo; `crm_ultimo_erro` recebendo só o nome da classe (a regra da TEC-222, que nenhum linter checa).
- **`tests/integration/`** — o job inteiro contra um webhook dublê (`httpx.MockTransport`): entrega marca `crm_sincronizado_em`; três falhas marcam o contador e emitem `crm.exportacao_falhou_permanente` em `error`; handoff já sincronizado sai cedo sem tocar a rede; a varredura reenfileira os dois casos da D8 e não reenfileira o que já foi.
- **A D3 tem teste próprio, e é o que mais importa aqui**: depois da terceira falha, a linha do banco está marcada e o evento de alerta saiu. É ele que reprova se alguém "simplificar" a contagem para `max_tries=3` na inscrição do job — mudança que parece equivalente, passa nos outros testes e reintroduz a perda silenciosa.
- **`ctx["crm"] is None`**: o job sai cedo e a varredura devolve 0, sem tocar banco nem rede.

## Emendas ao SRS

**Emenda E-01 à RN-16.5 (TEC-180, 24/09/2026)** — a "fila de reprocessamento" **não guarda payload**; ela é a própria linha de `handoffs` com `crm_sincronizado_em` nulo, e o JSON é remontado a cada tentativa. A regra original sugere uma fila de payloads, e guardá-los exigiria gravar o resumo **em claro** numa tabela nova — `handoffs.resumo` é cifrado com AES-GCM e AAD amarrado ao id, com uma guarda no modelo que recusa texto claro. Guardar o payload moveria PII para fora do esquema de cifra e criaria uma segunda fonte para um fato que envelhece (resumo regenerado, prioridade escalada pela emenda E-01 da RN-16.1). Em consequência, **o modelo de dados da seção 5.1 ganha duas colunas além do `crm_sincronizado_em` que ele já previa**: `crm_tentativas`, sem a qual a varredura não distingue "nunca tentei" de "desisti" e reenfileira para sempre, e `crm_ultimo_erro`, que guarda só o nome da classe da exceção pela regra da TEC-222. Ver a D5 e a D8 do desenho.

**Emenda E-02 à RN-16.5 (TEC-180, 24/09/2026)** — sem `CRM_WEBHOOK_URL` configurada a exportação fica **desligada**, e o worker sobe assim. É divergência deliberada do precedente da TEC-280, em que a falta de `SMTP_HOST` **impede** o worker de subir: aquela regra é `Must` e sem ela o corretor não é avisado, enquanto esta é `Should` e a própria card declara o contorno da POC — *"exportar manualmente ou trabalhar direto no dashboard"*. Uma guarda de startup tornaria uma integração opcional pré-requisito para rodar o sistema. **Consequência declarada:** enquanto ninguém configurar o webhook, nenhum lead é exportado e a mitigação que esta regra representa **não está em vigor** — o que se tem é um aviso único na subida do worker. Ver a D1 e a D2 do desenho.

## Lacunas declaradas

- **L1 — "o CRM não recebe o mesmo lead duas vezes" não é verificável deste lado.** A guarda por `crm_sincronizado_em` cobre o reenqueue; não cobre a resposta perdida depois de o CRM já ter gravado. O que esta card entrega é o `Idempotency-Key`; **quem dedupa é o consumidor**, e nenhum teste daqui prova que ele o faz. O critério de aceite fica exercitado pelo lado que é nosso, e isso precisa estar no comentário da card.
- **L2 — não há webhook de CRM nenhum configurado, e não há como haver por um PR deste repositório.** Mesmo formato da lacuna que a TEC-177 declarou para e-mail e WhatsApp: o destino é cadastro externo. Os testes correm contra `httpx.MockTransport`, e a exportação nasce desligada em toda máquina até alguém apontar uma URL.
- **L3 — o `resumo` vai em claro para fora.** É o que a card pede (*"o payload contém os dados do lead, a qualificação e o resumo"*), e a cifra de `handoffs.resumo` é de repouso, não de trânsito; o TLS do webhook é quem protege o caminho. Fica registrado porque a decisão de exportar PII para um sistema de terceiro é de produto, não de código: **quem configurar a URL está autorizando esse envio**, e nada neste repositório pede confirmação.
- **L4 — sem tabela de auditoria da exportação.** `crm_ultimo_erro` guarda só a última falha; o histórico de tentativas não fica. A trilha imutável é a TEC-206, e é lá que isso cabe.
- **L5 — a varredura não tem teto de rodadas (D8).** Um CRM fora do ar indefinidamente produz um `error` por ciclo de cron, para sempre. É escolha, não esquecimento — mas quem configurar alerta sobre `crm.exportacao_falhou_permanente` precisa saber que ele repete.

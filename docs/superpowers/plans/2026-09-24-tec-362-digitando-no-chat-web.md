# TEC-362 — plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-24-tec-362-digitando-no-chat-web-design.md`
**Branch:** `feat/tec-362-digitando-no-chat-web`

Card de backend, pequena. Os três gates estáticos e a suíte valem inteiros.

## Ambiente

O `.venv` com Python 3.13.14 e os containers já estão de pé desde a TEC-368, nesta mesma sessão. Se for outra máquina, os passos estão no plano daquela card — este checkout não trazia venv nem 3.13.

Baseline desta branch, medido em `7766413` (`main` no momento do corte): **2 failed, 2952 passed**. As duas falhas são `tests/integration/test_motivo_do_erro_de_banco.py` e **são anteriores a esta card** — verificadas na `main` antes de começar. Não confundir com regressão.

## Fase 1 — o contrato

`IndicadorDePresencaPort.indicar_digitacao` ganha `para: str`. Três implementações acompanham:

- `IndicadorNoop` — assinatura nova, corpo igual;
- `WhatsAppIndicador` — recebe e **ignora**, com o porquê escrito (o indicador da Meta é anotação sobre a mensagem recebida, e quem ele precisa é `provider_message_id` mais `de`);
- `WebIndicador` — a implementação nova, na fase 2.

O agendador (`indicador_de_digitacao`) passa `para=message.sender_external_id`.

**A guarda de entrada não ganha `para`.** Hoje ela desiste cedo quando `provider_message_id` ou `de` são nulos. Acrescentar `sender_external_id` ali mudaria o comportamento do WhatsApp — um caso que hoje indica passaria a não indicar —, e a coluna é anulável nas três. Quem precisa dela é só o web, e é lá que a ausência vira log.

**Verificação:** `mypy` é quem pega implementação esquecida — o `Protocol` é estrutural, e uma classe com a assinatura velha deixa de casar.

## Fase 2 — o `WebIndicador`

Em `domain/outbound/web.py`, ao lado do `canal_da_sessao`:

```python
{"tipo": "digitando", "ate": (agora + DURACAO).isoformat()}
```

publicado em `canal_da_sessao(para)`. Sem captura de `RedisError` — o contrato do port manda propagar, e o agendador engole (D5). Sem `para`, loga e volta.

**Verificação:** teste unitário com relógio congelado. `ate` medido, não "perto de 25".

## Fase 3 — a troca no worker

Em `workers/main.py`, `IndicadorNoop()` vira `WebIndicador(ctx["redis"])` — o mesmo pool do `WebOutbound` logo acima, pela razão que aquele comentário já dá.

**E o comentário da lacuna sai.** Ele diz que "esta card nao mexe nesse contrato", e esta mexe. Deixá-lo seria o defeito que o `CLAUDE.md` chama de comentário que mente.

**Verificação:** teste de integração no molde de `test_indicador_de_digitacao.py`.

## Fase 4 — a prosa que a branch tornou falsa

Três lugares, e nenhum deles aparece no diff de código:

1. **`docs/superpowers/specs/2026-09-23-tec-124-widget-web-via-websocket-design.md`** — a D5 declara a lacuna e a seção "O que este desenho não entrega" a repete. Emenda nas duas, com o formato do frame (é o que a card pede ao dizer "registrar o formato na spec da TEC-124").
2. **`docs/srs/srs-agente-sdr-imobiliario-v1.0.md`** — §6.3 lista `{ "tipo": "digitando" }` sem carga; a RN-04.7 descreve só o WhatsApp. Duas emendas, aninhadas, **sem reescrever o texto de 22/08/2026**.
3. **`docs/superpowers/specs/2026-09-19-tec-274-indicador-de-digitacao-design.md`** — a L1 fala da expiração de 25 s como fato do canal da Meta. Passa a valer nos dois, agora por escolha nossa. Emenda.

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Esta branch mexe em `presenca.py`, `web.py`, `whatsapp.py` e `main.py` — arquivos densos em comentário, então `VIZINHO` deve render.

## Ordem de verificação, no fim

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução da suíte, com o hash guardado junto do resultado. **O critério não é "zero falhas": é "as mesmas duas de antes, e nenhuma a mais"** — enquanto o `test_motivo_do_erro_de_banco.py` não for consertado por outra card, é esse o baseline honesto.

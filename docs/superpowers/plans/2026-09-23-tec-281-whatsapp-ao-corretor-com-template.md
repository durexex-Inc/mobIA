# TEC-281 — Plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-23-tec-281-whatsapp-ao-corretor-com-template-design.md`
**Branch:** `feat/tec-281-whatsapp-ao-corretor-com-template`

## Tarefa 0 — O levantamento, feito antes de planejar (executado)

Medido contra a árvore de hoje, e dois achados mudam o escopo:

1. **A TEC-186 já entregou** o `type: "template"` em `outbound/whatsapp.py` e o `whatsapp_templates_aprovados` em `config.py`. A card afirma que faltam; ficou falso no merge dela.
2. **`GuardedOutbound` não serve** para o corretor — as três guardas dele (opt-out por `message_id`, atendimento humano, reserva em `outbound_dispatches`) são todas sobre o lead, e o corretor não tem linha em `messages`.

## Tarefa 1 — `Aviso` substitui a tupla (D2)

`domain/notificacao/mensagem.py`: dataclass congelada com `assunto`, `corpo`, `etiqueta`, `prioridade`, `link`. `montar()` passa a devolvê-la.

`domain/notificacao/canais.py`: a porta vira `enviar(*, destino: str, aviso: Aviso)`.

Atualizar os dois implementadores e o chamador:

- `domain/outbound/email.py` (`EmailSmtp`) — usa `aviso.assunto` e `aviso.corpo`, comportamento idêntico.
- `domain/notificacao/canais.py` (`_CanalQueRegistra`) — some na tarefa 3, mas precisa compilar até lá.
- `domain/notificacao/envio.py` — monta o `Aviso` e o passa ao laço.

**O `corpo` continua fora de todo log**, nos dois canais. A regra não muda por o campo ter mudado de lugar.

## Tarefa 2 — O canal de WhatsApp (D1, D3, D4)

Arquivo novo, `domain/outbound/whatsapp_notificacao.py`, ao lado de `email.py` — é onde o outro canal que entrega de verdade já mora.

- **Não herda de `GuardedOutbound`**, e o comentário diz por quê (D1). Sem isso, a primeira revisão pede a "simplificação" que reintroduz o acoplamento ao lead.
- Monta o corpo de template no formato que `whatsapp.py` já usa (`name`, `language`, `components` com parâmetros de texto) e faz `POST` na Cloud API com o `whatsapp_access_token`.
- Parâmetros: `aviso.etiqueta`, `aviso.prioridade`, `aviso.link`. **Nunca `aviso.corpo`.**
- Erro de rede, timeout ou status não-2xx → `log.warning` (sem `corpo`) e `FalhaDeCanal`.

**Sem template aprovado** (nome vazio, ou fora de `templates_aprovados`): `log.warning` nomeando o motivo e `FalhaDeCanal`. Nunca texto livre — o corretor está sempre fora da janela de 24h, então seria recusa garantida com 131047.

O log antes do `raise` não é redundância: `notificar` só imprime `motivos` quando **nenhum** canal aceita, então com o e-mail entregando a falha do WhatsApp sumiria — pior que o `WhatsAppRegistrado` de hoje, que ao menos loga.

## Tarefa 3 — Configuração e fiação

`app/config.py`: `whatsapp_template_notificacao_corretor: str = ""`, com comentário ligando ao par que a TEC-186 estabeleceu (catálogo em código, aprovação injetada).

`workers/main.py:121`: `WhatsAppRegistrado()` → o canal novo.

**`WhatsAppRegistrado` e `_CanalQueRegistra` são APAGADOS**, não mantidos como alternativa — é o que a TEC-280 fez com o `EmailRegistrado`, e pela mesma razão que o docstring dela registra: deixá-los disponíveis preserva o caminho de volta para o descarte em silêncio.

## Tarefa 4 — Testes

Os quatro cenários Gherkin da card, mais o que o desenho acrescentou:

1. template configurado e aprovado → a Cloud API recebe `type: "template"` com os três parâmetros;
2. o payload **nunca** é `type: "text"`, em nenhum caminho;
3. Cloud API fora → `FalhaDeCanal`, e o e-mail é tentado do mesmo jeito;
4. trocar o nome do template na configuração muda o enviado, sem tocar código;
5. **sem template aprovado → `FalhaDeCanal` E linha de log** (o item que a D3 acrescentou);
6. **o resumo nunca vai no payload** — asserção de ausência sobre o corpo enviado.

**Atenção no item 6:** a guarda da TEC-289 (`test_assercao_de_ausencia_sobre_log.py`) só reduz agulha que seja literal, constante do próprio arquivo ou import de `mobia.*`. Uma agulha vinda do `conftest` reprova aquele meta-teste — foi exatamente o que aconteceu na TEC-226.

Arquivos a atualizar pela mudança de porta: `test_notificacao_canais.py`, `test_notificacao_mensagem.py`, `test_notificacao_envio.py`, `test_email_smtp.py`, `test_notificacao_job.py` e os dubles de canal em `tests/conftest.py`.

## Tarefa 5 — Prosa

- **Emenda ao SRS** (`docs/srs/`), item aninhado sob a RN-16.2: os dois canais não são equivalentes — o WhatsApp leva aviso, o e-mail leva resumo. A card já antecipa que isso vira emenda.
- **Emenda na card**, no comentário: a seção "Metade interna" descreve o estado de 13/09 e a TEC-186 tornou dois dos três itens falsos.
- `canais.py`: a docstring inteira fala do WhatsApp "que continua só registrando". Some junto com o adaptador.

## Verificação

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration tests/features --tb=short
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Integração **por fatias com o banco reiniciado**, e com retentativa do `alembic upgrade head` entre elas: nesta máquina, em 23/09, o Postgres caiu sob `-n 8` e também em execução serial longa, e o `[WinError 64]` pós-restart derruba a fixture de sessão por motivo ambiental.

## Risco declarado

**A mudança de porta é o maior risco desta card, e ela não é o objetivo dela.** Tocar `CanalDeNotificacaoPort` mexe num caminho que hoje entrega e-mail em produção. O critério é que `EmailSmtp` saia com comportamento idêntico — mesmo assunto, mesmo corpo, mesmos cabeçalhos — e que os testes dela passem sem alteração de expectativa, só de forma de chamada. Qualquer teste de e-mail que precise mudar de **expectativa** é sinal de que a refatoração vazou para o comportamento.

**Segundo risco:** o canal novo não tem guarda de opt-out, e isso é deliberado (D1). Se algum dia existir opt-out de corretor, este é o sítio que vai parecer esquecido. O comentário precisa dizer que a ausência é decisão, não descuido.

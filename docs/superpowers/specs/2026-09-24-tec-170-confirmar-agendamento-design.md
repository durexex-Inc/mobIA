# TEC-170 — Confirmar o agendamento e avisar lead e corretor

**Status:** desenho aprovado em conversa, aguardando revisão do texto
**Card:** [TEC-170](https://eduardodurieuxlopes.atlassian.net/browse/TEC-170) — épico TEC-164
**Branch:** `feat/tec-170-confirmar-agendamento`
**Origem:** RF-12, RN-12.1 (SRS v1.0); §4.4 (Google Calendar opcional por flag).

## Objetivo

Depois que um agendamento vira `CONFIRMADO`, fazer três coisas independentes — **avisar o lead**, **avisar o corretor** e **criar o evento na agenda do corretor** — sem que a falha de uma impeça as outras, e sem que nenhuma delas desfaça o agendamento.

## O que esta card não entrega, dito antes

**Nada na conversa confirma agendamento.** Como nas TEC-165 a TEC-168 e na TEC-166: o turno não reconhece pedido de horário, não reserva e não chama `confirmar()`. Esta card entrega o que acontece **depois** da confirmação e a porta para enfileirar isso; quem ligar o agendamento à conversa chama a porta depois do commit do `confirmar`. Até lá, nenhum lead recebe confirmação nenhuma.

**Fora, e continuam esperando:**

- **O gatilho de handoff "agendamento confirmado" (RN-16.1) não é ligado.** `Gatilho.AGENDAMENTO_CONFIRMADO` continua sem chamador. Decidido em conversa em 24/09/2026: abrir handoff silencia o agente naquela conversa até o corretor devolvê-la, e o aviso do handoff não carrega os dados da visita. O corretor é avisado por um aviso próprio (D3), e o agente segue atendendo.
- **Os indicadores de agendamento do painel de funil** continuam `null`/`disponivel: false`. A Emenda E-01 da RN-17.1 diz que eles "voltam com a RF-12"; esta card é parte da RF-12 e não os traz de volta — a consulta que os preencheria conta agendamentos que nenhum caminho de produção cria ainda.
- Lembretes (TEC-171), cancelamento e remarcação (TEC-172).

## D1 — O gatilho é uma porta, e a confirmação continua sendo `confirmar()`

O agendamento **já nasce `CONFIRMADO`** pelo que a TEC-168 construiu: a reserva vira o agendamento quando `confirmar()` a vira. Esta card não mexe em `confirmar()`.

O que ela acrescenta:

- `avisar_confirmacao(session_factory, *, agendamento_id, outbound, email, calendario, agora)` — função de domínio em `domain/agendamento/confirmacao.py`, que faz os três passos da D2.
- Job ARQ `avisar_confirmacao` em `workers/jobs/`, fino, que só a chama com as portas de `ctx`.
- `AgendadorDeConfirmacaoPort` com `AgendadorArq`/`AgendadorNoop`, no molde de `domain/handoff/agendador.py`: `enqueue_job(AVISAR_CONFIRMACAO_JOB, str(id), _job_id=f"confirmacao:{id}")`. O `_job_id` fixo impede dois jobs vivos para o mesmo agendamento.

**Só age sobre `CONFIRMADO`.** Agendamento inexistente, `RESERVADO` ou `EXPIRADO` é um no-op com uma linha de log (`agendamento.confirmacao_ignorada`): o job pode ter sido enfileirado por um caminho que depois não commitou.

## D2 — Três passos independentes

Cada passo abre a própria sessão curta, sem transação aberta durante chamada de rede — o molde de `notificar()` em `domain/notificacao/envio.py`. Cada um em seu `try`; a falha de um vira alerta (D6) e o seguinte roda mesmo assim.

**Idempotência por passo**, para o job poder ser reexecutado à mão sem duplicar nada:

| passo | como sabe que já foi feito |
| --- | --- |
| lead | coluna nova `agendamentos.lead_avisado_em` — a reserva de `outbound_dispatches` por `(message_id, kind)` não basta, porque a chave é a última mensagem do lead, e uma reexecução depois de o lead escrever de novo teria outra chave |
| corretor | coluna nova `agendamentos.corretor_avisado_em` |
| calendário | coluna nova `agendamentos.calendar_event_id` |

**Sem retentativa automática.** Uma falha fica no log de erro e na coluna vazia; reexecutar o job refaz só o que falta. Retentativa com contagem, no molde de `exportar_crm`, é superfície que a card não pede.

## D3 — As mensagens

**Ao lead** — `TEXTO_DA_CONFIRMACAO` (e `TEXTO_DA_CONFIRMACAO_REMOTA`), português **com acento** (TEC-267), registrados em `tests/unit/literais_ao_lead.py`:

- Visita: data e hora por `data_e_hora_absolutas` (TEC-167), o endereço (D4) e o nome do corretor.
- Reunião remota: data e hora, "reunião remota" e o nome do corretor; sem endereço.

Envio por `outbound.send` com `kind` próprio (`KIND_DA_CONFIRMACAO = "confirmacao_de_agendamento"`), ancorado na **última mensagem do lead** — o molde de `_avisar_lead_da_janela_humana`, pelo mesmo motivo que a docstring dela explica (o `"de"` sai do número certo). Sem mensagem do lead na conversa, o passo é pulado com log. A mensagem **não promete** o que não está garantido: não diz que o corretor "já recebeu", porque um canal aceitar não é entrega (lição registrada em `envio.py`).

**Ao corretor** — e-mail pelo `EmailSmtp` que já existe (TEC-280), ao `corretor.email`, com um `Aviso` montado para isto: assunto com data e hora, corpo com data, hora, tipo, imóvel e endereço (D4), identificação do lead (canal e `conversation_key`) e o link da transcrição por `link_da_transcricao`. `etiqueta` e `prioridade` vêm de `ETIQUETA_DE`/`PRIORIDADE_DE` para `Gatilho.AGENDAMENTO_CONFIRMADO`, o vocabulário que já existe para este fato.

**O template de WhatsApp não é usado**: ele só carrega etiqueta, prioridade e link, e a card exige os dados da visita. Aviso ao corretor por WhatsApp com esses dados precisaria de um template novo aprovado pela Meta — fora desta card.

## D4 — O endereço é o que o catálogo tem

`Imovel` não tem logradouro, número nem CEP. O endereço da mensagem é montado do que existe:

> `<título>` (cód. `<código>`) — `<bairro>`, `<cidade>`/`<UF>`

O corretor passa o número exato na conversa com o lead. **Divergência declarada** em relação ao "endereço do imóvel" da RN-12.1; acrescentar logradouro ao catálogo mudaria também a ingestão, que ninguém pediu. Decidido em conversa em 24/09/2026.

Visita com `imovel_id` nulo — o schema permite — sai sem a linha do imóvel, só com data, hora e corretor.

## D5 — O calendário: um organizador que convida

`CalendarioPort` com `criar_evento(*, inicio, fim, titulo, descricao, convidado) -> str | None` (o id do evento, ou `None` quando a integração está desligada), e dois adaptadores:

- **`GoogleCalendar`**, sobre `httpx` puro com cliente injetável (o molde de `WhatsAppTemplate`), sem biblioteca Google nova. Uma conta Google da imobiliária é a **organizadora**: com o refresh token OAuth dela, troca por access token (`POST https://oauth2.googleapis.com/token`) e cria o evento na agenda dela (`POST .../calendars/{calendar_id}/events?sendUpdates=all`) com o e-mail do corretor em `attendees`. O Google envia o convite e o evento aparece na agenda do corretor — com qualquer conta de e-mail, sem Workspace nem delegação. Decidido em conversa em 24/09/2026.
- **`CalendarioNoop`** — não faz chamada nenhuma e devolve `None`, que é o "nenhum evento criado" da porta (`criar_evento` devolve `str | None`).

**A flag é a credencial vazia**, a convenção do repo (`crm_webhook_url`): `Settings.google_calendar_refresh_token` vazio faz o `startup` do worker pôr `CalendarioNoop` em `ctx` e emitir um único aviso (`agendamento.calendario_desligado`). Os outros campos: `google_calendar_client_id`, `google_calendar_client_secret`, `google_calendar_id` (padrão `primary`).

O evento leva `start`/`end` com `timeZone` do fuso da imobiliária, título com tipo e imóvel, descrição com a identificação do lead e o link da transcrição. O id devolvido vai para `calendar_event_id` (`String(120)`, o nome e o tamanho do modelo de dados do SRS).

## D6 — Alerta é log estruturado

Não existe sistema de alerta no repo; alerta é `log.error` com nome estável, que o monitoramento externo casa (TEC-177 D7):

- `agendamento.calendario_falhou`
- `agendamento.aviso_ao_corretor_falhou`
- `agendamento.aviso_ao_lead_falhou`

Cada um com `agendamento_id` e o tipo da exceção, nunca o corpo da resposta do Google (pode ecoar credencial). Em todos os casos o agendamento continua `CONFIRMADO`: nenhum passo escreve em `status`.

## D7 — Migration 0046

`agendamentos.calendar_event_id String(120) NULL`, `agendamentos.corretor_avisado_em timestamptz NULL` e `agendamentos.lead_avisado_em timestamptz NULL`. Nulos porque o passo pode falhar, e nulo é o registro de que falhou. `lead_avisado_em` só é gravado quando o `outbound.send` aceita; recusa da guarda (opt-out, atendimento humano) fica nula e em log.

## Testes

**Unitários:**

- Os textos ao lead: visita com imóvel, visita sem imóvel, reunião remota; data e hora absolutas no fuso local.
- O `Aviso` ao corretor: contém data, hora, endereço, identificação do lead e link.
- `GoogleCalendar` contra `httpx.MockTransport`: troca de token, corpo do evento (convidado, `sendUpdates=all`, fuso), id devolvido; 5xx e erro de rede viram exceção de canal.

**Integração** (Postgres, portas falsas):

- Agendamento confirmado → lead recebe, corretor recebe, evento criado, colunas preenchidas.
- Calendário indisponível → lead e corretor avisados, `calendar_event_id` nulo, `status` `CONFIRMADO`, `agendamento.calendario_falhou` no log.
- Flag desligada (`CalendarioNoop`) → nenhuma chamada ao calendário, fluxo termina normalmente.
- Reexecução → nada é repetido.
- Agendamento `RESERVADO`/`EXPIRADO`/inexistente → no-op.

## Emendas ao SRS

- **RN-12.1** — o endereço é bairro, cidade e UF do imóvel, com título e código, porque o catálogo não tem logradouro (D4); o corretor é avisado por e-mail, não por WhatsApp (D3).
- **RN-16.1** — o gatilho "agendamento confirmado" continua sem ligação, com o porquê (abrir handoff silencia o agente).
- **RN-17.1** — os indicadores de agendamento continuam nulos depois desta card, e o motivo.

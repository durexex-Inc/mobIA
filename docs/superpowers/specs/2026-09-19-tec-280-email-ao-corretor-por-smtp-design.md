# TEC-280 — A notificação ao corretor sai por SMTP de verdade

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-280](https://eduardodurieuxlopes.atlassian.net/browse/TEC-280)
**Branch:** `feat/tec-280-email-ao-corretor-por-smtp`
**Origem:** Emenda E-02 da RN-16.2 (TEC-177, 12/09/2026), que declarou a dependência externa em vez de fingir que ela não existia.

## Objetivo

Fazer o corretor ser avisado. Oito cards do épico TEC-173 estão em Feito — o handoff é registrado, o resumo é redigido, a contingência existe, o destinatário é resolvido, o prazo é contado, a escalada funciona — e **nada disso chega a uma pessoa**, porque `EmailRegistrado.enviar` faz uma coisa só: `log.info("notificacao.nao_entregue")`.

## A decisão de produto que destravou a card

A card estava bloqueada por uma escolha que não era de engenharia: qual provedor. Decidida em 19/09/2026: **SMTP direto, via `aiosmtplib`.**

A razão que desempatou não estava na card, porque é posterior a ela: **a TEC-219 (publicar em cloud) continua em "A fazer"**. Escolher SES hoje presumiria AWS antes da card que decide a nuvem. Com SMTP, todo provedor — SES, Resend, Postmark, Mailgun — passa a ser **configuração e não código**: a escolha de vendor pode esperar a TEC-219 sem bloquear a entrega.

O custo, declarado: perde-se webhook de bounce e template do provedor. Nenhum dos dois está no escopo desta card, e ambos continuam possíveis depois — um adaptador de API conviveria com este, já que a porta é a mesma.

## Decisões

### D1 — O adaptador mora em `domain/outbound/`, e `EmailRegistrado` é apagado

`src/mobia/domain/outbound/email.py`, ao lado de `whatsapp.py`, que é onde este repo põe adaptador que fala com serviço externo. `canais.py` fica com a porta `CanalDeNotificacaoPort`, com `FalhaDeCanal` e com `WhatsAppRegistrado`, que continua sendo verdade: aquele canal ainda espera template aprovado pela Meta.

**`EmailRegistrado` é removido, não mantido.** Deixá-lo disponível cria o caminho de volta para o descarte em silêncio que esta card existe para matar — bastaria alguém plugá-lo de novo num dia ruim.

O ponto de composição é um só e é literal: `ctx["canais_de_notificacao"] = (EmailRegistrado(), WhatsAppRegistrado())`, em `workers/main.py`. É ali que o adaptador novo entra.

### D2 — A guarda de partida é incondicional

O repo tem dois moldes de guarda em `startup()`:

| molde | exemplo | comportamento |
| --- | --- | --- |
| incondicional | `WHATSAPP_ACCESS_TOKEN` | levanta `ConfiguracaoInsegura` sempre que faltar |
| condicional | `OPENAI_API_KEY` | só recusa subir `em_producao`; em dev, avisa uma vez |

**Esta card usa o incondicional.** O critério de aceite diz "dado um ambiente sem a configuração do provedor de e-mail, quando o worker inicia, então ele falha na partida" — sem qualificar ambiente.

E o argumento é mais que literalismo: condicionar a produção deixaria o ambiente de desenvolvimento convivendo exatamente com o defeito que a card existe para matar. A notificação descartada em silêncio não é menos defeito por acontecer na máquina de quem desenvolve; é só menos visível, que é pior.

O custo é real e assumido: quem sobe o worker precisa do Mailpit de pé. O precedente diz que este repo aceita esse custo — hoje já é preciso ter `WHATSAPP_ACCESS_TOKEN` para subir.

### D3 — Mailpit no compose, e nenhum default de host no código

Serviço novo no `docker-compose.yml`, com healthcheck no padrão dos dois que já existem. O `.env` de desenvolvimento aponta `SMTP_HOST` para ele.

**Nenhum default de host no `Settings`.** Um `smtp_host: str = "localhost"` faria o worker subir em qualquer lugar e falhar só na hora da entrega — o fallback silencioso de volta pela porta dos fundos, agora disfarçado de conveniência. O campo nasce `""`, e a guarda da D2 é quem reprova.

Campos novos em `app/config.py`, no molde dos existentes (`pydantic-settings`, sem prefixo, sem `SecretStr` — o repo não usa `SecretStr` em nenhum lugar hoje, e esta card não é a de mudar essa convenção):

| campo | default | razão |
| --- | --- | --- |
| `smtp_host` | `""` | sem default utilizável; a guarda reprova |
| `smtp_porta` | `587` | submission com STARTTLS é o caso de produção |
| `smtp_usuario` | `""` | Mailpit não pede autenticação |
| `smtp_senha` | `""` | idem |
| `smtp_remetente` | `""` | sem default: remetente errado queima reputação de domínio |
| `smtp_starttls` | `True` | seguro por padrão; o dev desliga para o Mailpit |

`smtp_remetente` entra na guarda junto com `smtp_host`: host sem remetente não entrega.

### D4 — Sem retentativa dentro do adaptador

A primeira recusa vira `FalhaDeCanal`. Duas razões:

1. **A política já existe uma camada acima.** O orquestrador marca `aviso_manual_pendente` sem cancelar o outro canal, e a TEC-279 recupera o que a fila perde. Retentar aqui duplicaria essa decisão em dois lugares, que é como elas passam a divergir.
2. **Retentativa cega arrisca entrega dupla.** Um `250 OK` que se perde na volta é indistinguível, do lado do cliente, de uma recusa — e reenviar manda o resumo do lead duas vezes para o corretor.

Um **timeout explícito** acompanha a decisão: sem ele, um servidor pendurado segura o job do ARQ pelo tempo que quiser.

### D5 — O que vira `FalhaDeCanal` e o que sobe

`SMTPException` (a base de `aiosmtplib`), `OSError` (recusa de conexão, DNS) e `TimeoutError` viram `FalhaDeCanal`.

`TypeError` e `AttributeError` **sobem**. Não é detalhe: é textualmente a razão que a docstring de `FalhaDeCanal` dá para ela existir — *"sem ela, um `except Exception` no orquestrador engoliria TypeError e AttributeError como se fossem falha de entrega, e o handoff sairia marcado como pendente de aviso manual por um bug que ninguem veria"*. Um `except Exception` no adaptador novo reintroduziria o problema um nível abaixo.

### D6 — O corpo nunca vai para log, e a mensagem vai como `EmailMessage`

O `corpo` carrega o resumo, que é prosa destilada do que o lead escreveu — a mesma razão pela qual `handoffs.resumo` é cifrado em repouso. `destino` e `assunto` podem ir para log, como já vão hoje.

A mensagem é montada com `email.message.EmailMessage` e UTF-8 explícito, não com concatenação de cabeçalhos. O resumo é escrito pelo modelo e vem acentuado; montar cabeçalho à mão é precisamente como se produz mojibake no assunto e no corpo.

**`aiosmtplib` não pode entrar em modo de depuração**, que imprimiria o diálogo SMTP inteiro — corpo incluído — no log.

### D7 — O teste sobe um servidor SMTP de verdade, em processo

`aiosmtpd` como dependência de desenvolvimento, servindo numa porta efêmera durante o teste.

O precedente do repo para adaptador externo é `httpx.MockTransport`: finge a **borda de rede**, não a função. `aiosmtpd` é o equivalente para SMTP — o adaptador fala o protocolo de verdade e o teste lê a mensagem que chegou do outro lado.

O ganho sobre um monkeypatch de `aiosmtplib.send` não é estético. Um monkeypatch prova que chamamos uma função com certos argumentos; o servidor em processo prova o que o critério de aceite pede — **que a mensagem chega, no endereço certo, com resumo e link no corpo** — e pega a classe de defeito que o monkeypatch não pega: acento estropiado no transporte.

### D8 — Três comentários passam a mentir e mudam junto

Esta card torna falsa a prosa que descrevia a ausência dela:

- **`domain/notificacao/canais.py`**, docstring de módulo: *"Os dois adaptadores registram e nao entregam"* — passa a ser um. O parágrafo sobre e-mail sai; o do WhatsApp fica, porque continua verdade.
- **`domain/notificacao/mensagem.py`**: *"Sem dano hoje -- nenhum canal entrega nada a corretor nenhum (D4) -- mas o dia em que um adaptador real existir, a E8 tem de existir junto."* O dia é hoje. Ver a lacuna declarada abaixo.
- **`domain/notificacao/envio.py`**, o bloco que descreve o mesmo estado.

## A lacuna que esta card entrega de propósito, e que é decisão de produto

**O e-mail vai carregar um link que não resolve.**

`link_da_transcricao` monta `dashboard_base_url/conversas/{canal}/{conversa}`, e o destino é o dashboard — a E8, cujas cards (TEC-190 a TEC-194) estão todas em "A fazer". O comentário em `mensagem.py` já avisava que *"o dia em que um adaptador real existir, a E8 tem de existir junto"*.

A card decide aceitar: *"o dashboard é a E8 e não existe, então o corpo continua levando o link da transcrição que `link_da_transcricao` já monta"*. Este desenho segue a decisão dela.

**O efeito prático, dito sem rodeio:** o corretor recebe um e-mail que diz "Conversa completa: &lt;link&gt;" e o link não abre nada. Isso é melhor que o estado de hoje, em que ele não recebe e-mail nenhum, e é pior do que a RN-16.2 promete. Não é conserto desta card, e vai para o comentário dela.

## Testes

1. **O corretor recebe.** Servidor SMTP em processo; a notificação executa; a mensagem que chega tem o endereço do corretor no envelope, e o corpo contém o resumo e o link.
2. **Acento sobrevive ao transporte.** Resumo com acento entra, e o que o servidor recebe, decodificado, é o mesmo texto. É o teste que justifica a D7.
3. **Falha não cancela o outro canal.** Servidor indisponível; o canal levanta `FalhaDeCanal`; o handoff fica com `aviso_manual_pendente`; o canal de WhatsApp é tentado do mesmo jeito.
4. **Defeito de programação sobe.** `TypeError` de dentro do envio não vira `FalhaDeCanal` — trava a D5.
5. **O resumo nunca aparece no log.** Entrega bem-sucedida; nenhum registro contém o texto do resumo.
6. **Sem configuração, o worker não sobe.** `SMTP_HOST` vazio faz `startup` levantar `ConfiguracaoInsegura` com a razão escrita; idem `smtp_remetente`.
7. **Timeout vira `FalhaDeCanal`**, não travamento.

## Fora de escopo

- A entrega por WhatsApp ao corretor (TEC-281): depende de template aprovado pela Meta.
- O dashboard (E8) e o link que resolve.
- Webhook de bounce e template de provedor — possíveis depois, pela mesma porta.
- Trocar `str` por `SecretStr` nos campos de credencial: o repo não usa `SecretStr` em lugar nenhum, e mudar a convenção no meio desta card misturaria dois assuntos.

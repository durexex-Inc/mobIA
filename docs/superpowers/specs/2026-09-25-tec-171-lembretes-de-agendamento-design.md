# TEC-171 — Enviar lembretes de 24 e 2 horas

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-171](https://eduardodurieuxlopes.atlassian.net/browse/TEC-171) — épico TEC-164
**Branch:** `feat/tec-171-lembretes-de-agendamento`
**Origem:** RF-12, RN-12.2, CA-12.1 (SRS v1.0). Bloqueada por TEC-170, que mergeou em 25/09/2026.

## Objetivo

Um agendamento `CONFIRMADO` faz o lead receber dois lembretes — um 24 horas antes, outro 2 horas antes —, cada um uma única vez, sem que reprocessamento duplique e sem que um agendamento que deixou de valer receba os lembretes antigos.

## O que esta card não entrega, dito antes

**Nada lê a resposta do lead ao lembrete.** O de 24 horas oferece confirmar, remarcar ou cancelar, como a RN-12.2 manda — e nenhuma das três respostas é lida por lugar nenhum. O lead responde, a resposta cai na conversa normal, e o agente não tem ferramenta de agendamento: `domain/agente/turno.py` não importa nada de `domain/agendamento/`, e a TEC-170 já declarou essa ausência. O quinto cenário do Gherkin da card ("resposta ao lembrete atualiza o agendamento") **fica sem teste**, porque exercitá-lo exigiria construir o caminho de conversa que não existe. Decidido em conversa em 25/09/2026: o texto oferece os três mesmo assim, porque a card é a fonte de requisitos e duas das três ações são a TEC-172.

**Continua valendo o que a TEC-170 declarou:** nenhum caminho de produção chama `confirmar()`. Um agendamento só existe se alguém o criar à mão ou por teste, e por isso **nenhum lead recebe lembrete nenhum hoje**. Esta card constrói a régua; quem ligar o agendamento à conversa a põe em uso.

**Fora, e continuam esperando:**

- Cancelamento, remarcação e não comparecimento (TEC-172). Os status `CANCELADO`, `REAGENDADO`, `REALIZADO` e `NO_SHOW` da RN-12.5 não existem — `StatusDoAgendamento` tem três valores, e "cancelado" não é um deles. O quarto cenário do Gherkin ("agendamento cancelado não recebe lembrete") é exercitado contra `EXPIRADO`, que é o único status não-confirmado que existe hoje; ver a D2.
- Lista de espera sem disponibilidade em 72 horas (TEC-169).
- Os indicadores de agendamento do painel de funil, que a Emenda E-01 da RN-17.1 deixou `null`/`disponivel: false`. Esta card não cria agendamento nenhum, então continuam.

## D1 — Uma varredura, e não um job diferido por agendamento

O ARQ sabe adiar um job (`_defer_until`), e seria tentador enfileirar dois na hora da confirmação. **Não serve**, e a razão é a próxima card: um agendamento cancelado ou remarcado não pode receber o lembrete antigo (regra da card, RN-12.3), e um job já na fila não se desmarca — quem o escrevesse teria de lembrar de cancelá-lo em cada caminho que mexe no agendamento, e o caminho que esquecer manda a mensagem.

A varredura lê o estado de **agora**. Um agendamento que deixou de ser `CONFIRMADO` simplesmente não aparece na consulta, sem que nada precise ser desfeito — e a TEC-172 ganha a regra de graça, sem tocar nesta card.

`sweep_lembretes`, no molde de `sweep_crm_pendentes`: `SWEEP_LEMBRETES_JOB` em `workers/jobs/sweep_lembretes.py`, em `functions` com `keep_result=0` e em `cron_jobs`.

**De 5 em 5 minutos**, como `sweep_followups`, `sweep_sla` e `sweep_importacoes_travadas`, e não de 30 em 30 segundos como `sweep_stalled`: a menor janela desta regra é de **duas horas** (a faixa do lembrete de 2h, D2), então precisão de segundos não compra nada e custaria uma varredura a cada passagem. O erro máximo de disparo fica em cinco minutos sobre uma janela de duas horas.

## D2 — Um lembrete é devido numa FAIXA, e a faixa tem teto

Cada lembrete tem uma antecedência e um marco seguinte:

| lembrete | devido a partir de | devido até (exclusivo) |
| --- | --- | --- |
| 24 horas | `inicio - 24h` | `inicio - 2h` |
| 2 horas | `inicio - 2h` | `inicio` |

**O piso é o que a CA-12.1 pede**: "agendamento confirmado para daqui a 26 horas, quando o relógio chega a 24 h antes, então o lembrete é enviado". Com o cron de 5 em 5 minutos, "chega a" significa "a primeira passagem em que `now() >= inicio - 24h`".

**O teto é a parte que não é óbvia, e sem ele a regra mente.** Sem limite superior, um worker parado por três horas faria a passagem seguinte mandar o lembrete de 24 horas **junto** com o de 2 horas — e "você consegue ir? dá para remarcar" noventa minutos antes da visita é outra mensagem, não a mesma atrasada. O teto de cada faixa é o marco do lembrete seguinte, o que dá 22 horas de folga ao de 24h e 2 horas ao de 2h: cabe qualquer indisponibilidade plausível, e a mensagem nunca sai depois de ter deixado de fazer sentido.

**E há uma terceira condição, que é o caso do agendamento confirmado em cima da hora:** `confirmado_em < inicio - antecedencia`. Um agendamento confirmado três horas antes da visita tem `now() >= inicio - 24h` verdadeiro no instante em que nasce — sem esta condição, o lead receberia a confirmação da TEC-170 e, minutos depois, um "lembrete de 24 horas". **Um lembrete cujo momento já tinha passado quando o agendamento foi confirmado nunca existiu**: a mensagem de confirmação já levou data, hora, endereço e corretor, que é o conteúdo que o lembrete repetiria.

**A consulta é PRÉ-FILTRO, e a regra acima é a única fonte.** O SQL seleciona `status = 'CONFIRMADO'` (é ele que exclui o cancelado da TEC-172 e o `EXPIRADO` de hoje), `confirmado_em IS NOT NULL`, pelo menos uma das duas colunas nula, e a janela grosseira `agora < inicio <= agora + 24h` — derivada da maior antecedência, não escrita à mão. Quem decide se um lembrete é devido é `lembrete_devido`, em Python. Escrever as três condições de tempo uma segunda vez em SQL seria o defeito de duas fontes da TEC-146.

**E sem `FOR UPDATE SKIP LOCKED`, ao contrário de `sweep_crm_pendentes`** (decidido na implementação, contra a primeira versão desta D2). Lá o claim é uma escrita na mesma linha que o `SELECT` trava, e o lock morre no commit antes do enqueue; aqui o que vem depois da leitura é um POST para a Meta, e segurar lock de linha durante chamada de rede é a contenção que este repo já pagou caro. Quem impede duas varreduras concorrentes de mandarem o mesmo lembrete é a `UNIQUE (message_id, kind)` de `outbound_dispatches`: a segunda recebe `False` de `send` — o mesmo desfecho de uma guarda que recusou — e grava a coluna sem mandar nada.

## D3 — Idempotência em duas camadas

**Migration 0048**: `agendamentos.lembrete_24h_em` e `agendamentos.lembrete_2h_em`, `timestamptz NULL`, no molde exato das três colunas que a 0047 criou.

A coluna quer dizer **"este lembrete está resolvido"**, e não "foi entregue" — quem registra entrega é a linha em `outbound_dispatches`. Ela é gravada em dois desfechos, e nulo é o terceiro:

| desfecho de `send` | coluna | log |
| --- | --- | --- |
| aceito (`True`) | gravada | `lembrete.enviado`, `info` |
| recusado pela guarda (`False`) | **gravada** | `lembrete.recusado`, `info` |
| exceção de canal | **nula** | `lembrete.envio_falhou`, `warning` |

**O `False` gravar é onde esta card diverge da TEC-170, e é por causa do cron.** Lá o job roda uma vez por enfileiramento, e deixar a coluna nula custa nada. Aqui a passagem se repete a cada cinco minutos: um lead em opt-out, ou uma conversa que um corretor assumiu, produziria uma tentativa barrada a cada cinco minutos por até vinte e duas horas — 264 linhas de `outbound.optout_bloqueou` em `warning` por um lembrete que nunca vai sair. A guarda já respondeu; repetir a pergunta não muda a resposta.

**A exceção deixar a coluna nula é o oposto, e também é deliberado:** falha de rede é o caso em que retentar resolve, e a faixa da D2 é o que a limita — a passagem seguinte tenta de novo, e quando a faixa fecha a linha deixa de aparecer na consulta. Sem retentativa contada, sem `max_tries` próprio: a faixa é o teto.

**A segunda camada é o `kind`**, que é o que impede duas varreduras concorrentes de mandarem o mesmo lembrete no intervalo entre o `SELECT` e o `UPDATE`. Um `kind` por agendamento e por lembrete, pelo mesmo motivo que `kind_da_confirmacao` documenta — a âncora é a última mensagem **do lead**, e dois agendamentos do mesmo lead cairiam na mesma linha de `messages`:

```
lembrete_24_<20 primeiros do hex do id>
lembrete_02_<20 primeiros do hex do id>
```

Doze caracteres de prefixo mais vinte de hex fecham os trinta e dois de `outbound_dispatches.kind`, a mesma conta de `confirmacao_`. Os dois prefixos têm o mesmo comprimento de propósito: `_02_` e não `_2_` para que a aritmética seja uma só.

**Nenhum dos dois entra em `_GRUPOS`** (`outbound/kinds.py`), pela mesma razão que `KIND_DO_FOLLOWUP` não entra: cada lembrete é uma mensagem própria, e liberar a reserva do de 24 horas porque o de 2 falhou reabriria o envio de algo que o lead recebeu no dia anterior.

## D4 — O canal: a janela de 24 horas mora em `outbound/`, não em `followup/`

Fora da janela de serviço da Meta só sai template aprovado — é a mesma regra que a TEC-186 já resolveu para o follow-up, e a card manda o lembrete respeitá-la. A decisão daqui é sobre **onde a regra mora**.

`dentro_da_janela` e `JANELA_DE_SERVICO` estão hoje em `domain/followup/template.py`. **Mudam para `domain/outbound/janela.py`**, pelo argumento que `domain/outbound/horario.py` já escreveu sobre si mesmo, palavra por palavra: a regra é do canal, não do follow-up, e sob `followup/` a próxima card não a acharia e escreveria a segunda — que é a forma exata do defeito de duas fontes que a TEC-146 gastou uma card inteira consertando. A própria docstring de `dentro_da_janela` aponta para `outbound/whatsapp.py` como o outro lugar onde a janela aparece.

`followup/template.py` e `sweep_followups.py` passam a importar do lar novo. A função não muda — nem assinatura, nem corpo, nem docstring.

**O catálogo de templates do lembrete é próprio**, em `domain/agendamento/lembretes.py`, e não uma categoria nova no `TEMPLATES` do follow-up: as três categorias de lá (`queda_de_preco`, `imovel_novo`, `convite`) são contextos de reengajamento, e `categoria_da_novidade` escolhe entre elas a partir do par `(ficha, queda)` que um lembrete não tem. Dois templates, `lembrete_visita_24h` e `lembrete_visita_2h`, e a aprovação continua vindo de `Settings.templates_aprovados` — o mesmo fato externo (RT-03), lido do mesmo lugar.

**E a janela só vale no WhatsApp.** Quem o diz é `domain/outbound/web.py`: o canal web não tem janela, e nele não existe template a mandar. Aplicar a regra de um canal ao outro faria o lembrete de um lead do site virar um template que aquele adaptador não sabe renderizar. Decidido na implementação; o lembrete não filtra por canal como `sweep_followups` filtra, pela mesma razão que a TEC-170 não filtra — o agendamento é um compromisso que o lead marcou, não reengajamento de quem esfriou.

Os três desfechos, na ordem:

1. **Dentro da janela** (a última fala do lead tem menos de 24 horas) → texto livre, o da D5.
2. **Fora, com template aprovado** → o template, com os parâmetros posicionais montados dos dados da visita.
3. **Fora, sem template aprovado** → **nada sai**, `lembrete.sem_template` em `warning`, e a coluna é gravada como resolvida.

**O terceiro desfecho é a realidade de hoje, e é a lacuna maior desta card.** `WHATSAPP_TEMPLATES_APROVADOS` é vazio por padrão, e o RT-03 avisa que a aprovação pode não chegar; com ela vazia, `escolher_template` devolve `None` para tudo. E o lembrete cai fora da janela quase sempre por construção: um lead que marcou visita ontem provavelmente não escreveu desde então, e 24 horas é exatamente a antecedência do primeiro lembrete. **Sem template aprovado, o lembrete de 24 horas praticamente não existe.** Está declarado, não escondido — e é o mesmo preço que a TEC-186 já paga no follow-up.

**E não vira `TarefaDeCorretor`**, como o follow-up sem template vira. Lá a tarefa existe porque ninguém mais sabe daquele lead; aqui o corretor já recebeu o e-mail da TEC-170 com os dados da visita e já tem o evento na agenda. Uma tarefa seria a terceira cópia do mesmo fato.

## D5 — A guarda de horário, e a consequência que ela tem

`horario_permite_envio` (`outbound/horario.py`, TEC-185, RN-13.3) roda **no topo da varredura**, antes de tocar o banco, como em `sweep_followups` e pela mesma razão: sob fuso único (PR-04) a janela é propriedade de `agora` e não do agendamento. A docstring daquele módulo nomeia esta card como um dos sítios que deviam aplicá-la; é o que esta D5 faz.

**A consequência é declarada, não contornada:** com `followup_horario_inicio = 9`, uma visita às 9h ou às 10h tem a faixa inteira do lembrete de 2 horas (`[inicio - 2h, inicio)`) fora do horário de contato, e **esse lembrete não sai**. Não se inventa exceção aqui: a RN-13.3 fala de envio automático, e o lembrete é um; uma exceção para esta card seria uma segunda opinião sobre uma regra que já tem dono.

O registro do que não saiu é a **coluna nula com a faixa fechada**, que é consultável:

```sql
SELECT id, inicio FROM agendamentos
 WHERE status = 'CONFIRMADO' AND inicio < now() AND lembrete_2h_em IS NULL;
```

Não há detecção ativa disso nesta card (L2): um alerta precisaria de uma marca de "já avisei", que é uma terceira coluna para uma preocupação operacional. A consulta acima é o que existe.

## D6 — Os textos

Português **com acento** (TEC-267), constantes de módulo em `domain/agendamento/lembretes.py`, registradas em `tests/unit/literais_ao_lead.py` — é entrar nessa lista que põe um texto sob as guardas de acento (TEC-267) e de promessa (TEC-286).

Seis constantes: dois lembretes × três formas do compromisso, a mesma divisão que `texto_ao_lead` já faz, e reaproveitando `endereco_de` e `data_e_hora_absolutas`.

O de 24 horas oferece as três opções, como a RN-12.2 pede e como foi decidido em conversa em 25/09/2026 — e **não promete que alguém age sobre a resposta**, porque nada age. A diferença importa: "responda aqui se precisar remarcar ou cancelar" convida; "eu remarco para você" mentiria, que é a lição que a TEC-174 já pagou.

O de 2 horas não pergunta nada: faltando duas horas, o que serve é a hora e o endereço.

Nenhum dos seis diz que o corretor foi avisado ou está a caminho — a mesma regra que as três constantes da TEC-170 seguem.

## D7 — O que a varredura faz, por agendamento

O molde é `sweep_followups`, com as guardas na mesma ordem e pelo mesmo motivo (puro antes de I/O):

1. Guarda de horário — uma vez, no topo, antes da consulta (D5).
2. O pré-filtro da D2, em sessão própria e curta, que fecha antes de qualquer chamada de rede.
3. Por linha: `lembrete_devido` decide qual dos dois lembretes é devido (no máximo um — as duas faixas são disjuntas por construção), lê a âncora (última mensagem do lead), decide o canal pela janela de 24h (D4), monta o texto ou o template (D6), envia por `outbound.send` com o `kind` da D3, grava a coluna conforme a tabela da D3.

`GuardedOutbound` já carrega as guardas de opt-out (TEC-182) e de atendimento humano (TEC-179) — o lembrete passa por elas porque o `outbound` do `ctx` é o `RoteadorPorCanal`, o mesmo que `sweep_followups` usa. Não há checagem duplicada aqui.

**Sem mensagem do lead na conversa, o lembrete é pulado** com `lembrete.sem_ancora` em `info` e a coluna gravada: sem âncora não há `recipient_external_id`, que é o "de" do canal — o mesmo desfecho e o mesmo motivo que `_avisar_lead` da TEC-170 documenta. Gravar (e não deixar nulo) porque a ausência de mensagem do lead não se resolve sozinha nas próximas passagens.

**Nenhuma falha de um agendamento derruba o lote**, como em `sweep_followups`: cada linha em seu `try`, com `rollback` antes do `continue` para a sessão não envenenar a seguinte. `asyncio.CancelledError` continua propagando — não é `Exception`.

**Um teto por execução**, `MAXIMO_DE_LEMBRETES_POR_EXECUCAO = 50`: o custo por lembrete aqui é uma ida ao banco e um POST de até 10s (`outbound/whatsapp.py`), **sem chamada ao modelo** — o lembrete não passa por `redigir_abertura`, que é o que domina a conta de `sweep_followups`. Cinquenta × 10s são 500s contra um `job_timeout` de 240, então o teto de contagem sozinho não fecha a conta; o que fecha é o teto de tempo, `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS = 90`, o mesmo número e a mesma conta da varredura irmã, pela mesma razão (a checagem roda no topo do laço, então o pior caso é o teto mais um lembrete). Quem sobra continua devido e entra na passagem seguinte, cinco minutos depois — a faixa da D2 não se move.

## Testes

**Unitários** (sem banco):

- Os seis textos: visita com imóvel, visita sem imóvel e reunião remota, nos dois lembretes; data e hora absolutas no fuso local; o de 24h oferece as três opções e o de 2h não pergunta nada.
- O `kind`: 32 caracteres, um por agendamento e por lembrete, estável para o mesmo id.
- `escolher_template_de_lembrete`: devolve `None` com `aprovados` vazio, devolve o template certo por lembrete quando aprovado.
- A faixa da D2 como função pura: devido no piso, devido no meio, **não** devido no teto, **não** devido quando `confirmado_em` é posterior ao momento do lembrete.
- `dentro_da_janela` continua passando do novo lar, com os testes de `followup` importando de lá.

**Integração** (Postgres, portas falsas):

- Agendamento confirmado para daqui a 26 horas, relógio em `inicio - 24h` → um envio, coluna gravada (CA-12.1).
- Segunda passagem sobre o mesmo estado → nenhum envio novo.
- Relógio em `inicio - 2h` → o segundo lembrete sai, e o de 24h **não** sai de novo.
- Relógio em `inicio - 90min` com o de 24h ainda nulo → o de 24h **não** sai (o teto da faixa).
- Agendamento confirmado 3 horas antes do início → o de 24h nunca sai.
- Agendamento `EXPIRADO` e agendamento `RESERVADO` → nenhum lembrete. **É o quarto cenário do Gherkin no que ele tem de exercitável hoje**: o status `CANCELADO` não existe, e o filtro que o excluiria é o mesmo `status = 'CONFIRMADO'` que exclui estes dois.
- Fora do horário de contato → a varredura não toca o banco e nada sai.
- Fora da janela de 24h, sem template aprovado → nada sai, coluna gravada, `lembrete.sem_template`.
- Fora da janela de 24h, com template aprovado → sai o template.
- Lead em opt-out → nada sai e a coluna é gravada (não repete na passagem seguinte).
- Falha de canal → coluna nula, e a passagem seguinte tenta de novo.
- Sem mensagem do lead na conversa → nada sai, coluna gravada.

## Emendas ao SRS

- **RN-12.2** — os lembretes saem de uma varredura que lê o estado atual, numa faixa de tempo com teto, e não num instante; um lembrete cujo momento já passou quando o agendamento foi confirmado não existe. **Nada lê a resposta do lead**: o de 24 horas oferece confirmar, remarcar e cancelar, e as três caem na conversa normal, onde não há ferramenta de agendamento. Fora da janela de 24 horas da Meta o lembrete depende de template aprovado, e sem ele não sai.
- **RN-13.3** — a guarda de horário passa a valer também no lembrete de agendamento (`workers/jobs/sweep_lembretes.py::sweep_lembretes`), como a docstring de `domain/outbound/horario.py` previa. A consequência declarada: visita que começa antes de `followup_horario_inicio + 2h` não recebe o lembrete de 2 horas.
- **CA-12.1** — exercitado. O quinto cenário do Gherkin da card (resposta ao lembrete) **não**, e a razão está na D1 e no topo deste documento.

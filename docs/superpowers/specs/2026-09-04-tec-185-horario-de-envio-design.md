# TEC-185 — Respeitar a janela de 9h às 20h no fuso do lead

**Status:** desenhado em 2026-09-04 na branch `feat/tec-185-horario-de-envio`.

**Card:** [TEC-185](https://eduardodurieuxlopes.atlassian.net/browse/TEC-185) — Must (MoSCoW). Origem: RF-13, RN-13.3 (SRS v1.0, em `docs/srs/`). Épico de follow-up e opt-out.

**Branch:** `feat/tec-185-horario-de-envio`.

**Destravada por [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183)** (a cadência derivada), único bloqueio declarado, mergeada em `main` como `488f5ca`. A card está registrada como a **lacuna 3** do desenho da TEC-183.

## Objetivo

A história é da Marina, a lead: *"não quero receber mensagem da imobiliária às três da manhã, para não desinstalar o aplicativo por causa de um robô"*. A card se atribui Must porque mensagem automática de madrugada é o gatilho mais provável de denúncia e bloqueio do número na Meta (RN-B02), e declara que não há contorno: *"ou existe a janela, ou o disparo sai a qualquer hora"*.

**O que esta card entrega:** o predicado de horário — dado um momento, se um envio automático pode sair agora — e a sua aplicação no único sítio de automação que existe hoje, a varredura da cadência.

**O que ela não entrega:** nada é enviado ao lead, porque a TEC-184 ainda não existe. A TEC-183 decide *qual* tentativa está devida; esta decide *quando não* disparar. As duas juntas ainda só gravam trilha e emitem `followup.devido`.

## O que já existe, e que o desenho reusa

**A cadência derivada, e o que ela torna gratuito.** A TEC-183 não persiste agendamento: a varredura pergunta a cada passagem *"quem está devido agora?"*. As duas regras difíceis desta card caem dessa forma sem estado novo — ver a D1.

**O molde da função pura.** `cadencia.py`, `score.py`, `temperatura.py` e `gatilhos.py`: sem I/O, sem banco, sem chamada ao modelo, tudo keyword-only. O predicado de horário é o mesmo molde.

**O idioma de configuração do worker.** `sweep_stalled` lê `ctx.get("settings") or get_settings()`, e `Settings` já carrega knobs de varredura (`sweep_received_after_seconds`, `sweep_inflight_after_seconds`). A janela entra ali, e por isso as fixtures de teste existentes não precisam mudar.

**O `model_validator` que falha alto na construção.** `_recusar_chave_de_desenvolvimento_em_producao` existe em `Settings` precisamente para pegar configuração ruim em todo processo — API, worker, alembic e qualquer script. A validação da janela entra no mesmo lugar, pela mesma razão.

## Decisões

### D1 — O adiamento é aritmética, e não estado

A card pede duas coisas que, num modelo com agendamento persistido, seriam escrita no banco:

- *"Disparo agendado fora da janela é adiado para a próxima abertura, não descartado."*
- *"O adiamento não consome a tentativa da cadência."*

**No modelo derivado da TEC-183 as duas são consequência, não implementação.** Fora da janela a varredura não grava linha; como `ja_disparada` é o `MAX(tentativa_numero)` sob a âncora, ele continua no valor anterior, e a próxima varredura dentro da janela reencontra a mesma tentativa devida.

Verificado contra a régua atual, com o cenário exato do critério de aceite. Lead `QUENTE` que parou de falar às 19h30: a tentativa 1 vence às 21h30, fora da janela, e nada é gravado. Às 9h do dia seguinte, `tentativa_devida` recebe `ja_disparada=0` e `decorrido = 13h30`; a descida pela tupla `(2h, 24h, 3d, 7d)` rejeita 7d, 3d e 24h e devolve **1**. É o *"o follow-up é enviado às 9h do dia seguinte"* e o *"ele conta como a primeira tentativa"* da card, sem uma linha de código de adiamento.

**Isto é a Emenda E-01 à RN-13.4 outra vez, aplicada a outra regra.** Lá, a resposta do lead cancelava a cadência movendo a âncora em vez de escrever `CANCELADO`. Aqui, o adiamento preserva a tentativa não escrevendo nada. As duas dependem da mesma propriedade: o que não foi gravado não precisa ser desfeito.

**O que se perde:** não existe registro de que um disparo foi adiado. A distância entre `devido_em` e `created_at` na linha que acabar sendo gravada é a única evidência, e ela é indireta — mede o atraso total, sem dizer que a janela foi a causa. Nenhuma card pede o registro do adiamento hoje.

### D2 — `devido_em` continua sendo a hora da aritmética

`devido_em` permanece `ancora_em + CADENCIA[temperatura][n-1]`, e **pode cair de madrugada**. A janela decide se o disparo sai agora; ela não reescreve a coluna.

A alternativa era ajustar `devido_em` à janela (3h viraria 9h), que é o que o modelo de dados do SRS afirma sobre `agendado_para` (*"já ajustado à janela da RN-13.3"*). Rejeitada por duas razões:

- **`created_at` já é a hora do disparo real.** Ajustar `devido_em` gravaria a mesma informação em duas colunas e apagaria a única métrica interessante da linha: quanto tempo a janela empurrou o follow-up.
- **A coluna tem um significado só.** `devido_em` responde "quando a RN-13.1 disse que era hora". Misturar a RN-13.3 nela faria a coluna responder duas regras, e nenhuma revisão futura saberia qual delas está lendo.

Consequência: a **lacuna 3 da TEC-183** não desaparece com esta card. Ela muda de teor — de *"o horário calculado pode cair de madrugada"* para *"o horário calculado pode cair de madrugada, e nada é disparado ali"*. O texto tem de ser corrigido, não removido: comentário que descreve estado antigo é defeito neste repo.

### D3 — O nome é `horario`, e não `janela`

**"Janela" já significa três coisas neste repo**, e nenhuma é esta:

- `domain/context/janela.py` — a janela de contexto (quantas mensagens literais cabem antes de resumir).
- `EnvioForaDaJanela` (`outbound/port.py`) — a janela de 24 horas da Meta para mensagem livre.
- `job_completion_wait` (`workers/main.py`) — a janela de drenagem do worker no SIGTERM.

E `tests/unit/test_janela.py` já pertence à primeira. Nomear a quarta "janela" fabricaria ambiguidade num repo que trata comentário ambíguo como defeito — e a colisão de basename entre `unit` e `integration` já custou duas cards (`a3d1840`, `424ed72`).

Então: módulo `horario.py`, função `horario_permite_envio`, teste `tests/unit/test_horario_de_envio.py`. A prosa da card e do SRS continua dizendo "janela", que é o termo do negócio; o código diz "horário", que é o termo livre.

### D4 — O predicado mora em `outbound/`, e não em `followup/`

`src/mobia/domain/outbound/horario.py`:

```python
def horario_permite_envio(*, momento: datetime, inicio: int, fim: int, fuso: ZoneInfo) -> bool
```

A card diz que *"a regra vale para todo envio automático: follow-up, lembrete de agendamento e reengajamento"*. Sob `followup/`, a TEC-171 (lembretes de 24h e 2h) não acharia esta função e escreveria a segunda — o defeito de duas fontes que a TEC-146 gastou uma card inteira consertando.

**Tudo keyword-only**, e aqui o argumento é mais afiado que o de `tentativa_devida`: `inicio` e `fim` são dois `int` adjacentes, e trocá-los inverte a janela sem levantar, sem erro de tipo e sem o mypy ver. Mesma razão dos dois `datetime` de `tentativa_devida` e dos dois flags de `temperatura_de`.

#### E por que ele NÃO mora em `GuardedOutbound.send`

Seria a escolha tentadora: é lá que a guarda de opt-out mora, e o comentário dela diz explicitamente que *"quem HERDA desta classe ganha a guarda de graça, sem precisar lembrar dela"*.

**Mas `GuardedOutbound.send` é o mesmo caminho da resposta ao lead.** `executar_turno` envia por ali. Um lead que escreve às 3h da manhã tem de ser respondido às 3h da manhã, e a card fala de *"envio automático"* — não de todo envio. A janela na porta compartilhada silenciaria o produto por 13 horas por dia.

A guarda pertence aos sítios que **originam** automação. Hoje há um; a TEC-171 e a TEC-172 trarão os outros.

### D5 — A borda das 20h só passa se os segundos morrerem

A janela é inclusiva nas duas pontas, **na granularidade do minuto**:

```python
local = momento.astimezone(fuso)
minuto_do_dia = local.hour * 60 + local.minute
return inicio * 60 <= minuto_do_dia <= fim * 60
```

**Os segundos são descartados de propósito, e isso é o oposto de desleixo.** O cron dispara em `minute={0, 5, 10, ...}`, mas `agora` é lido dentro do job — na prática `20:00:00,04`. Com uma comparação de `time` cheia (`<= time(20, 0)`), esse sweep fica **fora da janela**, e o teste unitário com um `datetime` exato passaria enquanto produção falharia. Truncando ao minuto, a varredura das 20:00 entra e a das 20:05 não.

**Os dois primeiros critérios de aceite da card são a mesma borda**, e uma comparação exclusiva (`<`) quebraria os dois:

- *"Dado um lead QUENTE que parou de responder às 18h ... Então o follow-up é enviado às 20h"* — 18h + 2h cai exatamente em 20:00.
- *"Dado um disparo agendado para exatamente 20h ... Então a mensagem é enviada"*.

**Consequência para a configuração:** `fim` nomeia o último minuto em que um envio pode começar. `fim=20` autoriza 20:00 e recusa 20:01. É um ímã de off-by-one, e fica escrito no docstring da função e no comentário do campo.

### D6 — `momento` ingênuo levanta, e a razão é o CI

`horario_permite_envio` recusa `datetime` sem `tzinfo`.

`astimezone()` num naive **não** erra: ele assume o fuso do *sistema*. A máquina de desenvolvimento deste projeto está em UTC−3 (medido: `datetime.now().astimezone()` devolve "Hora oficial do Brasil", offset `-3:00`) e o runner do GitHub Actions está em UTC. Um naive daria resultados divergentes nos dois, e — porque o fuso configurado por default coincide com o da máquina local — o bug seria **invisível aqui e só apareceria no CI**.

É a mesma classe de armadilha que o `pythonpath = ["."]` do `pyproject.toml` já documenta ("roda aqui e falha em CI"), com os papéis trocados. Levantar `ValueError` transforma a divergência silenciosa em falha na primeira chamada.

Toda origem de tempo do projeto já é aware: `datetime.now(UTC)` nos jobs, `timestamptz` em toda coluna. O predicado não afrouxa isso.

### D7 — `tzdata` entra em `dependencies`, e foi medido

**Medido nesta máquina, não suposto:**

```
ZoneInfo('America/Sao_Paulo') -> ZoneInfoNotFoundError
tzdata -> ModuleNotFoundError
```

`zoneinfo` usa a base de fusos do sistema operacional, e o Windows não tem uma. O Linux do CI tem — então, sem a dependência, **os testes passariam no CI e falhariam na máquina de quem desenvolve**.

`tzdata>=2026.1` entra em `[project] dependencies`, e **não** no extra `dev`: o worker importa o fuso em produção. O piso é o ano corrente e não a versão mais antiga que funciona, porque aqui a versão **é** o dado — um `tzdata` velho carrega regras de fuso velhas. Disponíveis hoje até 2026.3.

**A alternativa era `timezone(timedelta(hours=-3))`**, que dispensaria a dependência. Rejeitada: o Brasil aboliu o horário de verão em 2019, mas gravar o *offset* em vez do *nome* significa que a volta dele viraria um erro silencioso de uma hora em todo disparo — e a POC assume fuso único justamente para não decidir isso agora. `tzdata` é um wheel puro e pequeno; o nome preserva a correção se a regra mudar.

### D8 — A janela é `Settings`, e a configuração ruim falha alto

```python
followup_horario_inicio: int = 9
followup_horario_fim: int = 20
followup_fuso: str = "America/Sao_Paulo"
```

mais uma property `fuso_de_envio -> ZoneInfo`.

**A card pede janela "configurável sem deploy", e a TEC-183 tratou o pedido gêmeo como lacuna RF-19** — os intervalos ficaram constantes de módulo. **O precedente não transfere**, e a diferença é de forma: `CADENCIA` é uma tabela indexada por temperatura, com tuplas de `timedelta`, que vazaria mal para variável de ambiente. A janela são dois inteiros e um nome de fuso, que é exatamente o que `Settings` já faz para `contexto_teto_de_tokens` e para os três knobs de `sweep_`.

**O `model_validator` recusa na construção:**

- `0 <= inicio < fim <= 23`. Uma janela invertida ou vazia (`9–9`) desligaria a cadência inteira **em silêncio** — a varredura simplesmente devolveria 0 para sempre, e o único sintoma seria a ausência de `followup.devido`, que é indistinguível de "nenhum lead devido".
- `followup_fuso` construível como `ZoneInfo`. Sem isso, um typo explodiria dentro da varredura a cada 5 minutos em vez de na subida do worker.

**`ValueError` e não `ConfiguracaoInsegura`.** O docstring daquela exceção diz *"configuração que rodaria, mas sem a proteção que devia ter"*, e o caso dela é a chave de cifra de desenvolvimento em produção. Uma janela invertida não perde proteção: ela deixa de operar. O pydantic embrulha o `ValueError` em `ValidationError`, que falha igualmente alto e em todo processo.

**Lacuna que fica:** "sem deploy" no sentido pleno — recarga viva, ajuste pelo dashboard — segue sendo RF-19. Variável de ambiente exige reiniciar o worker.

### D9 — O sítio é o topo da varredura

```python
if not horario_permite_envio(
    momento=agora,
    inicio=settings.followup_horario_inicio,
    fim=settings.followup_horario_fim,
    fuso=settings.fuso_de_envio,
):
    return 0
```

antes de `candidatos_a_followup`.

**Sob fuso único a janela é propriedade de `agora`, e não do candidato** — a card põe a detecção de fuso pelo número fora de escopo (PR-04). Então o porteiro no topo é exatamente correto, e por 13 das 24 horas o job não toca o banco.

**As duas alternativas, e por que não:**

- **Terceira guarda por candidato**, ao lado de `tentativa_devida` e `esta_em_optout`. Ficaria pronta para fuso por lead, mas pagaria o `GROUP BY` sobre `messages` a cada 5 minutos por 13 horas para descobrir que não pode mandar nada — justamente a consulta que a **lacuna 6 da TEC-183** registra como a cara da varredura.
- **A janela na SQL da consulta de candidatos.** Escreveria o predicado uma segunda vez, em outra linguagem, sem poder reusar a função pura.

**O que muda quando o fuso virar por lead:** o sítio da chamada desce para dentro do laço, e a função pura não muda — ela já recebe o fuso por parâmetro. Fica escrito no comentário do porteiro, para que a próxima card não reescreva o predicado achando que ele é global por natureza.

### D10 — `sweep_followups` passa a receber `agora`

`async def sweep_followups(ctx, limite=500, *, agora: datetime | None = None) -> int`, com `None` significando `datetime.now(UTC)`.

**Sem isto, a suíte da TEC-183 passaria a depender da hora do dia em que o CI roda.** Os sete testes de `tests/integration/test_sweep_followups.py` chamam `sweep_followups(_ctx())` e assumem que a varredura roda; com o porteiro da D9, um CI que rodasse às 23h de São Paulo reprovaria os sete. Isso não é um teste frágil que dá para tolerar — é a suíte inteira de uma card mergeada virando função do relógio de parede.

**Configurar a janela nos testes não resolve, e a aritmética diz por que.** A tentação é o `_ctx()` injetar uma janela "sempre aberta", mas ela não existe: com a borda da D5, `inicio=0, fim=23` autoriza 00:00 até 23:00 e **recusa 23:01–23:59**. Uma suíte que reprova cinquenta e nove minutos por dia é pior que uma que reprova sempre, porque parece flake.

**O precedente está escrito no repo.** A docstring de `candidatos_a_followup` já argumenta exatamente isto para a consulta: *"`agora` entra por parâmetro e não sai de `datetime.now()` aqui dentro: sem isso nenhum teste consegue posicionar o relógio, e a cadência inteira é sobre tempo."* A D10 estende o mesmo argumento uma camada acima — o job também é sobre tempo, e agora tem duas perguntas de tempo em vez de uma.

**O que isso permite, além de não quebrar nada:** o cenário-título da card fica testável ponta a ponta. "Parou às 19h30, nada às 21h30, follow-up às 9h do dia seguinte, contando como a primeira tentativa" vira três chamadas com três momentos, contra o mesmo banco.

Produção não passa o parâmetro — o cron chama `sweep_followups(ctx)`, e `limite` já é um parâmetro que só os testes variam.

## Fluxo

1. O cron dispara `sweep_followups` a cada 5 minutos.
2. `horario_permite_envio` decide, sobre `agora` convertido ao fuso configurado. Fora da janela, a varredura devolve 0 sem consultar o banco.
3. Dentro da janela, o resto é a TEC-183 intacta: candidatos, `tentativa_devida`, opt-out, `INSERT`, e os eventos depois do `commit`.
4. Um disparo que a janela recusou não deixa rastro, e a próxima varredura dentro da janela reencontra a mesma tentativa devida — o adiamento da D1.

## Testes

**Basenames distintos entre `unit` e `integration`:** `tests/unit/test_horario_de_envio.py` (novo) e extensão de `tests/integration/test_sweep_followups.py`. `test_janela.py` já existe em `unit` e pertence à janela de contexto — o nome novo não colide com nada.

**Unitários, com momento explícito:**

- Dentro da janela; antes das 9h; depois das 20h.
- Exatamente 09:00 e exatamente 20:00 — as duas bordas inclusivas.
- **20:00:03** — a regressão da D5. É o teste que morre se alguém trocar a truncagem ao minuto por uma comparação de `time` cheia, e o único que distingue "passa no teste" de "funciona no cron".
- 20:05 fora, que é o outro lado da mesma truncagem.
- `momento` naive levanta `ValueError` (D6).
- Janela configurada diferente do default, provando que os parâmetros são lidos e não ignorados.

**Integração**, com o momento fixado pelo parâmetro da D10 e a janela default (9h–20h) injetada em `ctx`:

- Fora da janela, `sweep_followups` devolve 0 **e não grava linha** — as duas assertivas, porque devolver 0 sem gravar e gravar sem contar são falhas diferentes.
- **O adiamento ponta a ponta:** parou às 19h30, a varredura das 21h30 devolve 0 e não grava, e a das 9h do dia seguinte grava a tentativa **1**. É o teste que morre se alguém tentar implementar o adiamento com estado.
- **As 20h em ponto ainda disparam:** um lead `QUENTE` que parou às 18h vence a primeira tentativa exatamente às 20h. A borda sobrevive nas duas pontas do caminho, e isso foi verificado no código da TEC-183: o corte da consulta é `HAVING MAX(created_at) <= :corte` (inclusivo) e a régua compara com `>=`.
- Os sete testes existentes daquela card ganham `agora` explícito e passam a ser determinísticos (D10). O comportamento verificado por eles não muda.

**Configuração:** o `model_validator` recusa janela invertida, janela vazia e fuso inválido. Três testes em `tests/unit/test_config.py`, que já é o lugar das guardas de `Settings`.

**O cenário do lembrete de visita não dá para escrever.** A card pede: *"Dado um lembrete de visita agendado para 6h da manhã ... Então o envio é adiado para as 9h"*. Não existe lembrete — é a TEC-171. Fica registrado como teste ausente e nomeado, no mesmo tratamento que a TEC-183 deu à conversa silenciada, em vez de virar um teste que finge cobrir.

## Emendas ao SRS

**RN-13.3** ganha `Emenda E-01` como item aninhado, sem tocar no texto de 22/08, mais uma linha na tabela do topo. A numeração é **por regra** — há várias `E-01` no documento, cada uma de uma regra diferente.

O teor: a janela é guarda de disparo, e não ajuste de agendamento. `devido_em` continua sendo a hora da aritmética da RN-13.1 e pode cair fora da janela; o que a janela impede é o disparo. O efeito observável da regra é o descrito — nenhum envio automático fora de 9h–20h, e o disparo recusado é adiado para a próxima abertura sem consumir a tentativa. A consequência declarada é que a afirmação do modelo de dados da seção 5 sobre `agendado_para` estar *"já ajustado à janela da RN-13.3"* não vale para `devido_em`: a Emenda E-01 da RN-13.4 já havia renomeado a coluna e apontado para esta card, e esta fecha o ponto escolhendo não ajustar.

## O que muda no que já está escrito

A regra "comentário não mente" cobra três correções, e elas fazem parte da entrega:

1. **A lacuna 3 do desenho da TEC-183** passa a dizer que `devido_em` pode cair de madrugada **e que nada é disparado ali** (D2). Corrigida, não removida.
2. **O docstring de `sweep_followups`** ganha a guarda de horário na lista das guardas, com a nota de que ela é a única que roda antes da consulta, e por quê.
3. **O docstring de `cadencia.py` não muda.** A régua continua respondendo "quem está devido", e não "quem pode receber agora" — a separação é a razão de o predicado morar em outro pacote.

## Lacunas declaradas

1. **Fuso único, não por lead.** Está na própria card (PR-04). O `astimezone` já converte corretamente; o que falta é a origem do fuso, e o comentário do porteiro nomeia o que muda quando ela existir.
2. **A janela não cobre lembrete nem reengajamento**, porque nenhum dos dois existe (TEC-171, TEC-172). A regra da card os inclui; a função está pronta para os dois sítios, e o cenário de aceite do lembrete fica como teste ausente.
3. **"Sem deploy" é por variável de ambiente**, o que exige reiniciar o worker. Recarga viva e ajuste pelo dashboard seguem RF-19.
4. **O adiamento não deixa registro** (D1). A distância entre `devido_em` e `created_at` é evidência indireta do atraso, e não diz que a janela foi a causa.
5. **Nada é enviado ao lead.** A TEC-184 é quem fala. Esta card decide quando não disparar, e a anterior decidiu o quê.

## Fora de escopo

- Detecção do fuso do lead a partir do número — PR-04, escrito na própria card.
- O conteúdo da mensagem de follow-up — RN-13.2, [TEC-184](https://eduardodurieuxlopes.atlassian.net/browse/TEC-184).
- Os lembretes de 24h e 2h, que a regra desta card cobrirá quando existirem — [TEC-171](https://eduardodurieuxlopes.atlassian.net/browse/TEC-171).
- O teto de 4 mensagens não respondidas — RN-13.7, [TEC-188](https://eduardodurieuxlopes.atlassian.net/browse/TEC-188).
- Configuração alterável sem reiniciar o worker — RF-19.

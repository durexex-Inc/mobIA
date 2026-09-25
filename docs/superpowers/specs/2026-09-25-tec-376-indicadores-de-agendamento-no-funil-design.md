# TEC-376 — Os quatro indicadores de agendamento, e a etapa que vem junto

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-376](https://eduardodurieuxlopes.atlassian.net/browse/TEC-376) — épico TEC-303
**Branch:** `feat/tec-376-indicadores-de-agendamento-no-funil`
**Origem:** SRS v1.0 — RF-17, RN-17.1, RN-17.2, CA-17.1 · TEC-190, TEC-367, TEC-371

## Objetivo

Quatro indicadores do painel saem `null` desde a TEC-190, e a etapa `Agendado` sai `null`/`disponivel: false` junto com eles. Quatro emendas do SRS já falaram do assunto, e a última — a E-04 da RN-17.1, escrita **hoje** pela TEC-371 — diz o que esta card existe para desfazer:

> **o motivo declarado pela Emenda E-01 deixou de valer.** Existe tabela de agendamento desde a TEC-168 e, desde esta card, existem linhas criadas por lead de verdade (…) Dito sem rodeio: até lá eles mentem por omissão em vez de por ausência, que é pior do que era.

A card pergunta se deve esperar pela TEC-371. **A pergunta já está respondida pelos fatos:** a TEC-371 fechou hoje às 11:29 e a TEC-372 às 12:24. `agendamento/conversa.py` cria agendamento a partir da fala do lead, e a resposta ao lembrete de 24 horas cancela e remarca. Contar já não é contar conjunto vazio.

## D1 — A etapa `Agendado` entra junto, e isto é uma divergência do texto da card

**A card fala em quatro indicadores e põe "os demais indicadores do funil" fora do escopo. A etapa `Agendado` não é um dos "demais que já funcionam" — ela é nula pela mesma ausência, e sai pela mesma consulta.**

Três coisas sustentam trazê-la junto:

1. **O código já nomeia esta card como a que a liga.** `metricas/repositorio.py::contar_etapas` diz, sobre deixar `AGENDADO` fora da acumulação: *"escreveria aqui uma dependencia que some no dia em que a TEC-376 der numero aquela etapa"*. E `metricas/vocabulario.py` diz *"Quando a RF-12 existir, tire `AGENDADO` daqui e escreva a consulta"*.
2. **O SRS amarra as duas.** A Emenda E-02 da RN-17.2 diz que a etapa é nula *"pela Emenda E-01 da RN-17.1"* — a mesma emenda dos quatro indicadores. Ligar os indicadores e deixar a etapa apagada tornaria a E-02 falsa sem que nada a emendasse.
3. **O painel ficaria incoerente.** `agendamentosCriados: 12` ao lado de `Agendado: —`, lidos na mesma tela, afirmam ao mesmo tempo que há e que não há fonte.

A própria card mistura os dois vocabulários sem perceber: ela diz que *"os quatro indicadores saem `null`, com `disponivel: false`"*, e `disponivel` é campo de **etapa**, não de indicador — os indicadores saem como chave nula mais o nome na lista `indisponiveis`. Isso é indício de que o texto pretendia o conjunto todo.

**Registrado como divergência no comentário da card.**

## D2 — Coorte, e não atividade

Todo número de `metricas/repositorio.py` é sobre a **coorte** — os leads cujo primeiro contato caiu no período —, e não sobre eventos ocorridos nele. É a Emenda E-02 da RN-17.1, e a docstring do módulo a repete em maiúsculas.

Os quatro indicadores herdam o recorte: são os agendamentos **dos leads da coorte**, onde quer que tenham sido marcados depois. Um painel em que `leadsNovos` é coorte e `agendamentosCriados` é atividade poria lado a lado dois denominadores diferentes com a mesma aparência.

O Gherkin da card diz *"três agendamentos criados no período"*. Lido ao pé da letra, isso é atividade. Lido como o resto do módulo, é "três agendamentos de leads da coorte". **Adoto o segundo**, e os testes usam leads nascidos no período para que as duas leituras coincidam no cenário.

## D3 — A etapa conta LEADS; os indicadores contam COMPROMISSOS

São unidades diferentes na mesma resposta, e isso é deliberado:

- **`Agendado`** é uma etapa de funil. Conta pares `(channel, conversation_key)` distintos, como as outras cinco. Um lead com três visitas conta 1 — senão a "conversão" `Agendado / Recomendado` passaria de 100% pelo caminho que a TEC-367 acabou de fechar.
- **`agendamentosCriados`** e os outros três contam **compromissos**. O Gherkin é explícito: *"três agendamentos criados no período, dois deles confirmados → criados é 3"*. A gerente pergunta quantas visitas foram marcadas, não quantas pessoas marcaram alguma.

Um lead com duas visitas soma 2 em `agendamentosCriados` e 1 na etapa `Agendado`. Escrito na docstring do módulo, porque um leitor que presuma a mesma unidade vai achar que uma das duas consultas está errada.

## D4 — A cadeia de remarcação colapsa na raiz, e isso não precisa de CTE recursivo

O critério de aceite: *"um agendamento REAGENDADO e o sucessor dele REALIZADO → criados conta 1, e não 2"*. `origem_id` liga sucessor a original, sem teto de cadeia (`ciclo.py::remarcar`: "A -> B -> C encadeia por aqui").

A tentação é uma `WITH RECURSIVE` para subir cada cadeia até a raiz. **Não é preciso, e a razão está na máquina de estados de `ciclo.py::_ORIGENS_DE`:**

```
_ORIGENS_DE[REAGENDADO] = {CONFIRMADO}
_ORIGENS_DE[REALIZADO]  = {CONFIRMADO}
_ORIGENS_DE[NO_SHOW]    = {CONFIRMADO}
```

Disso saem três propriedades, e cada uma dispensa a recursão de um dos números:

1. **`criados` = linhas com `origem_id IS NULL`.** Toda cadeia tem exatamente uma raiz, e contar raízes é contar compromissos. Vale para A→B→C sem tratamento especial.

2. **`confirmados` = raízes com `confirmado_em IS NOT NULL`.** Para ter sucessor, o original precisou passar por `CONFIRMADO` — é a única origem legal de `REAGENDADO` —, e `repositorio.py::confirmar` carimba `confirmado_em` no mesmo UPDATE. Logo **"a cadeia foi confirmada alguma vez" ⟺ "a raiz tem `confirmado_em`"**, e basta olhar a raiz. (O sucessor de `remarcar` nasce `CONFIRMADO` com `confirmado_em=agora`, mas nunca é raiz.)

3. **`realizados` e `no-show` = linhas, sem filtrar raiz.** Uma cadeia tem **no máximo um** desfecho: quem virou `REAGENDADO` não pode virar `REALIZADO` nem `NO_SHOW` depois, porque a origem legal dos dois é só `CONFIRMADO`. Então contar linhas com `realizado_em IS NOT NULL` já conta cada cadeia uma vez — a dedução da remarcação é automática, e não uma correção aplicada em cima.

**Se algum dia `_ORIGENS_DE` admitir `REAGENDADO` como origem, as três propriedades caem juntas.** Por isso a consulta cita a tabela pelo nome no comentário, em vez de só afirmar o resultado.

## D5 — `EXPIRADO` fica fora de tudo, e a card não fala dele

A card lista o vocabulário a contar — `RESERVADO`, `CONFIRMADO`, `REALIZADO`, `NO_SHOW`, `CANCELADO`, `REAGENDADO` — e **omite `EXPIRADO`**, que existe em `StatusDoAgendamento` e não está na RN-12.5. O próprio enum declara o desvio: *"`EXPIRADO` existe e nao esta na RN-12.5. E a reserva atropelada por outra, um fato que aquela lista nao modela."*

**Decido deixá-lo fora de `criados` e da etapa `Agendado`.** `ciclo.py` diz o porquê melhor do que eu conseguiria: *"EXPIRADO nao e origem de nada: ele ja e terminal, e a reserva que ele descreve nunca virou compromisso."* E `agendamento/conversa.py` põe em `EXPIRADO` também a reserva que **o lead recusou** — contá-la como visita marcada diria que o agente agendou quando o lead disse não.

`RESERVADO` vivo **conta**: é a reserva de 5 minutos da RN-11.4, o `PROPOSTO` da RN-12.5 sob outro nome, e enquanto o relógio corre ela é um compromisso pendente. `CANCELADO` e `REAGENDADO` contam em `criados` — foram marcados, e depois desfeitos; `criados` é sobre ter sido criado.

Vira emenda ao SRS, porque é regra que a RN-17.1 não decidia.

## D6 — O denominador da taxa de no-show é o desfecho DECIDIDO

`taxaNoShow = no_show / (realizados + no_show)`, e `null` quando o denominador é zero.

O molde não é novo: é o mesmo de `sla_handoff_cumprido_pct`, que já escolheu contar *"o handoff cujo desfecho ja esta DECIDIDO"*. Um agendamento `CONFIRMADO` cujo horário passou e que ninguém marcou não decidiu nada — pô-lo no denominador como "não foi no-show" diluiria a taxa com compromissos sobre os quais não se sabe nada.

O Gherkin — *"quatro agendamentos com horário passado, um deles NO_SHOW → 25%"* — fecha com isto quando os outros três são `REALIZADO`, e é assim que o teste o monta. Fosse o denominador "horário passado", os mesmos quatro com três sem marcação dariam 25% afirmando que três visitas aconteceram, o que ninguém registrou.

`null` e não `0.0` no denominador zero, pela regra do módulo: *"Nulo e 'nao ha o que medir', e nunca zero."*

## D7 — `agendamentosRealizados` vai sair zero em produção, e entra assim mesmo

**Nenhum caminho de produção marca `REALIZADO` ou `NO_SHOW` hoje.** `ciclo.py` declara: *"`marcar_realizado` e `marcar_nao_comparecimento` continuam sem chamador: sao acao do corretor, e a interface dele e a E8, que nao existe."* Ligar a rota é a [TEC-374](https://eduardodurieuxlopes.atlassian.net/browse/TEC-374), criada um minuto antes desta.

Então, em produção: `criados` e `confirmados` trazem número de verdade; `realizados` sai **0** e `taxaNoShow` sai **`null`** (0/0), até a TEC-374 entrar.

**A tensão é real e vale dizer qual lado escolhi.** O princípio da card é que zero só pode ser dito quando um caminho de produção pode escrever o fato — e para o desfecho não pode. O argumento oposto, que adoto:

- O critério da própria card é sobre **criar**: *"a partir do momento em que um caminho de produção pode criar agendamento, zero passa a ser um fato sobre o negócio"*. Esse momento chegou.
- Os quatro são critério de aceite escrito em Gherkin. Entregar três e inventar um quinto estado para o quarto é reescrever a card.
- `taxaNoShow` já degrada para `null` sozinha, pela D6 — três dos quatro são honestos sem esforço.
- `agendamentosRealizados: 0` é literalmente verdadeiro sobre o registro: nenhuma visita foi marcada como realizada.

**O risco que fica**: a gerente lê `Criados: 12, Confirmados: 9, Realizados: 0` e conclui que o agente marca visita e ninguém aparece. É conclusão errada, e a causa é a TEC-374 faltando, não o número. **Vai no comentário da card como lacuna de produto**, e é o tipo de coisa que a tela resolve melhor que a consulta — um rótulo dizendo de onde vem o dado.

## D8 — `SEM_FONTE` e `INDICADORES_SEM_FONTE` somem, e `indisponiveis` fica vazio

Não viram conjuntos vazios. Uma `frozenset()` vazia com a docstring de ausência é um mecanismo sem caso de uso esperando envelhecer; `montar_funil` passa a marcar toda etapa como disponível e a rota deixa de ter lista de exceção.

**O contrato não muda de forma:** `etapas[].disponivel` continua existindo e passa a ser sempre `true`; `indisponiveis` continua existindo e passa a ser `[]`. Quem consome não precisa de mudança — que é o que a Emenda E-01 prometeu com *"só a consulta muda"*.

**O campo `disponivel` continua na resposta**, mesmo constante: tirá-lo é mudança de contrato de verdade, e ele volta a valer no dia em que uma etapa nova nascer sem fonte. A alternativa — remover agora e recriar depois — troca uma constante por duas migrações de contrato.

## D9 — `Recomendado` muda de valor, e isso é consequência da acumulação

Com `AGENDADO` entrando na acumulação da TEC-367 entre `RECOMENDADO` e `HANDOFF_ACEITO`:

```
Recomendado    = união(recomendados, agendados, aceitos)   ← cresce
Agendado       = união(agendados, aceitos)                 ← novo
Handoff aceito = aceitos                                   ← igual
```

O lead que marcou visita sem ter recomendação registrada passa a contar em `Recomendado`. É exatamente o que a D4 da TEC-367 determinou — cada etapa conta quem a alcançou **ou alcançou uma posterior** —, e é o que mantém `Agendado ⊆ Recomendado` por construção, sem depender de os dados colaborarem.

**E a conversão de `Handoff aceito` deixa de ser nula.** A Emenda E-02 da RN-17.2 registrou que ela era nula *"por consequência"* de a etapa anterior não ter fonte. A consequência acaba junto com a causa.

## Emendas ao SRS

Três, todas aninhadas sob a regra que alteram:

- **RN-17.1, Emenda E-05** — os quatro passam a contar; o que cada um conta; coorte; a raiz da cadeia; `EXPIRADO` fora; o denominador do no-show; e a lacuna da TEC-374 dita com todas as letras.
- **RN-17.2, Emenda E-04** — `Agendado` ganha fonte e entra na acumulação; `Recomendado` muda de valor; a conversão de `Handoff aceito` deixa de ser nula.
- **CA-17.1, Emenda E-03** — o critério volta a ser exercitável e **ganha teste**, depois de duas emendas registrando que não tinha.

## Fora do escopo

- **Marcar realizado/no-show pelo painel** — é a TEC-374. Esta card só conta o que aquela escreve.
- **O filtro por corretor** — continua recusado com 422 (`montar_recorte`), e a decisão é da TEC-316.
- **Os demais indicadores do funil**, que já funcionam.

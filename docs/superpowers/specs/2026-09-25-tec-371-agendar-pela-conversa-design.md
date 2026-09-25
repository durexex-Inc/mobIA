# TEC-371 — Agendar a visita pela conversa, do pedido de horário à confirmação

**Status:** implementado
**Card:** [TEC-371](https://eduardodurieuxlopes.atlassian.net/browse/TEC-371) — épico TEC-164
**Branch:** `feat/tec-371-agendar-pela-conversa`
**Origem:** RF-11, RF-12, RN-11.1 a RN-11.4, RN-12.1, CA-11.1, CA-11.2, RT-07, RT-10 (SRS v1.0). Depende de TEC-165, TEC-166, TEC-167, TEC-168 e TEC-170 — todas mergeadas.

## Objetivo

O lead marca a visita conversando. Esta é a card que liga sete cards de agendamento à conversa: até ela, `domain/agente/turno.py` não importava uma linha de `domain/agendamento/`, e o épico inteiro era motor sem ignição.

## O que esta card não entrega, dito antes

- **Lista de espera sem disponibilidade em 72 horas (RN-11.5).** É a TEC-169, e o que esta card faz quando não há janela está na D8 — não é a lista de espera, e não finge ser.
- **Ler a resposta do lead ao lembrete de 24 horas.** É a TEC-372. A Emenda E-01 da RN-12.2 continua verdadeira depois desta card: o lembrete oferece "sim/remarcar/cancelar" e nada lê a resposta. O que muda é que a conversa passa a ter **um** caminho de agendamento; o do lembrete continua sem leitor.
- **Cancelar e remarcar pela conversa.** A TEC-172 construiu as transições (`ciclo.py::cancelar`, `::remarcar`); esta card não as chama. Um lead que escreve "quero desmarcar" continua caindo no turno normal.
- **Reunião remota.** `TipoDeCompromisso.REUNIAO_REMOTA` existe e continua sem caminho de conversa: o pedido que esta card reconhece é de **visita**, e o tipo gravado é sempre `VISITA_PRESENCIAL`. Ver a D2.
- **Os indicadores de agendamento do painel de funil**, `null` desde a Emenda E-01 da RN-17.1 e reafirmados pela Emenda E-03. Esta card é a primeira a criar agendamento por caminho de lead, então ela **remove o motivo** daquelas emendas — mas trocar `null` por contagem é mudança de contrato do painel, e é da E8. A Emenda E-04 registra isso.

## D1 — A detecção é determinística, e o orçamento do prompt é a razão de sempre

O pedido de visita é reconhecido por **código, não pelo modelo**. Molde de `domain/optout/deteccao.py::pediu_optout` e `domain/humano/deteccao.py::pediu_humano`.

Medido hoje, 25/09/2026, com `pytest -k margem_do_orcamento -s`: líquido 786,8, teto 793, **margem 6,2**. Uma ferramenta nova em `tools=` custa a ordem de grandeza da ferramenta de busca — **131,2 tokens**, vinte vezes a margem inteira. O ritual manda perguntar "o que sai do prompt para o novo texto entrar?", e esta card não tem resposta: nada no prompt de hoje é dispensável para caber um esquema de agendamento.

E há o argumento que a TEC-143 diz ser o que de fato decidiu, não o custo: **a decisão não pode depender de o provedor estar de pé.** Um lead que pergunta "pode ser quinta de manhã?" durante uma indisponibilidade do modelo continua tendo horário para escolher, porque nada neste caminho chama o classificador.

## D2 — O detector é NOVO, e não é `gatilhos_de`: a assimetria de erro é a inversa

`domain/context/gatilhos.py` já tem `MOTIVO_VISITA`, e reusá-lo seria o erro barato de cometer. A docstring daquele módulo declara o critério dele: a faixa é **estrita** porque um falso positivo força QUENTE **permanentemente** e toca o telefone do corretor, sem tela para desfazer. Ela paga isso em recall, e nomeia o caso: **"posso ver o apartamento amanhã?" não dispara.**

Aqui a conta é a inversa:

- **Falso positivo:** o agente oferece três horários a quem não pediu. O lead ignora, ou diz que não quer, e o turno seguinte segue normal. Visível, barato, reversível pela própria conversa.
- **Falso negativo:** o lead pediu para marcar visita e o agente responde como se não tivesse pedido. É o produto inteiro do épico não acontecendo, e o lead não tem como insistir de outro jeito — ele já disse a frase certa.

Reversível e visível perde para invisível e irreversível na `gatilhos.py`; aqui os papéis se trocam. Então: **dois detectores, com vocabulários diferentes, e nenhum importa o outro.** Quem quiser deduplicá-los depois tem de reabrir as duas assimetrias, não só as duas listas.

`domain/agendamento/deteccao.py::quer_agendar` normaliza como os irmãos (minúsculas, sem acento, sem pontuação) e tem **duas vias**.

A primeira é a lista de termos: verbo de ação junto do objeto, com limite de palavra nos **dois** lados de cada alternativa. Os dois lados, e não só o início como na `gatilhos.py`, porque aqui há termos curtos (`sim`, `ok`, `nao`) que são substring de palavra comum — sem o limite no fim, `sim` casaria dentro de `simples`. **O substantivo sozinho não entra**: com `visita` na lista, "quero desmarcar a visita" disparava, que é o erro exato contra o qual a `gatilhos.py` avisa quando diz que o critério é o verbo de ação junto do objeto.

A segunda via existe porque **o primeiro cenário do Gherkin não tem termo nenhum**: "pode ser quinta de manhã?" não traz verbo de agendamento nem a palavra visita. O que ela traz é um **enquadramento de proposta** (`pode ser`, `que tal`, `posso ir`, …) mais uma data que `data_falada::resolver` reconhece, e são as duas juntas que fazem um pedido de horário. Exigir as duas é o que separa essa fala de "meu contrato vence dia 15" (data sem enquadramento) e de "pode ser mais barato?" (enquadramento sem data).

**`desmarcar`, `remarcar`, `reagendar` e `cancelar` têm VETO, e não só ausência.** São a TEC-372 e a TEC-172. Deixá-los fora das listas não bastava: a segunda via dispara em "quero remarcar, pode ser quinta de manhã?" sem precisar de termo nenhum, e o agente ofereceria horário novo a quem quer mexer no que já existe, sem nunca cancelar o antigo.

O tipo é sempre `VISITA_PRESENCIAL`: todo termo da lista fala de ver imóvel. Reunião remota não tem vocabulário próprio nesta card e por isso não tem caminho.

## D3 — São três turnos, e é o que a RN-11.4 já descrevia

| turno | o lead diz | o sistema faz | o lead lê |
| --- | --- | --- | --- |
| A | "pode ser quinta de manhã?" | recorta pela data falada, ou `janelas_alocadas` → grava as propostas | até 3 janelas, cada uma com data e hora absolutas |
| B | "a segunda" / "às 11h" | casa a escolha → `reservar_ou_alternativas` | a janela escolhida, absoluta, e o pedido de confirmação |
| C | "isso, pode marcar" | `confirmar` → commit → enfileira | a confirmação da RN-12.1, enviada pelo job |

**A reserva de 5 minutos existe entre B e C, e é exatamente o que a RN-11.4 diz:** "slot é reservado com lock otimista por 5 minutos *durante a confirmação*". Não é um detalhe de implementação que poderia ser colapsado — colapsar B e C em um turno faria a RN-11.3 ser violada (gravar sem confirmação explícita de data e hora absolutas) **e** deixaria o terceiro cenário do Gherkin da card inalcançável: uma reserva que nunca vive não vence.

O que torna os três turnos possíveis sem estado em memória é que **cada estado é uma pergunta ao banco**:

- sem proposta e sem reserva viva → turno A, se `quer_agendar`
- propostas gravadas para esta conversa → turno B, para qualquer texto
- linha `RESERVADO` desta conversa → turno C, para qualquer texto

Nos dois últimos, texto que não case nada **cai fora** e o turno segue normal. É isso que limita o custo do falso positivo da D2: o sequestro da conversa dura um turno, não uma sessão.

## D4 — As propostas são gravadas, e não recalculadas (migration 0051)

Tabela nova, `janelas_propostas`: `id`, `channel`, `conversation_key`, `ordinal` (1..3), `corretor_id` (FK), `imovel_id` (FK nula), `tipo`, `inicio`, `fim`, `motivo_da_alocacao`, `proposto_em`. `UNIQUE (channel, conversation_key, ordinal)`.

**A alternativa era recalcular no turno B, e ela tem um defeito que o lead vê.** As janelas são função de `agora`, e `agora` anda: a grade é de 30 minutos e a antecedência mínima é de 3 horas, então a rodada das 10h00 propõe 13h00 e a das 10h03 propõe 13h30. Três minutos de digitação depois, o lead que responde "13h" recebe "não encontrei esse horário" — sobre um horário que **nós** acabamos de oferecer. Gravar é o que faz o ordinal e a hora se referirem ao que foi dito, e não ao que o relógio produziria agora.

Precedente direto: `recomendacoes` grava cada imóvel apresentado justamente para que "gostei do segundo" (CA-10.1) tenha a que se referir. É o mesmo problema.

**Uma rodada substitui a anterior**, por `DELETE` seguido de `INSERT` na mesma transação: os ordinais são sempre os da última oferta, e não há acumulação a envelhecer. Não há coluna de validade — **quem valida é o relógio contra `inicio`**: no turno B, proposta cujo `inicio` já passou de `agora + ANTECEDENCIA_MINIMA` é tratada como inexistente e a resposta é uma rodada nova. Uma coluna `expira_em` seria um segundo relógio para manter sincronizado com o primeiro.

A tabela entra em `TABELAS` (`tests/conftest.py`), no `TRUNCATE` único.

## D5 — Como o lead escolhe: uma função pura

`domain/agendamento/escolha.py::escolher(texto, propostas, *, agora) -> Escolhida | NaoEscolheu`, sem I/O, no molde de `data_falada.py`. Três vias, nesta ordem:

1. **Ordinal** — "a primeira", "a segunda", "a terceira", "a última", "1", "2", "3". Casa contra a posição na lista gravada.
2. **Data** — `data_falada.resolver(texto, agora=agora)`; o `Instante` resultante casa a proposta cujo `inicio` bate exatamente. Quando a resolução é `Dia`, `Periodo` ou `Semana` e **exatamente uma** proposta cai dentro, ela é a escolhida; mais de uma é `NaoEscolheu`.
3. **Hora solta** — a hora sem dia ("11h", "às 11"), casada contra a hora local das propostas; exatamente uma é a escolhida. **Esta via não sai de `resolver`, e a razão é que a pergunta é outra**: aquele módulo responde "que data o lead está propondo" e por isso devolve `Ambigua` para hora que já passou hoje — "às 9h" ditas às 10h não são proposta de nada. Aqui a pergunta é "a qual das janelas já oferecidas o lead se refere", e todas são futuras por construção. Sem esta via, o lead que lê "quinta às 9h" e responde "9h" de manhã não escolheria nada.

Mais de uma candidata é sempre `NaoEscolheu`, nunca a primeira: chutar gravaria uma reserva que o lead não pediu, e o horário errado sai da agenda do corretor.

`NaoEscolheu` **não** produz texto: o turno cai fora e segue normal. Uma pergunta nossa aqui ("não entendi, qual dos três?") competiria com a resposta que o modelo daria a uma fala que pode não ter nada a ver com agendamento — o lead que responde "quanto é o condomínio?" no meio da escolha tem de receber o valor do condomínio.

Ordinal antes de hora porque "a segunda" é ambíguo entre ordinal e dia da semana (`segunda-feira`), e no contexto de uma lista de três a leitura ordinal é a que o lead quis. O custo declarado: o lead que responde "segunda" querendo o dia da semana recebe a segunda janela — e vê a data absoluta na pergunta de confirmação do turno B, que é exatamente a proteção que a RN-11.3 existe para dar (RT-10).

## D6 — A confirmação do turno C, e o que o turno NÃO diz

Turno C reconhece assentimento por `domain/agendamento/deteccao.py::confirmou` (`sim`, `isso`, `confirmo`, `pode marcar`, `pode ser`, `fechado`, `ok`, `perfeito`) e recusa por `recusou` (`nao`, `outro horario`, `nao posso`, `nao da`). Recusa devolve uma rodada nova de janelas; nem uma nem outra cai fora, e o turno segue normal.

Confirmado: `confirmar(session, reserva_id=..., agora=...)`, commit, e **depois do commit** `agendador_de_confirmacao.agendar(id)`. A ordem é a regra que a card escreve, e a razão é a de sempre: um job enfileirado antes do commit pode ser consumido por um worker que ainda não enxerga a linha.

**O turno não manda texto nenhum ao lead nesse caso, e isso é deliberado.** Quem é dona da mensagem de confirmação é a RN-12.1, e ela já está construída: `confirmacao.py::_avisar_lead` monta o texto com data, hora, endereço e nome do corretor e o envia ancorado na última mensagem do lead — que é justamente o "sim" deste turno. Um texto nosso aqui seria a segunda mensagem dizendo a mesma coisa, com menos dados.

O custo, declarado: **com o worker parado, o "sim" do lead fica sem resposta visível** enquanto o agendamento já está `CONFIRMADO` no banco. É o mesmo acoplamento que a TEC-170 assumiu quando decidiu que os três avisos saem de um job, e o desfecho do turno (`"agendamento_confirmado"`, valor novo em `ResultadoDoTurno`) é o que torna isso contável no log em vez de invisível.

`Expirado` — reserva vencida, atropelada, ou já confirmada — devolve uma rodada nova de janelas com a frase que diz que o horário não ficou reservado. É o terceiro cenário do Gherkin.

## D7 — Conflito: quem chama é `reservar_ou_alternativas`, e a CA-11.2 sai de graça

O turno B chama `reservar_ou_alternativas` e não `reservar`: em `Conflito` ela já devolve as janelas que sobraram, no mesmo corretor e respeitando a capacidade diária dele. O turno grava essas janelas como a rodada nova de propostas e diz ao lead que o horário foi tomado.

Dois leads confirmando o mesmo slot: um recebe `Reserva`, o outro recebe lista — **um agendamento, e alternativas para o outro**, que é a CA-11.2 inteira. Nada de novo é escrito para isso; a exclusão por intervalo da migration 0044 e a tradução de `IntegrityError` em `Conflito` (TEC-168) já faziam o trabalho e estavam sem chamador.

## D8 — Sem janela nas próximas 72 horas: o turno cai fora, e não promete nada

`janelas_alocadas` devolvendo lista vazia é o começo da TEC-169, e a card põe a lista de espera fora de escopo. A pergunta que sobra é o que dizer ao lead **hoje**, e há três respostas possíveis:

1. "Vou pedir para um corretor te propor um horário." — **recusada.** Nada cria essa tarefa. É literalmente a lição da TEC-174, que o CLAUDE.md registra: "já avisei um corretor" teve de ser reescrito porque nada notificava ninguém.
2. "Assim que abrir uma janela eu te aviso." — **recusada** pelo mesmo motivo, e pela guarda `test_promessa_ao_lead.py` (TEC-286), que existe para barrar exatamente esta frase.
3. **O turno cai fora e segue normal.** O modelo responde ao lead como responde hoje, sem oferecer horário e sem prometer retorno.

Fica a 3. Não é boa — é a menos falsa. Nenhum texto que caiba nesta card diz algo verdadeiro e útil ao mesmo tempo, e a que diria é a lista de espera da TEC-169. Isto vai no comentário da card como lacuna de produto: **um lead que pede visita numa semana lotada recebe uma resposta genérica e nada registra que ele pediu.**

O horizonte é 72 horas a partir de `agora`, o número da RN-11.5 — é ele que define o que conta como "sem disponibilidade".

Cai fora pelo mesmo caminho o caso de não haver corretor ativo.

**Lead sem qualificação gravada NÃO cai fora**, e essa parte mudou na implementação: o critério nasce vazio, critério vazio nunca tem match exato, e `alocar` cai no corretor generalista de plantão — que é o que a RN-11.2 manda fazer. Recusar o agendamento a quem ainda não foi qualificado seria inventar uma etapa que a RF-11 não tem.

## D8-bis — A data que o lead falou recorta a oferta, e a ambígua vira pergunta

A CA-11.1 pede horários **daquela quinta**, e não a grade dos próximos três dias. Quem faz a ponte entre a data falada e o motor é `data_falada::janelas_para`, que a TEC-167 construiu exatamente para isto e ficou sem chamador.

A diferença não é só o recorte. `janelas_alocadas` dá **uma janela por dia**, para espalhar a escolha entre datas — resposta certa para quem não nomeou dia. Com o dia nomeado, o que falta é a hora, e `janelas_para` dá até três no mesmo dia.

O caminho, em `conversa.py::_janelas_da_data_falada`: resolve a fala; para `Dia`, `Periodo` e `Instante`, aloca os candidatos daquela data (`alocar`, com a contagem de visitas do dia) e desce por eles até um ter janela livre. Não achando nada — ou sendo `Semana` ou `NaoReconhecida` —, cai para a grade de 72 horas em vez de deixar o lead sem resposta.

**`Ambigua` vira pergunta, e não chute.** `resolver` já devolve o texto exato a fazer ("Aos domingos não há atendimento. Pode ser sábado, 3 de outubro?"), e o resultado `Perguntou` o entrega sem gravar nada. É o RT-10 inteiro: chutar a data é visita marcada no dia errado.

## D9 — Onde o bloco entra em `_executar_turno`, e por que a função não é partida aqui

O bloco entra dentro de `turno.py::_executar_turno`, **depois** do desvio que chama `turno.py::_continuar_entrega` e **antes** da chamada a `montagem.py::montar_contexto` — a âncora verifica o nome, mas não localiza dentro de uma função de 2837 linhas; quem procurar o ponto acha pela linha `lote = await ler_apresentacao_da_mensagem(`. Três consequências, todas pretendidas:

- Fica abaixo das guardas de opt-out, atendimento humano e encerramento por escopo — todas vencem o agendamento.
- Fica abaixo da moderação de entrada: fala recusada não marca visita.
- Fica acima da chamada ao modelo: o caminho de agendamento não paga token nenhum.

Ele lê o estado do lead com `ler_estado` direto, e não pelo contexto: `criterio_de` precisa da qualificação, e montar contexto inteiro (resumo, histórico, âncora) para um caminho que não chama o modelo seria pagar o caro para não usar.

**A função não é partida nesta card, e a card pede que se considere.** O que ela ganha aqui é um bloco autocontido: uma chamada a `agendamento.conversa::atender` e um `_entregar_texto_fixo`, na ordem dos outros desvios determinísticos que já moram ali. A ordem de grandeza é de ~60 linhas numa função de 2837 — 2%, e nenhuma delas se entrelaça com o corpo que veio antes.

Partir `_executar_turno` é um trabalho de outra natureza e de outro tamanho: são 2837 linhas cuja ordem de efeitos colaterais é o contrato (o docstring de `executar_turno` gasta parágrafos explicando por que gravar a fala vem depois da entrega), e a suíte que a protege é a que leva 67 segundos. Misturar essa refatoração com a primeira ligação do agendamento à conversa faria um diff em que nenhuma das duas coisas é revisável — e a regressão de uma seria lida como defeito da outra. Vira card própria, e o comentário da TEC-371 a pede.

O que esta card faz pelo problema: **não o agrava**. O bloco novo é uma chamada e um retorno, não mais um trecho de lógica misturada ao resto.

## D10 — A porta de confirmação entra na assinatura, como a do resumo entrou

`executar_turno` e `_executar_turno` ganham `agendador_de_confirmacao: AgendadorDeConfirmacaoPort`, ao lado de `agendador: AgendadorDeResumoPort`. `AgendadorDeConfirmacaoNoop` é o default de todo teste que não é sobre agendamento — é para isso que ele existe desde a TEC-170 e não tinha chamador.

Quem escolhe a implementação é o `startup` do worker (`workers/main.py`), que já monta `AgendadorDeConfirmacaoArq(pool)` para a varredura e passa a montá-lo também para o turno.

`Gatilho.AGENDAMENTO_CONFIRMADO` **continua sem chamador**, e é preciso dizer por quê, porque esta é a card em que ele pareceria finalmente servir: a decisão de conversa da TEC-170 (Emenda E-01 da RN-12.1) é que o aviso ao corretor sai por e-mail, sem abrir handoff. Nada nesta card reabre isso.

## D11 — Os textos ao lead

Constantes de módulo em `domain/agendamento/mensagens.py`, ao lado das da TEC-170, **com acento** (TEC-267), registradas em `tests/unit/literais_ao_lead.py` — sem esse registro as guardas de acento e de promessa não olham para elas.

Cada janela é dita por `data_e_hora_absolutas` (dia da semana, dia do mês e hora), que é o formato que a RN-11.3 exige e que a TEC-167 já escreveu. Nenhum texto desta card diz "amanhã" ou "quinta que vem".

São cinco: a oferta de janelas, o pedido de confirmação de uma janela escolhida, o aviso de que o horário foi tomado com as alternativas, o aviso de que a reserva venceu com a oferta nova, e a oferta que segue uma recusa. Nenhum promete contato de ninguém.

A lista numera as janelas (`1.`, `2.`, `3.`), e isso não é estética: "a segunda" e "2" são as respostas mais curtas que o lead pode dar, e `escolha.py::escolher` as lê. Uma lista sem número deixaria o ordinal sem âncora visível.

**Não há texto de "não entendi qual".** Escolha que não resolve é `NaoEscolheu`, e `NaoEscolheu` cai fora — ver a D5.

## Testes

**Unitários** (`tests/unit/`), sem banco:

- `test_deteccao_de_agendamento.py`: `quer_agendar` sobre a faixa da D2, incluindo os quatro verbos que **não** disparam (`desmarcar`, `remarcar`, `reagendar`, `cancelar`) e a negação (`não quero marcar visita`).
- `test_escolha_de_janela.py`: ordinal, hora, "a última", `Dia` com uma e com duas propostas dentro, texto sem relação nenhuma → `NaoEscolheu`.
- O teste de tamanho de `literais_ao_lead.py` sobe com os cinco literais novos.

**Integração** (`tests/integration/`), com Postgres:

- `test_janelas_propostas.py`: a rodada nova substitui a anterior; proposta com `inicio` no passado é ignorada.
- `test_agendamento_pela_conversa.py`: os três turnos em sequência, terminando com uma linha `CONFIRMADO` e um enfileiramento.

**Features** (`tests/features/test_agendamento_pela_conversa.py`), um por cenário do Gherkin da card:

1. Pedido de horário → até 3 janelas, cada uma com data e hora absolutas (asserção sobre o texto, não sobre a lista).
2. Escolha → confirmação → `CONFIRMADO` no banco, e o enfileiramento acontecendo **depois** do commit (um fake de `AgendadorDeConfirmacaoPort` que consulta o banco por sessão própria no momento em que é chamado).
3. Reserva vencida → `confirmar` devolve `Expirado` → o lead recebe horários de novo.
4. Dois leads no mesmo slot → um `CONFIRMADO`, o outro com alternativas.

O cenário 2 é o único com uma asserção de ordem temporal, e ela é o ponto: "depois do commit" é regra da card e não decorre de nenhuma outra asserção.

## Emendas ao SRS

- **RN-11.1, RN-11.3, RN-11.4, CA-11.1, CA-11.2 — Emenda E-01 (TEC-371):** o caminho existe e é a conversa; três turnos, detecção determinística, propostas gravadas. E o que continua sem acontecer: sem janela em 72 horas o agente não oferece nada (D8), e reunião remota não tem vocabulário.
- **RN-11.5 — Emenda E-01 (TEC-371):** a regra continua sem código. O que esta card acrescenta é que a condição agora é **alcançável por um lead de verdade**, e o comportamento dela é cair no turno normal.
- **RN-12.1 — Emenda E-04 (TEC-371):** "nada na conversa confirma agendamento ainda", da Emenda E-01, deixa de ser verdade. O aviso continua saindo do job.
- **RN-12.2 — Emenda E-02 (TEC-371):** a Emenda E-01 dizia que nenhum lead recebe lembrete porque nenhum agendamento nasce de um lead de verdade. Passa a nascer; os lembretes da TEC-171 passam a ter linhas para varrer. Ler a resposta a eles continua sendo a TEC-372.
- **RN-17.1 — Emenda E-04 (TEC-371):** o motivo pelo qual os quatro indicadores de agendamento saem `null` era "nenhum caminho de produção cria agendamento". Deixa de valer. Trocar `null` por contagem é mudança de contrato do painel e é da E8; até lá os indicadores mentem por omissão em vez de por ausência, e isso é pior do que era.

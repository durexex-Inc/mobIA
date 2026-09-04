# TEC-183 — Agendar a cadência de reengajamento por temperatura

**Status:** desenhado em 2026-09-03, implementado em 2026-09-03 na branch `feat/tec-183-cadencia-de-reengajamento`.

**Card:** [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) — Must (MoSCoW). Origem: RF-13, RN-13.1, RN-13.4 (SRS v1.0, em `docs/srs/`). Épico de follow-up e opt-out.

**Branch:** `feat/tec-183-cadencia-de-reengajamento`.

**Destravada por [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151)** (temperatura) e **[TEC-182](https://eduardodurieuxlopes.atlassian.net/browse/TEC-182)** (opt-out), ambas mergeadas — eram os dois únicos bloqueios. Destrava [TEC-184](https://eduardodurieuxlopes.atlassian.net/browse/TEC-184) (conteúdo do follow-up), [TEC-185](https://eduardodurieuxlopes.atlassian.net/browse/TEC-185) (janela de 9h–20h), [TEC-186](https://eduardodurieuxlopes.atlassian.net/browse/TEC-186) (template fora das 24h), [TEC-187](https://eduardodurieuxlopes.atlassian.net/browse/TEC-187) (`DORMENTE`), [TEC-188](https://eduardodurieuxlopes.atlassian.net/browse/TEC-188) (teto anti-spam) e [TEC-172](https://eduardodurieuxlopes.atlassian.net/browse/TEC-172) (não comparecimento).

**Esta card é o pedido original de toda a sequência.** A cadeia era `TEC-146 → TEC-147 → TEC-150 → TEC-151 → TEC-183`, e as quatro primeiras foram feitas para chegar aqui.

## Objetivo

A história é da Anelise, gerente comercial: *"quero que nenhum lead morra por falta de retorno, para não perder venda por esquecimento do time"*. A card se atribui Must com a justificativa de que *"nenhum lead fica sem follow-up"* é uma das três frentes de ganho da proposta de valor — sem cadência automática, o produto entrega dois terços do que promete.

**O que esta card entrega:** a régua da RN-13.1 — quem está devido de follow-up, em que tentativa, e quando —, a trilha do que já disparou, e o reinício da RN-13.4 quando o lead responde.

**O que ela não entrega, e a card diz isso:** o conteúdo da mensagem (RN-13.2, TEC-184), a janela de horário (RN-13.3, TEC-185) e o teto anti-spam (RN-13.7, TEC-188) estão explicitamente fora do escopo. **A consequência é que nada é enviado ao lead.** A cadência decide e registra; quem fala é a TEC-184.

Isso não é uma entrega parcial disfarçada: a RN-13.2 proíbe follow-up sem informação nova (*"proibido 'oi, tudo bem?' solto"*), então mandar um texto provisório para "provar o caminho" violaria a regra de frente e queimaria o lead e o número. A régua é a metade que dá para construir sozinha, e é a metade que as outras cinco cards esperam.

## O que já existe, e que o desenho reusa

**A guarda de opt-out, escrita antecipando esta card.** O comentário de `GuardedOutbound.send` (`outbound/port.py`) diz literalmente: *"a TEC-183 vai criar um segundo caminho de envio. Quem HERDA desta classe ganha a guarda de graça, sem precisar lembrar dela."* Esta card não envia, então não herda ainda — mas consulta `esta_em_optout` pelo mesmo motivo, e a TEC-184 herdará.

**O molde de job periódico que varre o banco.** `sweep_stalled` (`workers/jobs/`) roda por `cron(...)` a cada 30 segundos, seleciona trabalho vencido por uma consulta e age. A varredura desta card é o mesmo molde com outro relógio.

**A temperatura, e a coluna que a guarda.** A TEC-151 deixou `lead_qualification.temperatura` gravada a cada turno com estado. É a entrada da régua, e o `NULL` dela é o que define quem fica de fora (D3).

**`Temperatura` como enum de domínio.** `context/temperatura.py`. A cadência indexa por ele, não por string solta.

## Decisões

### D1 — A cadência é derivada, não agendada

Não há linha `PENDENTE`. A varredura pergunta, a cada passagem, *"quem está devido agora?"*, e persiste apenas o que **disparou**.

O SRS descreve, na seção 5, uma entidade `FollowUp` com `agendado_para` e um `status` que inclui `PENDENTE` e `CANCELADO` — ou seja, um agendamento persistido. **Este desenho diverge, e a divergência é uma emenda declarada**, pelas três regras da própria card:

- **RN-13.4, "resposta cancela a cadência pendente e reinicia o ciclo".** Com agendamento persistido, isso é um `UPDATE ... SET status='CANCELADO'` em lote mais um reagendamento — dois caminhos de escrita que podem divergir da regra. Derivando, **não há nada para cancelar**: a âncora se move e a aritmética recomeça.
- **"Mudança de temperatura recalcula a cadência restante."** Com `agendado_para` gravado, o intervalo fica congelado no instante do agendamento, e a mudança vira reescrita das linhas pendentes. Derivando, a próxima varredura lê a `temperatura` de hoje e indexa outra tupla.
- **"Os intervalos vêm de configuração e podem ser ajustados sem deploy."** Um horário gravado no banco é imune a mudança de configuração — a config só valeria para agendamentos futuros, e as pendentes ficariam com a régua velha, em silêncio.

**O que se perde:** o dashboard não consegue mostrar *"o próximo follow-up sai às 14h"*, só o que já saiu. Nenhuma card pede isso hoje, e a TEC-192 (lista de leads) ordena por score, não por cadência.

### D2 — Os deslocamentos são a partir da âncora, e não encadeados

A RN-13.1 diz *"contada a partir da última mensagem do lead"*, e a CA-13.1 confirma com número: parou às 18h, follow-up às 20h. Então a tentativa *N* vence quando

```
agora >= ultima_fala + CADENCIA[temperatura][N-1]
```

e **não** "24 horas depois do follow-up anterior". Um lead `QUENTE` recebe em `+2h`, `+24h`, `+3d` e `+7d` contados sempre da mesma âncora.

A leitura importa porque muda o comportamento: encadeando, um atraso na varredura empurraria toda a cauda; ancorando, um disparo atrasado não desloca os seguintes. A segunda é a que a regra descreve.

**`src/mobia/domain/followup/cadencia.py`**, pura no molde de `score.py`, `temperatura.py` e `gatilhos.py` — sem I/O, sem banco, sem chamada ao modelo:

```python
CADENCIA: dict[Temperatura, tuple[timedelta, ...]] = {
    Temperatura.QUENTE: (2h, 24h, 3d, 7d),
    Temperatura.MORNO:  (24h, 4d, 10d),
    Temperatura.FRIO:   (3d, 14d),
}

def tentativa_devida(
    *, temperatura: Temperatura, ultima_fala: datetime,
    ja_disparada: int, agora: datetime,
) -> int | None: ...
```

Devolve o número 1-based da tentativa devida agora, ou `None` — porque nenhuma venceu ainda, ou porque a cadência esgotou.

**Devolve a MAIOR tentativa vencida, não a próxima — e essa é a decisão mais fácil de errar do desenho.** Um lead `QUENTE` calado há dez dias tem as quatro vencidas ao mesmo tempo. Devolvendo "a próxima", ele receberia uma por varredura: **quatro follow-ups em vinte minutos**, para alguém que sumiu há dez dias. Devolvendo a maior, ele recebe a quarta e só. As três que passaram não são "perdidas" — os deslocamentos são absolutos desde a âncora (D2), então o momento de mandar a de `+2h` acabou há dez dias, e mandá-la agora seria entregar uma mensagem cujo pressuposto de tempo já é falso.

**Por isso `ja_disparada` é o `MAX(tentativa_numero)` sob a âncora, e não um `COUNT`.** Com contagem, o lead do exemplo receberia a tentativa 4 (contagem 0 → 1) e, na varredura seguinte, a régua acharia que só uma foi feita e dispararia a 2 — refazendo para trás. Com o máximo, `4` fecha a cadência inteira de uma vez. A diferença só aparece quando há salto, que é exatamente o caso que este parágrafo existe para cobrir.

A função é então: o maior `N` tal que `agora >= ultima_fala + CADENCIA[temperatura][N-1]` **e** `N > ja_disparada`; `None` se não houver.

**Tudo keyword-only**, pela razão que a TEC-150 aplicou às contagens de `calcular_score` e a TEC-151 aos flags de `temperatura_de`: `ultima_fala` e `agora` são dois `datetime` adjacentes, e trocá-los não levanta, não é erro de tipo, não é visível ao mypy, e devolve a tentativa errada em silêncio.

**Constantes de módulo, e não configuração.** A card pede intervalos ajustáveis sem deploy; isso é um subsistema (persistir, autorizar, invalidar cache) e pertence ao épico de configuração (RF-19), exatamente como a TEC-150 decidiu para os pesos do score. Lacuna declarada, e o mesmo precedente.

### D3 — Lead sem temperatura não entra na cadência

A varredura exige `temperatura IS NOT NULL`.

Depois da TEC-151, `NULL` significa uma de duas coisas, e nenhuma pede insistência: linha anterior àquela card, ou **lead que nunca disse nada qualificável** — o turno classificado `FORA_DE_ESCOPO`/`INDEFINIDA` sem campo extraído, que pelo caminho *"Deliberadamente NAO cria linha"* de `gravar_estado` nem chega a ter linha em `lead_qualification`.

A RN-13.1 prescreve cadência para três temperaturas. Escolher uma para o nulo seria inventar uma quarta linha na tabela — e mandar follow-up para quem o sistema classificou como fora de escopo, sobre o qual, por definição, não há informação nova a trazer (RN-13.2).

**Consequência declarada:** quem escreveu antes da TEC-151 e nunca mais falou não recebe follow-up. Volta a ser elegível no primeiro turno com estado, que é quando a coluna passa a existir.

### D4 — A tabela `followups`, append-only, e a âncora que a torna legível

Migration `0015`.

| coluna | tipo | nota |
|---|---|---|
| `id` | `UUID` PK | |
| `channel` | `String(32)` | o par de `lead_qualification` |
| `conversation_key` | `String(64)` | |
| `tentativa_numero` | `smallint` | posição na cadência, 1-based |
| `temperatura` | `String(8)` | a do momento do disparo |
| `ancora_em` | `timestamptz` | a última fala do lead que gerou este disparo |
| `devido_em` | `timestamptz` | `ancora_em + CADENCIA[temperatura][n-1]` |
| `created_at` | `timestamptz` | `server_default=clock_timestamp()` |

**`ancora_em` é a coluna que faz o desenho fechar.** Descobrir *"até que tentativa a cadência já foi desde que o lead falou pela última vez"* — que é o `ja_disparada` da D2 — vira `SELECT MAX(tentativa_numero) ... WHERE ancora_em = <âncora atual>`. Igualdade exata, porque a âncora **é** o `created_at` daquela mensagem, não uma aproximação.

Isso resolve a pegadinha do modelo derivado: se `ja_disparada` olhasse a vida inteira, um lead que respondeu e reiniciou o ciclo entraria com o orçamento já gasto e nunca mais receberia nada. E torna o reinício da RN-13.4 **auditável** em vez de implícito — as duas séries ficam lado a lado na tabela, cada uma sob a sua âncora.

**`temperatura` é gravada, e é redundante com `lead_qualification`.** De propósito: ela explica *por que* foram N tentativas, e a coluna viva já terá mudado quando alguém for ler a trilha. Mesmo raciocínio dos cinco fatores em `lead_score_audit`.

**`UNIQUE (channel, conversation_key, ancora_em, tentativa_numero)`.** Duas varreduras concorrentes veriam o mesmo candidato devido e ambas inseririam. Não dá para usar `FOR UPDATE SKIP LOCKED` sobre a agregação que produz os candidatos, então a defesa é a restrição — mesmo espírito dos `CHECK` da `0014` e da `0012`: a invariante mora no banco, e não na esperança de que só um worker rode.

**`CHECK (tentativa_numero > 0)`**, porque 1-based é contrato e não convenção.

**Três colunas do modelo de dados do SRS ficam de fora:** `status` (não há `PENDENTE` nem `CANCELADO` num modelo derivado — ver a emenda), `usou_template`/`template_nome` (RN-13.6, TEC-186) e `enviado_em` (nada é enviado, TEC-184).

**Sem FK para `messages` nem para `lead_qualification`**, pela razão da `0010` e da `0012`: a retenção da trilha não pode ser encurtada por cascata da limpeza de outra tabela.

Índice `ix_followups_lead (channel, conversation_key, ancora_em)` — a consulta quente é o `MAX(tentativa_numero)` por âncora, uma vez por candidato por varredura.

### D5 — A varredura, e por que de 5 em 5 minutos

`cron(sweep_followups, minute={0, 5, 10, ...})` em `workers/main.py`, ao lado do `sweep_stalled`.

**E não de 30 em 30 segundos como o irmão.** O menor intervalo de qualquer temperatura na RN-13.1 é **2 horas**; precisão de segundos não compra nada e custa uma varredura que agrega `messages`. Cinco minutos deixa o erro máximo de disparo em cinco minutos sobre uma janela de duas horas.

Os candidatos saem de um `GROUP BY` sobre `messages` juntado com `lead_qualification`, com dois cortes baratos aplicados antes de qualquer trabalho:

- `temperatura IS NOT NULL` — a D3.
- `MAX(created_at) < now() - 2h` — o menor intervalo que existe em qualquer temperatura, então nada abaixo disso pode estar devido.

A âncora usa a mesma definição de fala do lead que `contar_mensagens_do_lead` fixou: `direction = INBOUND` e `bloqueada_em IS NULL`. **Não é uma segunda leitura desse fato**, é a mesma regra — e a docstring daquela função existe precisamente para que a próxima card não escreva uma terceira.

Para cada candidato, em Python:

1. `esta_em_optout(...)` → pula.
2. `tentativa_devida(...)` devolve `None` → pula.
3. Senão: `INSERT` na `followups` e `log.info("followup.devido", ...)`.

**O opt-out é consultado por candidato, e não juntado na consulta.** `esta_em_optout` é a única implementação daquele fato, e escrevê-lo uma segunda vez em SQL criaria duas fontes que divergem em silêncio — o defeito que a TEC-146 gastou uma card inteira consertando. O preço é uma consulta por candidato, e os candidatos são poucos por construção: só quem tem temperatura, calou há mais de duas horas e ainda não esgotou.

**O evento no log é o entregável observável desta card**, no molde de `lead.qualificado` e `lead.esquentou`: `followup.devido` com canal, tentativa, temperatura e a âncora. Sem texto do lead — a regra de PII que `moderacao.entrada_bloqueada` respeita vale igual aqui.

## Fluxo

1. O cron dispara `sweep_followups` a cada 5 minutos.
2. Uma consulta devolve os candidatos: leads com `temperatura` não nula cuja última fala não bloqueada tem mais de 2 horas, com a âncora e a maior tentativa já disparada sob aquela âncora.
3. Para cada um, na ordem: opt-out barra; `tentativa_devida` decide; o `INSERT` registra.
4. A restrição `UNIQUE` absorve a corrida entre duas varreduras — a segunda falha o `INSERT` daquela linha e segue.
5. Nada é entregue ao lead. A TEC-184 plugará a geração e o envio sobre esta trilha.

## Testes

**Basenames distintos entre `unit` e `integration`:** `tests/unit/test_cadencia.py` e `tests/integration/test_sweep_followups.py`. Colisão de basename aborta a coleta da suíte inteira, não aparece no arquivo isolado, e já custou duas cards (`a3d1840`, `424ed72`). `test_sweep_stalled.py` já existe em `integration` — o nome novo não colide.

**Os cinco cenários da card viram testes diretos.** A tabela de tentativas por temperatura (4/3/2) vira parametrização; o primeiro disparo do lead `QUENTE` às 2 horas; a resposta cancelando as restantes; a conversa silenciada; o lead com opt-out.

**A conversa silenciada é o único que não dá para escrever de verdade** — o estado não existe (lacuna 2). Fica registrado como teste ausente e nomeado na lacuna, em vez de virar um teste que finge cobrir algo.

**Quatro que a card não pede e o desenho exige:**

- **O reinício zera a régua.** Duas tentativas sob a âncora A, o lead responde, e a tentativa 1 volta a ser devida sob a âncora B. É o teste que morre se alguém olhar `ja_disparada` pela vida inteira em vez de por âncora.
- **O lead muito atrasado recebe UMA tentativa, a última.** Dez dias de silêncio com zero disparos devolve `4` e fecha a cadência; a varredura seguinte devolve `None`. É o teste que morre se alguém trocar o máximo pela próxima, ou o `MAX` por um `COUNT`.
- **A mudança de temperatura encurta a cadência.** Lead `QUENTE` com três tentativas que esfria para `MORNO` não recebe a quarta, porque `MORNO` tem três.
- **A restrição `UNIQUE` recusa a segunda inserção** da mesma tentativa sob a mesma âncora.
- **Lead com `temperatura` nula não aparece entre os candidatos**, nem com dois meses de silêncio.

## Emendas ao SRS

**RN-13.4** ganha `Emenda E-01` como item aninhado, sem tocar no texto de 22/08, mais uma linha na tabela do topo. A numeração é **por regra** — há várias `E-01` no documento, cada uma de uma regra diferente.

O teor: não há cadência pendente a cancelar, porque não há agendamento persistido. A resposta do lead move a âncora e a cadência recomeça por aritmética; o efeito observável da regra é idêntico. A consequência declarada é que a entidade `FollowUp` da seção 5 perde `PENDENTE` e `CANCELADO` do enum de status, e que `agendado_para` vira `devido_em` — calculado, não agendado.

## Lacunas declaradas

1. **Nada é enviado ao lead.** A card grava a tentativa e emite `followup.devido`; o texto e a entrega são da TEC-184. Enquanto ela não existir, a tabela acumula tentativas que ninguém mandou — e é isso que se quer, porque a alternativa violaria a RN-13.2.
2. **A conversa silenciada não é checada.** A RN-13.4 e o critério de aceite pedem que conversa assumida pelo corretor não receba disparo, e esse estado não existe: é a TEC-179. Só o opt-out tem produtor hoje. **Quando a TEC-179 existir, o predicado entra na mesma lista de guardas da D5**, ao lado de `esta_em_optout`.
3. **O `devido_em` não respeita a janela de 9h–20h**, ao contrário do que o modelo de dados do SRS afirma sobre `agendado_para` (*"já ajustado à janela da RN-13.3"*). É a TEC-185, e até lá o horário calculado pode cair de madrugada.
4. **O teto anti-spam da RN-13.7 não é aplicado** (TEC-188) e **`DORMENTE` não é marcado** (RN-13.5, TEC-187). A cadência simplesmente para de disparar quando esgota, sem registrar que esgotou.
5. **Os intervalos são constantes de módulo**, não configuração viva, contrariando a letra da card. Mesmo precedente e mesma lacuna que a TEC-150 declarou para os pesos do score; pertence ao épico de configuração (RF-19).
6. **A varredura agrega `messages` a cada passagem.** Aceitável no volume de MVP e a cada 5 minutos, mas é varredura, e o índice `ix_messages_timeline` serve *"a última mensagem de uma conversa"*, não *"todas as conversas cuja última fala é antiga"*. Quando doer, a saída é uma coluna de âncora denormalizada em `lead_qualification` — que o turno já tem sob lock e escreveria de graça. Não é feito agora porque seria uma segunda fonte para um fato que `messages` já guarda, sem dor medida que a justifique.
7. **`QUENTE` é quase inalcançável por faixa, então a cadência de 4 tentativas quase não roda.** São três totais possíveis até a TEC-158, e o teto `MORNO` da TEC-151 apertou mais. Na prática a maioria dos leads recebe a régua de `MORNO` ou `FRIO` — mais lenta e mais curta do que o SRS desenhou. Decidido em 02/09/2026, não é defeito desta card, **e não parecerá bug em lugar nenhum**: cada card está correta em relação à própria regra.
8. **Um lead cuja última fala foi bloqueada pela moderação usa a fala anterior como âncora.** É consequência de reusar a definição de `contar_mensagens_do_lead` (`bloqueada_em IS NULL`), e é o comportamento certo — um turno que o resto do produto trata como não-dito não deveria adiar o follow-up. Fica declarado porque surpreende quem lê a consulta.

## Fora de escopo

- O conteúdo da mensagem de follow-up — RN-13.2, [TEC-184](https://eduardodurieuxlopes.atlassian.net/browse/TEC-184).
- A janela de 9h às 20h no fuso do lead — RN-13.3, [TEC-185](https://eduardodurieuxlopes.atlassian.net/browse/TEC-185).
- O template aprovado fora da janela de 24 horas — RN-13.6, [TEC-186](https://eduardodurieuxlopes.atlassian.net/browse/TEC-186).
- O encerramento em `DORMENTE` — RN-13.5, [TEC-187](https://eduardodurieuxlopes.atlassian.net/browse/TEC-187).
- O teto de 4 mensagens não respondidas — RN-13.7, [TEC-188](https://eduardodurieuxlopes.atlassian.net/browse/TEC-188).
- O silenciamento quando o corretor assume — [TEC-179](https://eduardodurieuxlopes.atlassian.net/browse/TEC-179).
- Configuração alterável sem deploy — RF-19.

# TEC-151 — Derivar temperatura e aplicar os gatilhos que forçam QUENTE

**Status:** desenhado em 2026-09-03, implementado em 2026-09-03 na branch `feat/tec-151-temperatura-do-lead`.

**Card:** [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151) — Must (MoSCoW). Origem: RF-06, RN-06.2, RN-06.3, RN-06.5 (SRS v1.0, em `docs/srs/`). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144).

**Branch:** `feat/tec-151-temperatura-do-lead`.

**Destravada pela [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150)**, que está mergeada, e apoiada na [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152), que também está — o gancho de recálculo que esta card estende é dela. Adiante: a [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) (cadência de reengajamento, que lê temperatura), o dashboard da [TEC-192](https://eduardodurieuxlopes.atlassian.net/browse/TEC-192) (que é quem faz a intervenção humana da RN-06.3) e a [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158) (busca de imóveis, que acende o quinto fator do score).

## Objetivo

A história é do Paulo, corretor: *"quero que quem pede uma visita chegue até mim como quente mesmo com score baixo, para não perder a pessoa que está pronta para agir"*.

O contorno, sem esta card, não existe: o score é calculado a cada turno desde a TEC-152 e **ninguém o traduz em nada**. Não há temperatura em lugar nenhum do sistema — a palavra `QUENTE` aparece hoje apenas em comentários de `score.py`, descrevendo uma faixa que nenhum código aplica.

**O que esta card entrega:** a faixa da RN-06.2, os três gatilhos da RN-06.3, a persistência que faz o forçamento sobreviver ao recálculo, e o evento da RN-06.5 na borda de esquentar.

**O que ela não entrega, e a card diz isso:** a entrega da notificação. *"A entrega da notificação em si depende do handoff (E7) — link a criar quando aquele épico existir."* E7 não existe: não há épico, não há consumidor, não há conteúdo de mensagem definido. A RN-06.5 vira um evento estruturado no log, e a lacuna fica declarada em vez de simulada.

## O que já existe, e que o desenho reusa

**O gancho de recálculo, já no lugar certo.** `registrar_recalculo` (`context/repositorio.py`) roda a cada turno com estado, dentro da transação do estado, e já tem em mãos as três coisas de que esta card precisa: o `SELECT ... FOR UPDATE` sobre a linha de `lead_qualification`, o `Score` novo recalculado sobre aquela linha, e a recusa que saiu dela. Esta card não cria gancho nenhum — ela cresce dentro do que a TEC-152 construiu.

**A decisão que a TEC-152 nomeou e recusou tomar.** A seção de lacunas dela diz: *"Se a TEC-151 ler daqui em vez de recalcular, a tabela de auditoria vira carga viva do produto — e uma tabela que a retenção pode expurgar deixa de ser lugar seguro para o estado corrente. A decisão é da TEC-151, e esta card não a toma."* Ela é tomada na D3, e a resposta é não.

**O molde de detector determinístico sobre a fala do lead.** `optout/deteccao.py` (TEC-182) é uma função pura sobre o texto decifrado, com duas faixas de termo, normalização sem acento e a assimetria de erro raciocinada na docstring. A D2 é o mesmo molde com a assimetria invertida, e a inversão é o ponto.

**`corpo`, o texto decifrado, já no topo de `executar_turno`.** `pediu_optout(corpo)` já é chamado ali, na linha seguinte ao `decrypt`. O detector desta card entra ao lado, no mesmo ponto do fluxo e sobre o mesmo insumo.

**A entrada bloqueada pela moderação já retorna antes do gancho.** `executar_turno` devolve por `_entregar_texto_fixo` quando `veredito.bloqueado`, e nunca chega ao bloco transacional. Fala bloqueada não pode forçar `QUENTE` — e isso sai de graça, sem guarda nenhuma, coerente com o contrato de `mensagens_do_lead`, que exclui `bloqueada_em IS NOT NULL` da contagem de engajamento pela mesma razão: um turno que o resto do produto trata como não-dito não pode virar sinal aqui.

**O molde do evento de borda.** `lead.qualificado` (`turno.py`) é emitido **depois do commit**, e só na travessia. O evento desta card copia a forma, inclusive o defeito de reemissão — ver a D6 e a lacuna 5.

## O que esta card herda decidido, e não redecide

**`QUENTE ≥ 70` fica como o SRS escreve.** Decisão do usuário em 02/09/2026, tomada antes desta card começar, quando a TEC-150 revelou que o score topa em **75** sem catálogo (o fator de aderência vale 20 e contribui zero até a TEC-158). A pergunta era recalibrar os cortes para o teto real ou aceitar a consequência; a escolha foi aceitar.

**A consequência não é sutil, e é insumo desta card.** Até a TEC-158, só três totais alcançam 70: `{70, 72, 75}`. Cada um exige, simultaneamente, os quatro campos obrigatórios, `urgencia == IMEDIATA`, forma de pagamento declarada e engajamento. Um lead que não seja `IMEDIATA` topa em **65**. **`QUENTE` por faixa não é uma faixa — é uma conjunção de quase-máximos.** A enumeração completa está na seção de lacunas da TEC-150.

É por isso que os gatilhos da RN-06.3 não são um detalhe de borda: hoje eles são o **caminho principal** para um lead ser `QUENTE`, e não a exceção que a card sugere ao chamá-los de "independentemente do score". A card já sabia disso na prioridade que se atribuiu: *"os gatilhos são o que impedem que a régua numérica atrapalhe um lead evidentemente pronto; sem eles o score vira armadilha."*

## Decisões

### D1 — A faixa é função pura, em `context/temperatura.py`

Molde de `score.py`, `auditoria.py` e `qualificacao.py`: sem I/O, sem banco, sem chamada ao modelo.

```python
class Temperatura(StrEnum):
    QUENTE = "QUENTE"
    MORNO = "MORNO"
    FRIO = "FRIO"

CORTE_QUENTE = 70
CORTE_MORNO = 40

def temperatura_de(score: Score, *, qualificado: bool, forcada: bool) -> Temperatura: ...
```

**`forcada` curto-circuita antes de olhar o score.** É literalmente o cenário de aceite da card — *"um lead com score 35 e temperatura FRIO… a temperatura passa a QUENTE… e o score permanece 35"*. O score não é tocado por lugar nenhum desta card; a temperatura deixa de ser função dele.

**Os dois flags são keyword-only**, pela razão que a TEC-150 já aplicou às duas contagens de `calcular_score`: são dois `bool` adjacentes, trocar a ordem num chamador não levanta, não é erro de tipo, não é visível ao mypy, e devolve temperatura errada em silêncio.

**`Score` e não `int`.** A função só usa `.total`, e receber o total seria mais simples. Recebe o `Score` porque o chamador tem o objeto e passar `.total` no lugar dele abriria a porta para alguém passar `total_anterior` da trilha ou um total montado à mão — o tipo é a única coisa que impede a temperatura de ser derivada de um número cuja procedência ninguém garante.

**`score is None` não é caso.** `calcular_score(None)` devolve zerado, mas quem chama esta função já sabe que há linha — sem linha não há sujeito, e o gancho retorna antes (D5). Aceitar `None` aqui exigiria escolher entre `FRIO` e "sem temperatura" para um lead que não existe, e as duas respostas seriam invenção.

### D2 — Os gatilhos são detector determinístico, em `context/gatilhos.py`

Molde de `optout/deteccao.py`: função pura sobre o texto decifrado, normalização para minúsculas sem acento e sem pontuação, faixas de termo como constantes de módulo.

```python
MOTIVO_VISITA = "VISITA"
MOTIVO_CORRETOR = "CORRETOR"
MOTIVO_PROPOSTA = "PROPOSTA"

def gatilhos_de(texto: str) -> tuple[str, ...]: ...
```

**Determinístico e não campo novo no schema do classificador.** O campo pegaria paráfrase que regex nenhum pega, e teria sido a escolha melhor num orçamento folgado. O orçamento não é folgado: `test_a_margem_do_orcamento_do_prompt_e_deliberada` fixa o teto em **655**, o líquido de hoje é 648,8 e a margem é **6,2**. O campo `recusou` da TEC-148 custou 17,6, e um campo novo custaria a mesma ordem — três vezes a margem inteira. O ritual do `CLAUDE.md` manda perguntar *"o que sai do prompt para o novo texto entrar?"* antes de subir o número, e esta card não tem resposta para essa pergunta: nada em `SISTEMA_DO_AGENTE` está sobrando. **O detector custa zero de orçamento, e a margem de 6,2 fica intacta.**

**Tupla e não motivo único.** *"quero fazer uma proposta e agendar visita"* casa dois. Motivo único exigiria regra de precedência, e precedência aqui descarta informação real — o mesmo argumento da D4 da TEC-152 contra uma coluna única de causa. `ARRAY(String)` já tem dois precedentes na casa (`perguntados_sem_resposta`, `campos_recusados`).

**A assimetria de erro é o INVERSO do opt-out, e por isso a faixa inequívoca é estrita.** No opt-out, deixar de detectar é violação de LGPD e detectar demais é prejuízo comercial, então a faixa inequívoca é generosa. Aqui os dois lados são:

- **Falso negativo:** um lead pronto para agir não chega ao topo da fila do corretor. Ruim, e recuperável — o lead continua na conversa, o score continua subindo, e o próximo turno pode disparar.
- **Falso positivo:** força `QUENTE` **permanentemente** (a RN-06.3 diz "até intervenção humana") *e* toca o telefone do corretor. **Não existe tela para desfazer** — a TEC-192 é a dona da intervenção humana e não existe. O erro é invisível, permanente, e custa a confiança do corretor na fila, que é o único produto que a RF-06 entrega.

Permanente e sem desfazer vence recuperável. **Faixa estrita.**

**O corpus já tem o caso que a estritez protege.** `evals/corpus/compra.yaml:318` — *"voces tem plantao de visita no fim de semana?"*. É pergunta sobre horário de funcionamento, não pedido de visita, e um detector que casasse `visita` em qualquer posição marcaria esse lead `QUENTE` para sempre. Os dois pedidos reais do corpus casam: *"quero agendar visita no apartamento"* (`compra.yaml:139`) e *"da pra remarcar uma visita pra essa semana?"* (`follow_up.yaml:18`).

**O critério de termo, então: o verbo de agendamento junto do objeto, e não o objeto sozinho.** `agendar visita`, `marcar visita`, `remarcar visita`, `agendar uma visita` casam; `visita` sozinho não. Mesma forma que fecha a colisão no opt-out, onde é o objeto de mensageria que faz `"pare de me mandar mensagens"` não colidir com `"pare de mandar apartamento sem vaga"`. **O custo aceito é de recall**, e fica declarado: quem escrever *"posso ver o apartamento amanhã?"* não dispara.

**`CORRETOR` e a RN-04.6 se sobrepõem, e esta card não unifica.** A RN-04.6 — *"pedido explícito de falar com humano interrompe o fluxo imediatamente e cria handoff prioritário (RF-16), sem tentativa de retenção"* — descreve quase o mesmo sinal, e também não tem implementação. Duas detecções do mesmo fato divergiriam em silêncio, que é o defeito que a TEC-146 gastou uma card inteira consertando. **Mas unificar exige a card da RN-04.6, que não existe**, e adivinhar a assinatura dela aqui é pior que declarar a sobreposição. Fica na lacuna 6, para quem escrever aquela card achar escrito em vez de descobrir.

### D3 — A temperatura mora em `lead_qualification`, e não na trilha de auditoria

Migration `0014`, três colunas:

| coluna | tipo | nota |
|---|---|---|
| `temperatura` | `String(8)` nulável | `NULL` = linha anterior a esta card, nunca recalculada. **É contra isto que a borda da D6 compara** |
| `temperatura_forcada_em` | `timestamptz` nulável | `NULL` = não forçada. Ver abaixo sobre `COALESCE` |
| `temperatura_forcada_motivos` | `ARRAY(String(16))` nulável | União entre turnos, molde de `campos_recusados` |

**Aqui e não em `lead_score_audit`, e é a decisão que a TEC-152 deixou.** Ler a temperatura anterior da última linha da trilha teria custado zero coluna e zero migration — os dois insumos já estão em mãos dentro de `registrar_recalculo`. Seria errado por duas razões, e a segunda é a grave:

- A D3 da TEC-152 grava **só quando o `Score` muda**. Um turno em que um gatilho dispara sem o score se mover não produz linha nenhuma, então a trilha não teria onde guardar o forçamento.
- A trilha tem retenção de 12 meses (RNF-18) e é expurgável. **Um lead antigo cujo último registro foi expurgado voltaria a parecer nunca-calculado, e reemitiria a notificação de esquentou como se tivesse acabado de esquentar.** É exatamente o "carga viva do produto" que a TEC-152 nomeou.

**Aqui e não em tabela nova.** `lead_qualification` já guarda o que o sistema concluiu e não o que o lead escreveu — a docstring do modelo diz isso, e `perguntados_sem_resposta` e `campos_recusados` já vivem lá pela mesma razão. E o gancho já tem essa linha travada: três colunas ali custam **zero leitura e zero lock a mais**. Uma tabela append-only daria histórico e auditaria a intervenção humana de graça, mas a intervenção humana não existe (TEC-192), e desenhar a tabela do histórico de um evento sem produtor é construir para dois consumidores que não existem.

**`CHECK (temperatura_forcada_em IS NULL OR temperatura = 'QUENTE')`.** Forçado implica `QUENTE`; sem o `CHECK`, uma linha pode afirmar as duas coisas contrárias e nada reclama. Mesmo espírito dos dois `CHECK` da `0012`, que existem para impedir a denormalização de mentir. Linha anterior a esta card passa — os dois `NULL`.

**Sem `CHECK` sobre os valores de `temperatura`.** `intencao`, `urgencia` e `forma_pagamento` são todas `String` com enum no domínio e nenhuma restrição no banco. Seguir a casa.

**`temperatura_forcada_em = COALESCE(temperatura_forcada_em, clock_timestamp())`.** O carimbo é o do **primeiro** forçamento, não do último. É o que "permanece até intervenção humana" torna interessante: quando esquentou, e há quanto tempo ninguém interveio. `clock_timestamp()` e não valor do cliente, pela razão da `0010` e da `0012` — o relógio de cada máquina escrevendo a coluna faria um skew inverter a ordem de dois fatos do mesmo lead; e `clock_timestamp()` e não `now()`, porque `now()` congela no primeiro statement da transação, vários statements antes deste.

**Os motivos unem, não sobrescrevem.** Lead pede visita no turno 1 (`VISITA`) e menciona proposta no turno 5 (`PROPOSTA`): a coluna acumula os dois. União no SQL, na forma que `gravar_estado` já usa para a recusa — `coalesce(coluna, '{}') || excluded`, com o `coalesce` existindo justamente porque `NULL || qualquer coisa` é `NULL` em Postgres. As duas alternativas descartam informação de forma assimétrica: "primeiro vence" esconde o que veio depois, "último vence" perde justamente o motivo que forçou. A união não tem esse lado.

**`CHECK (temperatura_forcada_em IS NULL OR cardinality(temperatura_forcada_motivos) > 0)`.** Molde do `CHECK (cardinality(causas) > 0)` da `0012`, e existe pela mesma razão: uma linha que afirma que o lead foi forçado a `QUENTE` sem nomear o que o forçou é a mesma forma de mentira que o `CHECK` do total impede. `NOT NULL` cobriria metade — o array vazio passaria.

**`NULL` e `{}` não são sinônimos** em `temperatura_forcada_motivos`, como nas duas colunas de array vizinhas: `NULL` é "não forçada" (e é o único estado que o `CHECK` acima admite junto de carimbo nulo), `{}` é o estado que os dois `CHECK` juntos tornam inalcançável. Quem lê trata os dois iguais (`or ()`), e nunca grava `NULL` querendo dizer vazio.

### D4 — O forçamento não é rebaixado, e a garantia tem duas metades

O cenário 3 da card: *"Dado um lead com temperatura forçada a QUENTE por pedido de visita, quando o score é recalculado e continua em 35, então a temperatura permanece QUENTE."*

Isso não é um `if` no chamador. É a leitura de `temperatura_forcada_em` da linha travada alimentando o `forcada` da D1: **se a coluna não é nula, `temperatura_de` devolve `QUENTE` sem olhar o score**, e nenhum recálculo tem como rebaixar. A regra de "não rebaixa" mora no mesmo lugar que a regra de "qual é a temperatura", e as duas não têm como divergir — mesma forma que a tupla vazia de `causas_do_recalculo` é o sinal de "não grave".

**`forcada` tem duas metades, e a persistida é a que o cenário 3 exige:**

```python
forcada = estado.temperatura_forcada_em is not None or bool(gatilhos)
```

O segundo termo força **agora** — é o cenário 2 da card, o pedido de visita chegando neste turno. O primeiro mantém forçado **depois** — e é o único que responde ao cenário 3, porque **o turno que rebaixaria é justamente um turno sem gatilho**: o lead pediu visita há três turnos, agora só respondeu "ok", e `gatilhos` está vazio. Sem o termo persistido, `temperatura_de` voltaria a olhar o score e devolveria `FRIO`.

A ordem dos termos não é indiferente para leitura, ainda que o `or` seja comutativo: o estado persistido vem primeiro porque é o invariante, e o gatilho do turno é o que o cria.

### D5 — O gancho cresce; não ganha irmão

`registrar_recalculo` já tem o lock, a linha fresca e o `Score` novo. Uma segunda função relockaria a mesma linha e reabriria a questão de estado velho que a D2 da TEC-152 fechou — e a fecharia pior, porque a segunda leitura viria depois da primeira e as duas poderiam discordar.

A assinatura ganha os gatilhos do turno e o retorno cresce:

```python
@dataclass(frozen=True)
class Recalculo:
    trilha: LeadScoreAudit | None
    temperatura: Temperatura
    anterior: Temperatura | None   # None = coluna NULL, primeiro calculo


async def registrar_recalculo(
    session, *, channel, conversation_key, gatilhos: tuple[str, ...] = ()
) -> Recalculo | None: ...
```

**`None` continua significando "não havia sujeito", e nunca "não mudou nada".** É a distinção que `score.py` já faz entre ausência de sujeito e nota zero, e o retorno atual a colapsa (hoje `None` cobre os dois casos). O campo `trilha` carrega o segundo sentido, que é o único que o chamador de hoje usa.

**A ordem interna inverte.** Hoje a função retorna cedo quando `causas` está vazio. Não pode mais: **um gatilho dispara num turno em que o score não se moveu** — o lead pede visita, nenhum dos cinco fatores muda, e o `return None` antecipado engoliria o forçamento. A temperatura é resolvida primeiro; a trilha, depois, sem mudança de comportamento.

**O `qualificado` do teto sai da linha travada, não do `antes` de `turno.py`.** `antes` foi lido por `montar_contexto` numa **outra sessão**, antes do bloco transacional, e um turno concorrente da mesma conversa pode ter commitado no intervalo — o teto seria aplicado sobre qualificação velha. Sai de `esta_qualificado(estado, frozenset(estado.campos_recusados or ()))`, com os mesmos dois insumos que `calcular_score` já recebe três linhas acima: zero consulta a mais, e a mesma razão da D2 da TEC-152.

**O `UPDATE` das três colunas só sai quando algo muda**, para não sujar `lead_qualification` com escrita por turno. Ele está dentro do mesmo lock e do mesmo commit que o estado e a trilha: ou os três fatos existem, ou nenhum.

### D6 — A borda, e o evento no log

`QUENTE` por faixa exige `esta_qualificado`, e a mudança é uma **emenda declarada** à RN-06.2 — ver a seção de emendas.

O motivo é o que a RN-06.5 muda de peso. A TEC-150 declarou a divergência e a empurrou nominalmente para esta card:

| Estado | `esta_qualificado` | Total | Faixa sem o teto |
|---|---|---|---|
| `intencao = VENDER_IMOVEL`, resto completo, `IMEDIATA`, `A_VISTA`, 6 mensagens | **False** | **70** | `QUENTE` |
| `intencao = None`, resto igual | **False** | **70** | `QUENTE` |
| Quatro obrigatórios, `IMEDIATA`, `forma_pagamento` nula, 10 mensagens | **True** | 66 | `MORNO` |

Até a TEC-152, o número não era consumido por nada e declarar bastava. **A RN-06.5 faz o telefone do corretor tocar**, e a segunda linha é o caso indefensável: um lead cuja intenção o sistema nunca determinou pinga o corretor como quente, e fica acima de um lead qualificado. O teto fecha isso.

**O teto só morde em ≥ 70.** Um lead não-qualificado com total 45 já era `MORNO`; o único efeito é impedir a passagem para `QUENTE`. E **o gatilho forçado ignora o teto** — a RN-06.3 diz "independentemente do score", e quem pede visita está pronto para agir mesmo sem os quatro campos. Um `VENDER_IMOVEL` que pede para falar com corretor chega `QUENTE`, o que é exatamente o que a RN-03.4 já quer para ele.

O evento sai **depois do commit**, no molde exato de `lead.qualificado`:

```python
if resultado is not None and resultado.anterior is not Temperatura.QUENTE \
   and resultado.temperatura is Temperatura.QUENTE:
    log.info("lead.esquentou", channel=..., message_id=..., motivos=..., total=...)
```

**Depois do commit, e não dentro.** Logar uma transição que o rollback desfez é mentir para quem lê o log — a mesma razão pela qual `lead.qualificado` está lá.

**`anterior is None` com `QUENTE` emite.** Um lead cujo primeiro recálculo já cai em `QUENTE` de fato esquentou; tratar `NULL` como "já era quente" perderia a única travessia que ele tem.

**O texto do lead não entra no log.** `motivos` é vocabulário nosso, não fala dele. A regra de PII que o `moderacao.entrada_bloqueada` respeita — *"o texto julgado não entra no log — é fala do lead, coberta pela regra de PII"* — vale igual aqui.

**Os 60 segundos da RN-06.5 são triviais e é isso que a lacuna 2 diz.** O evento é síncrono no turno, então a latência é a do turno. O critério de aceite *"uma notificação ao corretor é disparada em até 60 segundos"* é verificável apenas como "o evento foi emitido dentro do turno", porque não há entrega para cronometrar.

## Fluxo

1. `executar_turno` decifra `corpo` e chama `gatilhos_de(corpo)` ao lado do `pediu_optout(corpo)` que já está ali — mesmo insumo, mesmo ponto do fluxo.
2. Entrada bloqueada pela moderação retorna antes do bloco transacional, como hoje. **Fala bloqueada não força `QUENTE`, sem guarda nenhuma.**
3. Dentro do bloco transacional, depois de `gravar_estado`, `registrar_recalculo(..., gatilhos=...)`:
   - `SELECT ... FOR UPDATE` na linha de `lead_qualification` (como hoje). Sem linha: devolve `None`, e não há temperatura a resolver.
   - `calcular_score` sobre a linha travada (como hoje).
   - `forcada = temperatura_forcada_em IS NOT NULL or bool(gatilhos)`; `qualificado = esta_qualificado(estado, recusados da mesma linha)`.
   - `temperatura_de(novo, qualificado=..., forcada=...)`, comparada com a coluna `temperatura`.
   - `UPDATE` das três colunas quando algo mudou, com `COALESCE` no carimbo e união nos motivos.
   - A trilha de auditoria, exatamente como hoje.
4. `session.commit()`.
5. Depois do commit, `lead.esquentou` na borda.

## Testes

**Basenames distintos entre `unit` e `integration`, deliberadamente:** `tests/unit/test_temperatura.py`, `tests/unit/test_gatilhos_de_temperatura.py`, `tests/integration/test_temperatura_no_turno.py`. Colisão de basename aborta a coleta da suíte inteira, não aparece nos arquivos isolados, e já custou duas cards neste repo (`a3d1840`, `424ed72`).

**Os quatro cenários da card, diretos.** A tabela `85/70/69/40/39` vira parametrização de `temperatura_de`; o pedido de visita com score 35; o forçamento sobrevivendo a um recálculo que devolve 35; a borda emitindo o evento.

**Três que a card não pede e o desenho exige:**

- **O teto `MORNO`** num lead não-qualificado com total 70 — a linha 2 da tabela da D6, montada com `intencao = None`.
- **`"voces tem plantao de visita no fim de semana?"` não dispara**, e os dois pedidos reais do corpus disparam. É o teste que impede alguém de "melhorar" o recall do detector sem ver o custo.
- **A união de motivos entre turnos**, com o carimbo permanecendo o do primeiro forçamento.

**Um de guarda, contra a regressão que a D5 inverte:** um turno **sem campo nenhum e sem mudança de score** em que um gatilho dispara tem de forçar `QUENTE`. É o caminho que o `return None` antecipado de hoje engoliria, e o único teste que morre se alguém restaurar a ordem original.

## Emendas ao SRS

**RN-06.2** ganha `Emenda E-01 (TEC-151, 03/09/2026)` como item aninhado, sem tocar no texto de 22/08, mais uma linha na tabela do topo. A numeração é **por regra**, não global — a RN-06.2 nunca foi emendada, e há três `E-01` na tabela hoje.

O teor: `QUENTE` por faixa passa a exigir `esta_qualificado`, com teto `MORNO` sem ela. Gatilho forçado (RN-06.3) ignora o teto. O motivo é a RN-06.5 — sem consumidor, a divergência que a TEC-150 declarou era um problema de ordenação de fila; com notificação, um lead sem intenção determinada pinga o corretor como quente.

## Lacunas declaradas

1. **Nada limpa o forçamento.** A RN-06.3 diz "até intervenção humana" e não existe intervenção humana: a TEC-192 é a dona da tela e não existe. **Hoje o forçamento é permanente de fato**, e é essa a razão de a faixa de detecção da D2 ser estrita em vez de generosa. Quem construir a TEC-192 tem de zerar as três colunas juntas — `temperatura_forcada_em`, `temperatura_forcada_motivos` e recalcular `temperatura` —, porque **zerar só o carimbo satisfaz os dois `CHECK` da D3 e deixa a temperatura mentindo**: com `temperatura_forcada_em` nulo, o `CHECK` do `cardinality` não exige mais nada, os motivos velhos ficam na coluna sem nada que os explique, e `temperatura` continua `QUENTE` até o próximo recálculo passar por ali.
2. **A notificação não é entregue, só logada.** O critério de aceite dos 60 segundos é verificável apenas como "o evento foi emitido no turno". E7 não existe, e o conteúdo da mensagem está fora de escopo pela própria card.
3. **`temperatura` é denormalizada, e nenhum `CHECK` a protege.** Ao contrário do `total_novo` da `0012`, que a soma dos cinco fatores prende, esta coluna guarda uma conclusão que ninguém pode reconferir contra o banco. Se os pesos virarem configuração (RF-19), ela passa a guardar uma conclusão calculada com os pesos de ontem, e a única correção é recalcular todas as linhas.
4. **`QUENTE` é conjunção de quase-máximos, não faixa** — `{70, 72, 75}` até a TEC-158. Herdado da TEC-150 e da decisão de 02/09 de não recalibrar. A cadência de reengajamento da TEC-183 (RN-13.1 dá `QUENTE` 4 tentativas, `MORNO` 3, `FRIO` 2) roda sistematicamente mais lenta e mais curta do que o SRS desenhou por causa disso, **e não parecerá bug**: cada card está correta em relação à própria regra. O teto `MORNO` da D6 aperta isso mais um pouco.
5. **Um lead pode esquentar, esfriar e reesquentar, reemitindo o evento.** O total não é monótono desde a TEC-148 (recusa derruba completude), e `esta_qualificado` volta atrás quando o lead responde o que recusou — então a borda por faixa é atravessável nos dois sentidos, para o **mesmo** lead. O forçado não volta; o derivado volta. É o mesmo defeito que `lead.qualificado` já tem declarado na TEC-148, pela mesma causa, e a correção é a mesma que aquela card deferiu: estado persistido de "já emiti uma vez". Fica declarado para quem ler a contagem de notificações saber que ida-e-volta conta duas vezes.
6. **`MOTIVO_CORRETOR` e a RN-04.6 detectam quase o mesmo sinal, em dois lugares.** A RN-04.6 — *"pedido explícito de falar com humano interrompe o fluxo imediatamente e cria handoff prioritário, sem tentativa de retenção"* — não tem implementação e não tem card conhecida. Quando ela existir, as duas detecções têm de ser a mesma função, ou vão divergir em silêncio, que é o defeito que a TEC-146 gastou uma card consertando. Unificar agora exigiria adivinhar a assinatura daquela card.
7. **O detector não vê o histórico.** `gatilhos_de` recebe o texto de um turno só. Um lead que diz *"e a visita?"* referindo-se a um pedido de dois turnos atrás não dispara, e o contexto que resolveria isso está no prompt, não aqui. É consequência direta de a D2 escolher o detector determinístico em vez do campo no schema.
8. **Um pedido explícito de visita é descartado em silêncio — sem forçamento, sem evento — quando o lead não tem linha nenhuma em `lead_qualification` e o turno não cria uma.** Isso acontece quando o classificador rotula o turno `FORA_DE_ESCOPO` ou `INDEFINIDA` e nenhum campo é extraído: o caminho "Deliberadamente NAO cria linha" de `gravar_estado` (`context/repositorio.py`) não deixa linha, e `registrar_recalculo` devolve `None` antes de qualquer temperatura ser resolvida. Um lead que já tenha linha de um turno anterior **não** é afetado. O cenário-título da card funciona, porque uma classificação `COMPRA` grava `intencao` e cria a linha. Consertar isso significa decidir criar uma linha de qualificação para um lead que não disse nada qualificável, o que é decisão de outra card.
9. **`gatilhos_de` casa substring, e isso é um risco de precisão que o módulo não declara.** Uma frase negada como *"não quero falar com atendente"* normaliza para um texto que contém `"falar com atendente"` e ainda dispara o gatilho `CORRETOR`, forçando `QUENTE` permanentemente. O módulo declara a perda de *recall* que aceitou — quem foge dos termos exatos não dispara —, mas nunca este falso positivo. Aqui o sentido caro é o inverso do declarado: nada no produto desfaz um forçamento (lacuna 1), então um falso positivo custa mais que um falso negativo.

## Fora de escopo

- A entrega da notificação e seu conteúdo — E7 / RF-16, épico a criar.
- A intervenção humana que desfaz o forçamento — dashboard da [TEC-192](https://eduardodurieuxlopes.atlassian.net/browse/TEC-192).
- A redução de 15 pontos por não comparecimento — RN-12.4, [TEC-172](https://eduardodurieuxlopes.atlassian.net/browse/TEC-172).
- A cadência de reengajamento por temperatura — RN-13.1, [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183).
- A busca de imóveis que acende a aderência ao catálogo — [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158).
- Recalibrar os cortes da RN-06.2 para o teto real de 75 — decidido em 02/09/2026, e a decisão foi aceitar a consequência.
- A unificação com a RN-04.6 — ver a lacuna 6.

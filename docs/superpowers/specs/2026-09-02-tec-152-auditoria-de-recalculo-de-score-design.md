# TEC-152 — Registrar auditoria de cada recálculo de score

**Status:** desenhado em 2026-09-02. Não implementado.

**Card:** [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152) — Should (MoSCoW). Origem: RF-06, RN-06.4, RNF-18 (SRS v1.0, em `docs/srs/`). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144).

**Destravada pela [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150)**, que está mergeada. Adiante: a [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151) (temperatura), o dashboard da [TEC-192](https://eduardodurieuxlopes.atlassian.net/browse/TEC-192) e a [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158) (busca de imóveis, que acende o quinto fator).

## Objetivo

A história é da Anelise: *"quero saber por que um lead subiu ou caiu de score, para confiar na priorização em vez de tratá-la como caixa-preta"*. O contorno, sem esta card, é reconstruir o cálculo à mão a partir do estado atual — o que não funciona, porque o estado atual não guarda o que ele era antes.

**O que esta card entrega:** a trilha de recálculos, e o recálculo em si.

A segunda metade não estava óbvia no título. A TEC-150 entregou `calcular_score` e **nada a chama**: a spec dela diz que *"onde esse recálculo vive é decisão da TEC-151 e da TEC-152"*, e a TEC-151 ainda não existe. Uma auditoria de recálculos que nunca acontecem não audita nada, então esta card assume o gancho — e, com ele, a decisão que a TEC-150 delegou às duas. Quem chegasse primeiro decidiria; chegou esta.

## O que já existe, e que o desenho reusa

**`calcular_score` e o `Score` detalhado.** Os cinco fatores já vêm separados, e a docstring do `Score` diz por quê: *"a TEC-152 grava 'score anterior, novo, fatores e timestamp', e uma auditoria que precisasse recalcular os fatores para auditá-los não auditaria nada"*. A TEC-150 já construiu para esta card.

**O molde de tabela append-only.** `optout_events` (TEC-182, migration `0010`) é uma linha por evento, com `autor`/`motivo` nuláveis, `server_default=func.now()` porque a ordem *é* o estado, e sem FK para `messages` porque a evidência de conformidade sobrevive à limpeza das mensagens. A auditoria de score cai nesse molde quase sem ajuste.

**O ponto de gancho, já preparado.** `gravar_estado` devolve a linha do `RETURNING` desde a TEC-147, e o `populate_existing` foi posto lá com esta card em vista — o comentário em `repositorio.py` diz: *"a TEC-150 quer ler e gravar na mesma sessão para recalcular o score"*. O turno já tem o bloco transacional e já compara antes/depois para o evento `lead.qualificado`.

**O contrato de `mensagens_do_lead`, escrito e sem implementação.** A docstring de `calcular_score` fixa a definição palavra por palavra — `direction == INBOUND` e `bloqueada_em IS NULL` — e diz que *"quem for escrever a consulta na TEC-151 e na TEC-152 tem de escrever a mesma"*. Esta card escreve a única.

## Decisões

### D1 — A tabela `lead_score_audit`, append-only

Migration `0012`.

| coluna | tipo | nota |
|---|---|---|
| `id` | `UUID` PK | |
| `channel` | `String(32)` | o par de `lead_qualification` |
| `conversation_key` | `String(64)` | |
| `total_anterior` | `Integer` **nulável** | `NULL` = primeiro registro deste lead. Ver D6 |
| `total_novo` | `Integer` | |
| `completude`, `urgencia`, `catalogo`, `engajamento`, `capacidade` | `Integer` | os cinco fatores do score **novo** |
| `causas` | `ARRAY(String(32))` | nunca `NULL`, nunca vazio. Ver D4 |
| `autor` | `String(120)` nulável | só na edição manual (TEC-192); hoje sempre nulo |
| `created_at` | `timestamptz` | `server_default=clock_timestamp()`. Ver abaixo |

Índice `ix_lead_score_audit_lead (channel, conversation_key, created_at DESC)`, mesmo formato do `ix_optout_events_lead` e do `ix_messages_timeline`: a consulta quente é *"qual o último registro deste lead?"*, uma vez por turno, e o `DESC` no índice evita ordenar em memória para um `LIMIT 1`.

`server_default` e não valor vindo do cliente, pela razão que a `0010` já documentou e que vale igual aqui: a **ordem** dos `created_at` é o que torna a trilha legível, e com o relógio de cada máquina escrevendo a coluna um skew inverteria dois registros do mesmo lead.

**E `clock_timestamp()` e não `now()`.** `now()` é `transaction_timestamp()`, congelado no *primeiro* statement da transação — num turno, o `ler_intencao`, vários statements antes de o passo de auditoria tomar o lock. Dois turnos concorrentes da mesma conversa sairiam então carimbados pela ordem em que **começaram**, e não pela ordem em que gravaram; o turno que começa antes e ganha o lock depois grava por último com o carimbo mais antigo, e a trilha fica na ordem inversa da ordem de escrita. A consequência não é cosmética: o turno seguinte lê como "último registro" uma linha que não é a atual e encadeia `total_anterior` a partir dela. Como o `INSERT` acontece com o lock de `lead_qualification` na mão (D7), `clock_timestamp()` produz uma ordem total igual à ordem do lock.

**Só os fatores do score novo são gravados, não os do anterior.** Com "grava só quando muda" (D3), o registro anterior da mesma conversa *é* o score anterior — guardar os dois criaria duas fontes para o mesmo fato, que é o defeito que a TEC-146 gastou uma card inteira consertando. `total_anterior` fica mesmo assim: é o que a card nomeia, e poupa a segunda leitura no caso comum de só se querer o delta.

**`CHECK (total_novo = completude + urgencia + catalogo + engajamento + capacidade)`.** O total é denormalizado de propósito — é por ele que se ordena e se filtra —, e a restrição é o que impede a denormalização de mentir. Sem ela, um fator esquecido na soma produz uma trilha que parece consistente e não é.

**O teto de 95 não vira `CHECK`.** Ele se move quando a TEC-158 acender o catálogo e quando os pesos virarem configuração (RF-19), e engessá-lo no banco custaria uma migration para mudar uma constante de módulo. A D3 da TEC-150 já declarou que a escala não chega a 100; o banco não precisa ter opinião sobre isso.

**Sem FK para `messages` nem para `lead_qualification`.** Pela razão da `0010`: a retenção da trilha (12 meses, RNF-18) não pode ser encurtada por cascata da limpeza de outra tabela.

### D2 — O gancho vive no turno, na transação do estado

Dentro do `async with session_factory()` que já existe em `turno.py`, depois de `gravar_estado` e antes do `commit`.

**Mesma transação que o estado, pela mesma razão que a intenção e a extração estão nela:** ou os dois fatos existem, ou nenhum. Uma trilha que registrasse um score calculado sobre um estado que o rollback desfez seria pior que trilha nenhuma — ela é lida justamente por quem já desconfia do número.

**O estado vem do próprio `SELECT ... FOR UPDATE` da D7, e não de `depois_do_estado` nem de `contexto.estado`.** Reusar qualquer um dos dois pareceria mais barato — os dois já estão em mãos — e seria errado no caminho sem campos: `contexto.estado` foi lido por `montar_contexto` numa **outra sessão**, antes deste bloco, e um turno concorrente da mesma conversa pode ter commitado uma alteração no intervalo. O passo calcularia o score sobre estado velho, e a trilha registraria um número que nunca foi verdade. Como a D7 já emite o statement de lock, deixá-lo devolver a linha custa zero a mais e apaga a questão: há uma leitura, ela é a que segura o lock, e ela é a que alimenta o cálculo.

Sem linha, não há sujeito a auditar e o passo não faz nada. Isto é deliberado: `calcular_score(None)` devolve zerado, e o `score.py` já distingue *"a ausência de sujeito"* de uma nota igual a zero — auditar um lead que nunca informou nada seria registrar a primeira como se fosse a segunda.

**O recálculo roda em todo turno com estado, e não só nos turnos que gravaram campo.** O engajamento depende da contagem de mensagens, que sobe em todo turno: as travessias de 0 para 10 pontos (primeira mensagem) e de 10 para 15 (sexta) podem cair num turno sem campo nenhum. Amarrar o recálculo ao `gravar_estado` deixaria essas subidas fora da trilha — exatamente a caixa-preta que a card quer abrir.

### D3 — Grava quando o `Score` muda, e "muda" são os cinco fatores

A RN-06.4 diz *"todo recálculo grava um registro"*. Este desenho grava quando o resultado difere do último registrado, e a diferença é uma **emenda declarada**, não um descuido — ver a seção de emendas ao SRS.

O motivo: o gancho roda a cada turno, e a esmagadora maioria dos recálculos não move nada. Uma linha por mensagem de entrada, quase toda duplicata da anterior, enterra as transições que a Anelise quer ver no meio do que ela não quer. A trilha existe para responder *"por que subiu ou caiu"*; linha que não sobe nem cai não responde.

**"Mudou" compara os cinco fatores, e não o total.** O total pode ficar idêntico com a composição mudando, e o caso é alcançável em produção, não hipotético: um lead que só tinha informado `urgencia = ATE_3_MESES` (completude 5, urgência 15) diz *"quero comprar apto até 500 mil na Vila Mariana, mas sem pressa"*. A extração carrega intenção, faixa de preço e região de uma vez — completude sobe 15 — e a urgência cai para `SEM_PRESSA`, −15. **Total idêntico, e o lead passou de quase anônimo a quase completo.** É justamente o caso em que a trilha explica algo que ninguém deduz do estado atual, e o único em que comparar totais devolveria "nada aconteceu".

**Consequência: o último registro de um lead é o score atual dele.** É consequência, não contrato — ver as lacunas.

### D4 — As causas são derivadas por função pura, e moram numa lista

`src/mobia/domain/context/auditoria.py`, no molde de `qualificacao.py` e `score.py`: sem I/O, sem banco, sem chamada ao modelo.

```python
def causas_do_recalculo(anterior: Score | None, novo: Score) -> tuple[str, ...]: ...
```

O vocabulário, como constantes de módulo:

`PRIMEIRO_CALCULO` · `CAMPOS_OBRIGATORIOS` · `URGENCIA` · `FORMA_DE_PAGAMENTO` · `ENGAJAMENTO` · `CATALOGO` · `EDICAO_MANUAL` · `NAO_COMPARECIMENTO`

**Lista e não coluna única**, porque um único recálculo tem mais de uma causa com frequência: a mensagem que informa a forma de pagamento também incrementa a contagem que move o engajamento. Uma coluna única exigiria uma regra de precedência, e precedência aqui descarta informação real — a trilha diria "forma de pagamento" e esconderia que o engajamento subiu no mesmo passo. `ARRAY(String)` já tem precedente na casa (`perguntados_sem_resposta`).

**Os nomes são do domínio, não da direção.** Subiu ou caiu se lê nos números; um vocabulário com `_SUBIU`/`_CAIU` dobraria de tamanho para dizer o que as colunas já dizem.

**Tupla vazia é o sinal de "não grave".** A decisão da D3 não é um `if` no chamador: é a ausência de causa. Assim a regra de quando gravar mora no mesmo lugar que a regra do que gravar, e não há como as duas divergirem.

**Três valores entram no vocabulário sem produtor.** `CATALOGO` fica inerte enquanto a TEC-158 não existir (o fator contribui zero e nunca se move). `EDICAO_MANUAL` e `NAO_COMPARECIMENTO` não são deriváveis de diff nenhum — são fatos sobre a origem do gatilho, e o chamador futuro (TEC-192, TEC-172) os informa em vez de derivá-los. Entram agora porque acrescentá-los depois não custaria migration, mas custaria uma segunda lista.

**A tradução para a linguagem da card não é um-para-um, e isto é o que ela é:**

| motivo na card | o que a trilha registra |
|---|---|
| "novo campo preenchido" (obrigatório) | `CAMPOS_OBRIGATORIOS` |
| "novo campo preenchido" (o do cenário 1) | `FORMA_DE_PAGAMENTO` |
| "mudança de intenção" | ver abaixo — nem sempre existe |
| "edição manual do corretor" | `EDICAO_MANUAL`, sem produtor hoje |
| "não comparecimento" | `NAO_COMPARECIMENTO`, sem produtor hoje |

O cenário 1 da card chama informar forma de pagamento de *"preenchimento de novo campo"*, mas `forma_pagamento` **não é um dos quatro obrigatórios da RN-05.3** (`intencao`, `faixa_preco`, `regiao`, `urgencia`). Ele move `capacidade`, não `completude`. "Novo campo" na card significa qualquer campo extraído.

E **"mudança de intenção" não é derivável do score**: trocar `COMPRA` por `ALUGUEL` não move fator nenhum — as duas estão em `INTENCOES_QUALIFICAVEIS` —, então não há registro; trocar `COMPRA` por `VENDER_IMOVEL` tira a intenção da lista, derruba `completude` em 5, e aparece como `CAMPOS_OBRIGATORIOS`. Lacuna declarada.

### D5 — Imutabilidade por trigger; `DELETE` continua livre

A migration cria uma função e uma trigger `BEFORE UPDATE` em `lead_score_audit` que levanta exceção.

**É a única opção em que o cenário 3 da card vira teste.** *"Quando se tenta alterá-lo, então a operação é recusada"* precisa de algo que recuse; com convenção e caminho append-only — que é o que o `optout_events` faz — a recusa vira comentário, e o teste correspondente passaria com o código certo ou errado. Este repo já gastou rodadas de revisão exatamente nisso.

**`DELETE` não é bloqueado.** Imutável significa *não se altera o que foi registrado*; expurgo por política de retenção é ato deliberado, não alteração. Bloquear os dois obrigaria a retenção a passar por um caminho privilegiado que não existe neste repo, e a RNF-18 pede retenção de 12 meses — ou seja, pede que apagar seja possível.

### D6 — `total_anterior` é `NULL` no primeiro registro, não `0`

O `score.py` já faz essa distinção e a justifica: *"o zero é a ausência de sujeito, não uma nota sobre ele"*. Um lead cujo primeiro cálculo deu 51 nunca teve score 0 — dizer que teve inventaria uma subida de 51 pontos que não aconteceu, no primeiro registro de toda conversa, que é onde a trilha causa a primeira impressão.

`causas` nesse registro é `('PRIMEIRO_CALCULO',)`, e não a lista dos fatores diferentes de zero: não houve movimento a explicar.

### D7 — O lock que fecha a corrida entre turnos concorrentes

**Turnos da mesma conversa não são serializados.** A deduplicação do ARQ é por mensagem (`_job_id = msg:<id>`), não por conversa, e a proteção contra paralelismo é uma invariante de tempo — `job_timeout = 240` estritamente menor que `sweep_inflight_after_seconds = 300` —, não um lock. O comentário em `workers/main.py` diz que, invertida, *"o sweeper reenfileira um turno que ainda está em voo e a mesma conversa roda duas vezes em paralelo"*. Duas mensagens do mesmo lead chegando juntas já produzem dois jobs concorrentes.

Sem tratamento, dois recálculos concorrentes leem o mesmo último registro, ambos veem mudança e ambos gravam — dois registros com o mesmo `total_anterior`, e a cadeia deixa de reconstruir a evolução que o cenário 4 pede.

**O passo abre com `SELECT ... FOR UPDATE` na linha de `lead_qualification`, e usa a linha que ele devolve.**

Quanto ao lock: no turno **com** campos ele é redundante — o `ON CONFLICT DO UPDATE` de `gravar_estado` já tomou o lock exclusivo daquela linha, e o turno concorrente já está bloqueado ali. No turno **sem** campos não há upsert, logo não há lock — e é exatamente o caminho em que a única mudança possível vem da contagem de mensagens, que é a que dois turnos concorrentes leriam igual.

Quanto à leitura: ela não é redundante em caminho nenhum, e é o que a D2 explica. `contexto.estado` vem de outra sessão e de antes deste bloco; sob concorrência ele pode estar velho, e o lock sem a releitura protegeria a escrita enquanto o cálculo usaria dado obsoleto — a pior das combinações, porque parece correta.

Tomar os dois sempre custa um statement e faz o raciocínio parar de depender de qual caminho o turno tomou. A alternativa — só no caminho sem campos — economiza um round trip e paga com uma condição que quem ler o código daqui a seis meses tem de reconstruir para acreditar.

**Este `SELECT` precisa de `.execution_options(populate_existing=True)`**, pela mesma razão que `gravar_estado` precisou e que o comentário dele já documenta: no turno com campos a sessão **acabou de carregar** essa linha pelo `RETURNING` do upsert, e sem a opção o identity map do SQLAlchemy devolve a instância que a sessão já tem em vez da linha que o banco acabou de mandar. O sintoma seria o mais caro possível: a releitura que existe justamente para não usar estado velho devolveria estado velho, com o lock tomado e tudo parecendo certo. A TEC-147 escapou desse mesmo buraco por acidente — `turno.py` lia numa sessão e gravava noutra —, e aqui o acidente não protege, porque as duas operações são de propósito a mesma sessão.

## Fluxo

1. O turno chega ao bloco transacional que já existe, grava intenção e estado.
2. `SELECT ... FOR UPDATE` na linha de `lead_qualification` (D7). A linha que ele devolve **é** o estado usado daqui em diante. Sem linha, o passo termina aqui.
3. `contar_mensagens_do_lead(session, channel, conversation_key)` — `COUNT` sobre `messages` com `direction == INBOUND` e `bloqueada_em IS NULL`. **Inclui a mensagem do turno corrente**, que a ingestão persistiu antes de o job rodar.
4. `calcular_score(estado, mensagens_do_lead=..., imoveis_compativeis=0)`.
5. Lê o último registro do lead (`ORDER BY created_at DESC LIMIT 1`) e reconstrói o `Score` anterior a partir das cinco colunas de fator. Sem registro, o anterior é `None`.
6. `causas_do_recalculo(anterior, novo)`. Vazio: não grava.
7. `INSERT` do registro. O `commit` que já existia fecha os dois fatos juntos.

**`contar_mensagens_do_lead` tem uma implementação, e existe para que a TEC-151 não escreva a segunda.** A docstring de `calcular_score` já nomeia esse risco; esta card o fecha com uma função em vez de com um parágrafo.

## Testes

**Unitários — `tests/unit/test_auditoria_score.py`**, sem banco:

- `causas_do_recalculo` fator a fator: cada um dos cinco movendo sozinho produz a sua causa e só ela;
- o caso multi-causa: forma de pagamento e engajamento no mesmo passo produzem as duas;
- `PRIMEIRO_CALCULO` quando o anterior é `None`, e **só** ela — não a lista dos fatores não-zerados;
- **tupla vazia quando nada moveu**, que é o sinal de não gravar;
- total idêntico com composição diferente — completude +15 e urgência −15, o caso da D3 — produz duas causas, e não vazio. É o teste que a alternativa "só quando o total muda" faria passar por engano;
- o vocabulário é amarrado aos cinco fatores do `Score`, como a TEC-150 amarrou `_PONTOS_POR_URGENCIA` ao enum `Urgencia`: um sexto fator acrescentado ao `Score` sem causa correspondente tem de deixar um teste vermelho, e não passar em silêncio.

**Integração — `tests/integration/test_auditoria_score.py`:**

- o turno grava um registro com anterior, novo, os cinco fatores e as causas;
- o turno **não** grava quando o score não muda;
- `UPDATE` na linha é recusado pela trigger (cenário 3 da card, de verdade);
- quatro recálculos aparecem em ordem cronológica com as respectivas causas (cenário 4 da card);
- `contar_mensagens_do_lead` ignora `OUTBOUND` e ignora `bloqueada_em IS NOT NULL` — os dois casos que a docstring de `calcular_score` nomeia;
- o `CHECK` recusa um `total_novo` que não soma;
- `upgrade` e `downgrade` da `0012`, no molde que `test_migrations.py` já tem.

TDD, e cada teste verificado por mutação: trocar uma comparação de fator por outra tem de deixar vermelho exatamente o teste daquele fator. Nas cards anteriores, toda rodada de revisão perdida foi teste que passava com o código certo ou errado.

### O cenário 1 da card não é testável como está escrito

A card diz *"um lead com score 48"* que *"informa que paga à vista e o score sobe para 63"* — um delta de 15. Na escala que a TEC-150 implementou, informar à vista move `capacidade` de 6 (coluna nula ou `INDEFINIDA`) para 15: **delta de 9**.

Pior que o delta: a enumeração exaustiva dos totais alcançáveis com `imoveis_compativeis = 0`, que é o estado até a TEC-158, mostra que

- **63 é inalcançável**, e
- **48 só é alcançável se `capacidade` já for 15** — ou seja, se o lead **já** paga à vista, e portanto não pode informá-lo.

Os números da card são ilustrativos, escritos em 22/08 contra uma escala que só passou a existir com a TEC-150 em 02/09. O que a card pede — anterior, novo, os cinco fatores, o motivo e o timestamp — segue inteiro de pé; o que não se sustenta são os dois números.

**O teste usa o equivalente alcançável:** quatro obrigatórios (20), `ATE_3_MESES` (15), 1–5 mensagens (10), sem forma de pagamento (6) = **51**. O lead informa à vista: `capacidade` vai a 15 = **60**. `causas = ('FORMA_DE_PAGAMENTO',)`, ou `('FORMA_DE_PAGAMENTO', 'ENGAJAMENTO')` se a mensagem cruzar a sexta.

A substituição fica declarada aqui pelo mesmo motivo que a D3 da TEC-150 declarou que a escala não chega a 100: quem for reconciliar a card com o código precisa achar a divergência escrita, não descobri-la.

## Emenda ao SRS

Entra em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` como item aninhado sob a **RN-06.4**, sem reescrever o texto de 22/08:

> **Emenda E-01 (TEC-152, 02/09/2026)** — o registro é gravado quando o resultado do recálculo difere do último registrado, e não a cada recálculo. A comparação é sobre os cinco fatores, não sobre o total. O gancho roda a cada turno com estado, e a maioria dos recálculos não move nada: uma linha por mensagem de entrada enterraria as transições no meio das duplicatas, e a regra existe para responder *"por que subiu ou caiu"*.

## Lacunas declaradas

**Dois dos quatro motivos da card são inalcançáveis.** "Edição manual do corretor" precisa do dashboard (E8, TEC-192) e "não comparecimento" precisa de agendamento (RN-12.4, TEC-172). Nenhum dos dois existe, e o cenário *"edição manual registra o autor"* não tem como ser exercido ponta a ponta. A coluna `autor` existe e fica nula — como `optout_events.autor` fica nula no opt-out, pela mesma razão: o ato é do lead, não de um humano nosso.

**"Só quando muda" é emenda à letra da RN-06.4.** Ver a seção de emenda. A consequência operável é que a trilha não prova que um recálculo *aconteceu*, só que o resultado *mudou*. Quem precisar da primeira coisa — uma auditoria de que o sistema recalculou quando devia — não a encontra aqui.

**Mudança de intenção que não move o score não gera registro.** Ver D4. `COMPRA` para `ALUGUEL` é invisível na trilha.

**A retenção de 12 meses não é imposta.** A RNF-18 pede 12 meses e não há job de expurgo neste repo — o `optout_events` também guarda evidência de conformidade sem um, e a `0010` discute retenção sem construir nada. Construir o primeiro agendador de expurgo do projeto dentro de uma card de auditoria seria decidir política de retenção por todas as outras tabelas de passagem. A trilha cresce sem limite até alguém escrever essa card.

**O último registro de um lead é o score atual dele.** Consequência de D3, não contrato. Se a TEC-151 ler daqui em vez de recalcular, a tabela de auditoria vira carga viva do produto — e uma tabela que a retenção pode expurgar deixa de ser lugar seguro para o estado corrente. A decisão é da TEC-151, e esta card não a toma.

**O score continua monotonicamente não-decrescente pelo engajamento.** Lacuna herdada da TEC-150, que a declarou e explicou por que corrigi-la não é ajustar o chamador. A consequência para esta card é sobre o que a trilha vai mostrar: leads subindo por terem falado muito, não por estarem mais perto de comprar, e nenhum lead descendo por ter sumido.

**O `SELECT ... FOR UPDATE` serializa turnos concorrentes da mesma conversa, e isso é novo.** Antes desta card, dois turnos concorrentes só colidiam no upsert de `gravar_estado`, e só quando ambos traziam campo. Agora todo turno com estado toma o lock. O custo é latência num caminho que já era raro; fica declarado porque é uma mudança de comportamento que não aparece em nenhum teste de unidade.

**Os pesos continuam não sendo configuráveis.** Lacuna da TEC-150 (RF-19, CA-19.1). Importa aqui porque a trilha guarda contribuições calculadas com os pesos vigentes no momento, e não os pesos em si: se eles mudarem, os registros antigos deixam de ser reproduzíveis a partir do código atual. Registrar a versão dos pesos em cada linha seria a correção, e ela pertence à card que tornar os pesos configuráveis.

## Fora de escopo

- A derivação de temperatura e os gatilhos que forçam `QUENTE` — RN-06.2 e RN-06.3, [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151).
- A exibição do histórico de score no dashboard — E8, [TEC-192](https://eduardodurieuxlopes.atlassian.net/browse/TEC-192). A card diz explicitamente.
- A trilha de auditoria geral de acesso a dado pessoal — E9. A card diz explicitamente.
- O job de expurgo dos 12 meses — ver lacunas.
- A redução de 15 pontos por não comparecimento — RN-12.4, [TEC-172](https://eduardodurieuxlopes.atlassian.net/browse/TEC-172).
- A busca de imóveis que acende o fator de catálogo — [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158).

# TEC-150 — Calcular o lead score determinístico de 0 a 100

**Status:** desenhado em 2026-09-02. Não implementado.

**Card:** [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150) — Must (MoSCoW). Origem: RF-06, RN-06.1 (SRS v1.0, em `docs/srs/`). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144).

**Destravada pela [TEC-147](https://eduardodurieuxlopes.atlassian.net/browse/TEC-147)**, que está Feito. Bloqueia a [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151) (temperatura) e a [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152) (auditoria de recálculo); adiante, a [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) e o dashboard da [TEC-192](https://eduardodurieuxlopes.atlassian.net/browse/TEC-192).

Resta um bloqueio no Jira, a [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158) (busca de imóveis), que o texto da própria card resolve: *"até lá o fator contribui com zero"*.

## Objetivo

O produto promete ao corretor *"uma fila ordenada por probabilidade de fechar"*. Sem score, a fila volta a ser ordem de chegada — e a TEC-147 entregou a noção de qualificado, que diz **se** o lead passa, não **quanto** ele vale.

**O que esta card entrega:** o cálculo, determinístico e em código, com a contribuição de cada fator exposta. Nada mais.

## O que já existe, e que o desenho reusa

**Os campos dos quatro fatores ativos.** `LeadQualification` tem `urgencia`, `forma_pagamento` e os quatro obrigatórios da RN-05.3. `messages` tem `role`, `direction` e `created_at`, que é tudo que a contagem de engajamento precisa.

**A urgência mapeia limpo, e é o único fator que mapeia.** `Urgencia` é `IMEDIATA` / `ATE_3_MESES` / `ATE_6_MESES` / `SEM_PRESSA`, e a docstring do enum diz *"Faixas, nao datas. O lead diz 'em janeiro'; o que importa e a pressa."* As quatro faixas da RN-06.1 (≤30 dias, 31–90, 91–180, sem prazo) casam uma a uma.

**O padrão de parâmetro em vez de consulta.** A TEC-147 pôs `recusados` na assinatura de `esta_qualificado` em vez de criar coluna ou consultar. Este desenho repete a forma pelos mesmos motivos.

## Decisões

### D1 — Função pura; o que ela não pode ler entra por parâmetro

`src/mobia/domain/context/score.py`:

```python
def calcular_score(
    estado: LeadQualification | None,
    *,
    mensagens_do_lead: int = 0,
    imoveis_compativeis: int = 0,
) -> Score
```

**As duas contagens são keyword-only.** São dois `int` adjacentes com o mesmo default: inverter a ordem num chamador não levanta, não é erro de tipo, não é visível ao mypy, e devolve score errado em silêncio. A TEC-151 é o primeiro chamador e está sendo escrita agora — fechar isso antes dela custa um token.

Quatro dos cinco fatores leem `LeadQualification`. Engajamento precisa contar mensagens; aderência precisa consultar o catálogo. Nenhum dos dois é campo do estado, e nenhum dos dois justifica tornar a regra impura: quem chama consulta, a função permanece testável sem banco e sem mock.

`imoveis_compativeis=0` é o comportamento que a card prescreve enquanto a TEC-158 não existe. Quando ela existir, o chamador passa o número real e **nenhuma linha deste módulo muda**.

### D2 — O retorno é o detalhamento, não o total

A card exige que *"cada fator devolve sua contribuição, não só o total"*.

```python
@dataclass(frozen=True)
class Score:
    completude: int
    urgencia: int
    catalogo: int
    engajamento: int
    capacidade: int

    @property
    def total(self) -> int
```

A [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152) consome isto direto: a RN-06.4 manda gravar *"score anterior, novo, fatores e timestamp"*. Devolver só o inteiro obrigaria aquela card a recalcular os fatores para auditar o cálculo — auditoria que recomputa o auditado não audita nada.

### D3 — A completude vale 5 por campo, e o score vai até 95

A RN-06.1 dá ao fator peso **25** e o critério *"5 pontos por campo obrigatório preenchido"*. A RN-05.3 tem **quatro** obrigatórios. 4 × 5 = 20, e as duas afirmações não podem estar certas ao mesmo tempo.

Vale a regra operável. *"5 pontos por campo"* é verificável campo a campo; *"peso 25"* é número de cabeçalho que não fecha com a lista que o próprio SRS dá. A alternativa — 6,25 por campo — inventa um número que o SRS não contém, torna fracionárias as contribuições de um cálculo que a card chama de auditável, e quebraria de novo se um quinto obrigatório aparecesse.

**Consequência declarada: o score não chega a 100.** O teto é 95 com catálogo e **75 sem ele**. A TEC-151 corta `QUENTE` em 70, que continua alcançável — mas sem catálogo o alcançável acima de 70 são **três totais**, e não uma faixa. A enumeração está na seção de lacunas declaradas, e é dela que a TEC-151 precisa antes de calibrar qualquer coisa.

**A completude não redefine quais são os campos obrigatórios — ela importa a definição da TEC-147.** `qualificacao.py` já expõe `CAMPOS_OBRIGATORIOS` e já sabe o que "preenchido" significa em cada um, incluindo a regra não-óbvia de que `faixa_preco` são duas colunas e qualquer extremo conta. Uma segunda lista aqui divergiria da primeira no dia em que a RN-05.3 mudasse, e divergiria em silêncio: os dois módulos continuariam verdes, cada um com a sua verdade.

Não é risco hipotético neste repo. A TEC-146 gastou uma card num bug exatamente assim — `MARCADORES_DE_REPERGUNTA` guardando `"faixa_preco_max"` enquanto `Extracao` produzia `faixa_preco_max_centavos` — e a correção incluiu um teste que amarra as duas listas. Este módulo importa em vez de repetir, e um teste amarra a contagem máxima de completude a `len(CAMPOS_OBRIGATORIOS) * 5`.

### D4 — Os cinco fatores

| Fator | Peso | Regra | Hoje |
|---|---|---|---|
| Completude | 20 | 5 por campo obrigatório da RN-05.3 | ativo |
| Urgência | 25 | `IMEDIATA` 25 · `ATE_3_MESES` 15 · `ATE_6_MESES` 8 · `SEM_PRESSA` 0 | ativo |
| Aderência ao catálogo | 20 | ≥5 imóveis 20 · 1–4 12 · nenhum 0 | **zero** até a TEC-158 |
| Engajamento | 15 | ≥6 mensagens 15 · 1–5 10 · nenhuma 0 | ativo |
| Capacidade financeira | 15 | ver D5 | ativo |

**As faixas de engajamento são arbitradas, e o critério de aceite foi o único guia.** O SRS diz apenas *"por número de mensagens do lead e tempo médio de resposta"* — é o único dos cinco fatores sem faixas. O cenário de aceite pede **≥70** para um lead com os quatro obrigatórios, prazo de 20 dias e pagamento à vista: isso soma 60 sem catálogo, então engajamento precisa render ≥10 para o critério da própria card fechar.

**São três faixas, e a de baixo começa em UMA mensagem.** Falar vale 10; falar muito vale 15.

Uma versão anterior deste desenho tinha quatro faixas (`≥6` 15 · `3–5` 10 · `1–2` 5) justificadas assim: *"um lead que informou quatro campos mandou, por construção, ao menos três mensagens"*. **Essa afirmação é falsa neste repositório, e a correção é a razão de existir da faixa única de baixo.** `Extracao` (`domain/agente/schemas.py`) carrega `faixa_preco`, `regiao`, `urgencia` e `forma_pagamento` num **único turno**, e `intencao` vem do classificador do mesmo turno. O corpus já tem o caso: `borda-injecao-01`, turno 2, em `evals/corpus/borda.yaml` — uma única fala que traz região, faixa de preço e forma de pagamento de uma vez.

A consequência da premissa falsa era concreta: **o cenário de aceite da própria card, escrito como uma única mensagem, somava 65 e reprovava o critério de 70.** Com três faixas, o critério fecha em qualquer contagem ≥1.

A mesma mudança conserta um segundo problema. Com quatro faixas, dois leads de qualificação idêntica ficavam a **10 pontos** de distância só por verbosidade — mais que a distância entre pagar à vista e financiar (3) e mais que um campo obrigatório faltando (5), de modo que o comprador conciso à vista ranqueava *abaixo* do lead falante que apenas mencionou financiamento. Com três faixas o intervalo cai para 5. Ainda é arbitrado; é menos determinante.

Um teste que fixa a contagem de mensagens no valor usado para derivar a faixa não pode detectar esse defeito — foi o que aconteceu, e por isso o teste do cenário sem catálogo agora é parametrizado sobre a contagem, com `mensagens_do_lead=1` incluído.

**Tempo médio de resposta fica fora**, declarado na seção de lacunas.

### D5 — Capacidade financeira: o mapeamento que o SRS não dá

| Valor de `FormaPagamento` | Pontos |
|---|---|
| `A_VISTA` | 15 |
| `FINANCIAMENTO`, `CONSORCIO`, `FGTS` | 12 |
| `INDEFINIDA` ou nulo | 6 |

A RN-06.1 pontua três categorias — *à vista*, *financiamento pré-aprovado*, *a avaliar* — e o enum tem cinco valores.

**Pré-aprovação não existe como dado neste repo.** `FINANCIAMENTO` recebe os 12 do *pré-aprovado*, o que é generoso: um lead que menciona financiamento sem tê-lo aprovado pontua como quem já tem carta. É a única leitura possível com os campos que existem, e está declarada em vez de silenciada.

**`CONSORCIO` e `FGTS` não têm nota no SRS.** Recebem 12 por serem, como o financiamento, caminho de pagamento definido e não "a avaliar". Uma hierarquia mais fina entre os três — consórcio tem liquidez pior que financiamento aprovado — seria regra que o SRS não contém, inventada sem dado para sustentá-la.

### D6 — Os pesos são constantes de módulo, não configuração

A card diz *"os pesos vêm de configuração e podem mudar sem deploy"*, e a CA-19.1 do SRS é mais específica: *"os próximos recálculos usam o novo peso **sem reiniciar a aplicação**"*.

Isso não é entregável nesta card. `Settings` é `pydantic-settings` lendo `.env` sob `lru_cache`: mudar um valor exige reiniciar o processo. Atender a CA-19.1 exige persistir os pesos, decidir quem os altera, invalidar cache e definir o que acontece com cálculo em voo — um subsistema, e ele pertence ao épico de configuração (RF-19), não ao de scoring.

Os pesos ficam como constantes de módulo, como as bandas de preço da TEC-146 ficaram, e a configurabilidade vira lacuna declarada com ponteiro para a card que a deve.

## Fluxo

1. O chamador tem o estado (`gravar_estado` o devolve desde a TEC-147) e consulta o que a função não pode ler: a contagem de mensagens do lead.

**`mensagens_do_lead` conta as falas de entrada do lead que a moderação não bloqueou** — as linhas de `messages` com `direction == INBOUND` (equivalentemente `role == LEAD`, que a ingestão grava no mesmo `INSERT`) e `bloqueada_em IS NULL`. A definição está na docstring de `calcular_score`, e existe porque três leituras eram defensáveis e TEC-151 e TEC-152 escreveriam cada uma a sua consulta sem nada as reconciliando — a mesma armadilha de duas fontes para o mesmo fato que a D3 fecha para "campo preenchido", e que a TEC-146 já custou uma card a este projeto.

- **Não é a conversa inteira.** Fala do agente não é engajamento do lead, e contar as duas direções quase dobra o número e empurra `MORNO` para `QUENTE` de graça.
- **Fala bloqueada não conta.** Não é critério novo: `literais_apos` (`context/janela.py`) filtra `bloqueada_em IS NULL` desde a TEC-236, que tirou a fala bloqueada do contexto e do resumo. Um turno que o resto do produto trata como não-dito não pode virar ponto aqui.
- **`status` não entra.** `RECEIVED`, `QUEUED` e `PROCESSED` descrevem o pipeline de ingestão, não se o lead falou; filtrar por status faria a contagem oscilar com retentativa.
2. `calcular_score(estado, mensagens_do_lead, imoveis_compativeis=0)` devolve o `Score`.
3. Cada fator é uma função privada sobre o que lhe cabe; nenhuma lê fora do que recebeu.
4. `estado is None` devolve `Score` zerado, sem levantar.

**Esta card não grava o score em lugar nenhum e não o chama de dentro do turno.** A RN-06.1 diz *"recalculado a cada atualização de qualificação"*, e onde esse recálculo vive é decisão da TEC-151 (que consome a temperatura derivada dele) e da TEC-152 (que grava a auditoria). Antecipar aqui seria construir um chamador para dois consumidores que ainda não existem, e escolher por eles onde o score mora.

## Testes

- **`tests/unit/test_score.py`**, novo. Cada fator isolado, faixa a faixa — as quatro de urgência, as quatro de engajamento, as três de catálogo, as três de capacidade, e a completude de zero a quatro campos.
- **O cenário de aceite da card, literal:** quatro obrigatórios, prazo de 20 dias, seis imóveis compatíveis, pagamento à vista → ≥70. O `≥70` tem vinte pontos de folga nesse cenário (o total é 90), então o teste também fixa o total exato — sem isso ele não fica vermelho sob mutação nenhuma e documenta sem verificar. Quem pina a diferença que a TEC-158 fará são os dois testes de teto.
- **O mesmo cenário sem catálogo, parametrizado sobre a contagem de mensagens** (1, 2, 3, 5, 6, 99) → ≥70 em todas. É o teste que a premissa falsa da D4 fazia passar por acidente quando fixava a contagem em 4.
- **Os dois mapas de pontos são amarrados aos seus enums:** `set(_PONTOS_POR_URGENCIA) == {m.value for m in Urgencia}` e o mesmo para capacidade. Sem isso, um membro novo em `Urgencia` cai no default do `.get`, pontua 0 — idêntico a `SEM_PRESSA` — e colapsa em silêncio um fator de 25 pontos com toda a suíte verde. É a defesa que a D3 dá a `CAMPOS_OBRIGATORIOS`, aplicada às outras duas acoplagens do módulo com vocabulário que mora fora dele.
- **Determinismo:** o mesmo estado calculado duas vezes dá o mesmo `Score`, e a igualdade do dataclass cobre os cinco fatores, não só o total.
- **`total` é a soma dos cinco**, com um teste que quebraria se um fator fosse esquecido na soma.
- **Teto:** nenhum estado alcançável produz total acima de 95, e nenhum acima de 75 com `imoveis_compativeis=0`.
- **`estado is None`** devolve zerado sem levantar.
- TDD, e cada teste verificado por mutação: trocar uma faixa por outra tem de deixar vermelho exatamente o teste daquela faixa. Nas duas cards anteriores, toda rodada de revisão perdida foi teste que passava com o código certo ou errado.

## Lacunas declaradas

**Os pesos não são configuráveis.** A regra de negócio da card e a CA-19.1 do SRS pedem alteração sem reiniciar a aplicação; a D6 entrega constantes de módulo. Cabe no épico de configuração (RF-19).

**Tempo médio de resposta não entra no engajamento.** A RN-06.1 o cita, e ele fica de fora. Medi-lo exige parear cada mensagem do agente com a próxima do lead — e a primeira mensagem do lead não tem antecedente, duas perguntas seguidas do agente não têm pareamento óbvio, e um lead que responde de manhã a uma pergunta da meia-noite parece desengajado sem ser. Inventar essa métrica sem conversa real deste produto é o tipo de regra que envelhece errado e ninguém revisa.

**As faixas de engajamento são arbitradas.** Ver D4. Não há dado real para calibrá-las; o único guia foi fazer o critério de aceite da própria card fechar. São três, e não quatro, porque a justificativa original das quatro repousava sobre uma premissa falsa — que a D4 agora corrige em vez de repetir.

**O engajamento não decai, e não tem janela de recência.** Oito mensagens de quatro meses atrás valem 15 para sempre; duas de hoje valem 10. O score de um lead é **monotonicamente não-decrescente** ao longo da vida da conversa: nenhum fator pode diminuir com o tempo, e um lead que sumiu continua pontuando o que pontuava no dia em que falou. A consequência é que a TEC-151 rotulará leads parados como `QUENTE`, e a fila do corretor terá no topo gente que não responde há meses.

Onde o recálculo vive é decisão da TEC-151/TEC-152 e está fora de escopo aqui — mas **a forma do fator é decidida nesta card**, e é ela que impede o decaimento. Corrigir depois não é ajustar o chamador: é acrescentar um parâmetro de tempo à assinatura ou reescrever o fator. Fica declarado para que quem for reconciliar ache escrito.

**`FINANCIAMENTO` pontua como pré-aprovado.** Ver D5. O repo não distingue financiamento aprovado de mencionado, então todo lead que fala em financiar recebe os pontos de quem tem carta.

**O score não chega a 100, e para a TEC-151 isso não é uma questão de magnitude.** Teto de 95 com catálogo, 75 sem. Ver D3. A RN-06.2 fixa `QUENTE ≥ 70`, `MORNO` 40–69, `FRIO` < 40 — faixas desenhadas para uma escala que chega a 100.

Dizer que *"a faixa útil encolhe"* é inadequado: descreve um efeito de tamanho onde há uma mudança de natureza. Enquanto a TEC-158 não existir (`imoveis_compativeis=0`), a enumeração exaustiva de todos os estados alcançáveis dá **três totais** ≥70, e nenhum outro:

| Total | Configurações que o alcançam |
|---|---|
| **75** | quatro obrigatórios · `urgencia = IMEDIATA` · `A_VISTA` · ≥6 mensagens |
| **72** | quatro obrigatórios · `urgencia = IMEDIATA` · `FINANCIAMENTO`/`CONSORCIO`/`FGTS` · ≥6 mensagens |
| **70** | quatro obrigatórios · `IMEDIATA` · `A_VISTA` · 1–5 mensagens — **ou** três dos quatro · `IMEDIATA` · `A_VISTA` · ≥6 mensagens |

Ou seja: até a TEC-158, `QUENTE` **não é uma faixa numérica** — é o predicado *"urgência imediata **e** forma de pagamento declarada **e** pelo menos três obrigatórios **e** o lead falou"*. Em particular:

- **Nenhum lead que não seja `IMEDIATA` alcança `QUENTE`.** O máximo para qualquer outra urgência é **65**.
- **Nenhum lead sem forma de pagamento declarada alcança `QUENTE`.** O máximo com coluna nula ou `INDEFINIDA` é **66**.
- **Nenhum lead com zero mensagens alcança `QUENTE`.** O máximo é **60**.

A TEC-151 herda isto diretamente e precisa das *configurações*, não do teto: calibrar uma faixa contra uma escala contínua imaginária, quando o alcançável são três valores, é calibrar contra nada.

A mudança de faixas da D4 **não alterou este conjunto** — {70, 72, 75} já era o alcançável com quatro faixas. O que ela alterou foi quem chega lá: o total 70 passou a ser atingível com 1–5 mensagens, e antes exigia 3–5.

**A aderência ao catálogo é zero enquanto a TEC-158 não existir**, e são 20 dos 95 pontos. Um lead perfeito hoje pontua 75. A card prescreve esse comportamento; a consequência sobre a distribuição de temperatura é desta declaração.

**O score não sabe se o lead está qualificado, e o total sozinho não ordena fila.** Nenhum dos cinco fatores consulta `esta_qualificado`; completude conta campos, não a decisão. Recusa é apenas um caso disso — o geral é mais largo, e é o que a TEC-151 encontra:

| Estado | `esta_qualificado` | Total | Faixa que a TEC-151 aplicaria |
|---|---|---|---|
| `intencao = VENDER_IMOVEL`, resto completo, `IMEDIATA`, `A_VISTA`, 6 mensagens | **False** | **70** | `QUENTE` |
| `intencao = None`, resto igual | **False** | **70** | `QUENTE` |
| Quatro obrigatórios, `IMEDIATA`, `forma_pagamento` nula, 10 mensagens | **True** | 66 | `MORNO` |

A RN-03.4 manda `VENDER_IMOVEL` direto para handoff e o SDR não o qualifica — e ele chega ao topo da fila. Na outra ponta, um lead qualificado que só não disse como pagaria fica abaixo dele. Um obrigatório faltando custa 5 dos 95 pontos, menos que o ruído da contagem de mensagens.

**Consequência operável: quem ordenar a fila tem de combinar o total com `esta_qualificado`, e nunca usar o total sozinho.** Está dito também na docstring de `calcular_score`, que é onde a TEC-151 vai olhar.

O caso da recusa, especificamente: `esta_qualificado` recebe `recusados` e não conta campo recusado como preenchido (D4 da TEC-147); `calcular_score` não recebe esse conjunto. Um lead que recusou falar de orçamento **não é qualificado**, mas ainda pontua a completude do orçamento se a coluna tiver valor de um turno anterior. (Não há fator de preço no score — os cinco são completude, urgência, catálogo, engajamento e capacidade.)

Ficou assim de propósito: a card não menciona recusa em nenhuma das cinco regras nem em nenhum critério de aceite, e acrescentar o parâmetro seria estender o contrato por simetria em vez de por pedido. Mas a divergência é real e quem for reconciliar precisa achá-la escrita, não descobri-la.

**O piso real é 6, e não 0.** `calcular_score(None)` devolve capacidade 0, mas qualquer lead que já tenha linha em `LeadQualification` com `forma_pagamento` nula recebe os 6 de *"a avaliar"*. Os dois casos significam "nunca disse como pagaria" e pontuam diferente, de propósito — sem linha não há lead a ordenar, e o zero é ausência de sujeito, não uma nota sobre ele. É deliberado e testado; fica escrito porque a diferença surpreende quem lê a tabela da D5.

**Nada chama `calcular_score` ainda.** Ver Fluxo. A função existe, é testada e não roda em produção até a TEC-151 ou a TEC-152 decidirem onde o recálculo vive.

## Fora de escopo

- A derivação de temperatura e os gatilhos que forçam `QUENTE` — RN-06.2 e RN-06.3, [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151), que esta card destrava.
- O registro de auditoria de cada recálculo — RN-06.4, [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152).
- A busca de imóveis que alimenta a aderência — [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158).
- Configuração alterável sem reiniciar — RF-19 / CA-19.1.
- A redução de 15 pontos por não comparecimento — RN-12.4, [TEC-172](https://eduardodurieuxlopes.atlassian.net/browse/TEC-172).
- Campos próprios da trilha de investidor — RN-05.2, [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153).

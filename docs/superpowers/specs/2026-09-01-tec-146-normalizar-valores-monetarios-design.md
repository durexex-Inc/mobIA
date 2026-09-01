# TEC-146 — Normalizar valores monetários informados em linguagem natural

**Status:** desenhado em 2026-09-01. Não implementado.

**Card:** [TEC-146](https://eduardodurieuxlopes.atlassian.net/browse/TEC-146) — Must (MoSCoW). Origem: RF-05, RN-05.6 (SRS v1.0, em `docs/srs/`). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144).

**Por que esta card, e por que agora.** O pedido era a [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) (cadência de reengajamento). Ela é bloqueada por uma cadeia de cinco: `TEC-146 → TEC-147 → TEC-150 → TEC-151 → TEC-183`. A TEC-146 é a única raiz destravada — a TEC-145, que a bloqueia, está Feito. A decisão foi respeitar a ordem em vez de dublar a temperatura.

## Objetivo

O lead diz *"uns 500 mil"*, não `500000`. Hoje quem converte é o modelo: o `SCHEMA_DA_EXTRACAO` pede `faixa_preco_min/max` como JSON `number` já em reais, e o código só confere faixa e tipo.

Isso tem um defeito concreto, e ele está no repo agora. `PRECO_MINIMO = Decimal("1")`. Um lead de compra que escreve *"uns 500"* tem **R$ 500** gravado em silêncio, e esse valor vira filtro da busca de imóveis. Não há nada que o distinga de um orçamento de verdade.

**O que esta card entrega:** a normalização determinística em código, o armazenamento em centavos, a banda de plausibilidade por intenção, e a recusa — com pedido de confirmação — do valor que não fecha.

## O que já existe, e que o desenho reusa

**A ordem do schema já favorece o desenho.** `_ORDEM_DOS_CAMPOS = ("intencao", "confianca", "extracao", "resposta", "perguntou")`. A TEC-244 pôs a extração antes da resposta justamente para o modelo isolar o que a fala afirma antes de formular o que dizer. A regra da banda no prompt aproveita essa ordem: quando o modelo escreve a resposta, ele já isolou a expressão de orçamento.

**A acumulação de estado não precisa mudar.** `campos_a_gravar` e `campos_a_marcar` (`domain/context/repositorio.py`) operam sobre `Extracao.preenchidos()`, que itera os campos do dataclass. Mantendo os nomes lógicos dos campos de preço na `Extracao`, a mudança fica confinada entre o schema e o parser.

**O corpus anotado já é material de teste do parser.** `evals/corpus/compra.yaml` pareia *"minha faixa e de 300 a 450 mil"* com `faixa_preco_min: 300000` / `faixa_preco_max: 450000`. As falas são exatamente as expressões que o parser precisa resolver.

**O ritual do orçamento de prompt já está escrito.** O comentário de `classificador.py` manda rodar `pytest -k margem_do_orcamento -s` antes de alongar `SISTEMA_DO_AGENTE`, e `test_a_margem_do_orcamento_do_prompt_e_deliberada` guarda a margem.

## Decisões

### D1 — O modelo devolve a expressão; o inteiro é do código

`faixa_preco_min` e `faixa_preco_max` saem do `SCHEMA_DA_EXTRACAO` como `number`. Entra `faixa_preco_expressao: string | null` — o trecho literal da fala do lead sobre orçamento.

A card diz *"a normalização é determinística (…) não é o modelo que decide o inteiro final"*, e dois critérios de aceite só fecham com esta leitura:

- *"Dada a mesma expressão processada duas vezes, o valor em centavos é idêntico nas duas."* Se o modelo decide a ordem de grandeza, isso não é determinístico — ele pode devolver `500000` numa passada e `500` noutra, e nada no sistema detecta a diferença.
- *"Dada a expressão 'uns 500' para orçamento de compra, então nenhum valor é gravado e o agente pede confirmação."* Para o código enxergar que `500` é ambíguo, ele precisa receber `"uns 500"`. Um número que o modelo já resolveu chega sem a informação que decide o caso.

### D2 — Uma expressão única, não dois campos-string

A alternativa era `faixa_preco_min_expressao` e `faixa_preco_max_expressao`, com o modelo partindo a faixa e o código só convertendo magnitude. Ela reduz muito o parser — some o tratamento de `entre X e Y`.

E quebra no exemplo da própria card. `"entre 400 e 500 mil"` faz o modelo emitir `"400"` e `"500 mil"`. O `"400"` chega ao parser sem marcador de grandeza, cai na regra de ambiguidade da D3 e é recusado — perdendo um limite que o lead informou sem ambiguidade nenhuma.

A causa é que **partir uma faixa é uma decisão de normalização**: o `mil` final vale para os dois lados, e saber disso é justamente o trabalho que a D1 moveu para o código. Devolver a faixa inteira mantém a decisão onde ela foi posta.

### D3 — A banda de plausibilidade é por intenção

Banda única não serve, porque `Intencao` tem `ALUGUEL`: R$ 1.500 é aluguel mensal corriqueiro e preço de compra absurdo.

| Intenção | Banda plausível |
|---|---|
| `COMPRA`, `INVESTIMENTO`, `VENDER_IMOVEL` | R$ 30.000 – R$ 1.000.000.000 |
| `ALUGUEL` | R$ 300 – R$ 200.000 |
| `INDEFINIDA` | união das duas |

Três desfechos distintos, todos terminando em "não grava", logados separadamente porque mandam quem investiga para lados diferentes:

- **`AMBIGUA`** — número nu, sem `mil`/`k`/`milhão`/`R$`, **abaixo do piso** da banda. *"uns 500"*. O parser resolveu um número, mas o lead quase certamente quis dizer outro, e o sistema não deve adivinhar qual.
- **`IMPLAUSIVEL`** — valor resolvido fora da banda por qualquer outro caminho. *"2 milhões e meio"* para aluguel; um número nu acima do teto. O lead disse algo que não fecha com a intenção classificada.
- **`ILEGIVEL`** — o parser não extraiu número nenhum da expressão. *"quinhentos mil"* por extenso, *"o que der"*, ou lixo. É o motivo que mede o buraco da gramática, e por isso não se confunde com os outros dois: `AMBIGUA` e `IMPLAUSIVEL` dizem que o **lead** foi impreciso; `ILEGIVEL` diz que o **parser** não deu conta.

A ordem importa na leitura dos logs: um pico de `ILEGIVEL` é trabalho para a próxima card do parser; um pico de `AMBIGUA` é sinal sobre como os leads deste produto falam de dinheiro.

`faixa_preco_expressao` nula não é recusa: não há o que parsear, nada é gravado e nada é logado. É o caso comum de um turno que não fala de orçamento.

As bandas ficam como constantes de módulo, não configuração. A card pede configurabilidade para os **pesos do score**, que é a TEC-150; sobre bandas de preço ela não diz nada, e configuração que ninguém pediu é superfície a mais para manter.

### D4 — Duas camadas para a confirmação: o prompt pede, o código garante

*"O agente confirma com o lead"* esbarra na ordem real das coisas: o veredito de plausibilidade é do código, e ele só roda quando a chamada inteira já voltou. Quando `extrair` descobre que *"uns 500"* é ambíguo, a resposta ao lead **já está escrita**.

E `extrair` nunca levanta, por desenho declarado — *"extração é enriquecimento, a resposta é o produto"*. Esta é a primeira vez que a extração precisa influenciar a resposta.

São duas camadas, cada uma com um papel:

- **O código é a correção.** Valor ambíguo ou implausível não é gravado. Sem exceção, sem depender de o modelo ter colaborado. `extrair` continua nunca levantando: recusar um campo é descartá-lo, como já é hoje.
- **O prompt é a economia.** A regra da banda entra em `SISTEMA_DO_AGENTE`, e o modelo — que pela TEC-244 já extraiu antes de responder — pergunta no mesmo turno.

É o mesmo raciocínio de duas camadas da TEC-182, e pelo mesmo motivo: a camada que garante não pode depender da que lembra.

Foram recusadas duas alternativas. **Segunda chamada ao modelo** garantiria o mesmo turno, mas acrescenta chamada paga e latência a um turno que `workers/main.py` documenta como somando 360s no pior caso contra um `job_timeout` de 240. **Costurar uma frase determinística** na resposta do modelo custa zero chamadas e destoa de um texto que o modelo compôs.

### D5 — Centavos em `BIGINT`, com a unidade no nome da coluna

`Integer` não serve: `PRECO_MAXIMO` é 10⁹ reais, ou 10¹¹ centavos, e `int32` estoura em ~2,1×10⁹ — R$ 21 milhões. `BIGINT` cabe com folga.

As colunas passam a se chamar `faixa_preco_min_centavos` e `faixa_preco_max_centavos`. `faixa_preco_max = 50000000` sem unidade no nome é armadilha para quem ler depois de a conversa ter esfriado.

Migração `0011`: adiciona as colunas novas, backfill `ROUND(faixa_preco_min * 100)::bigint`, derruba as antigas. **O backfill é lossless por construção, não por sorte**: `numeric(12,2) × 100` é inteiro exato. O downgrade divide por 100 e cabe em `numeric(12,2)` para todo valor dentro da banda da D3 — valores fora dela não são graváveis por nenhum caminho.

### D6 — A faixa invertida continua descartada, por um motivo novo

Hoje `min > max` descarta os dois lados, e a justificativa está escrita no código: *"não há como saber qual dos dois o modelo errou"*.

**Esse argumento morre com a D1.** Não é mais o modelo errando; é a fala literal do lead, e *"entre 500 e 400 mil"* tem intenção óbvia.

O comportamento fica, com outra razão. Sob o desenho novo, faixa invertida é **canário de bug do parser** — o caso mais provável é o marcador de grandeza tendo se ligado ao lado errado. Reordenar em silêncio calaria exatamente o sinal que aponta para o defeito. Recusar custa uma repergunta; aceitar uma faixa remontada por palpite custa um filtro de busca errado que ninguém atribui ao parser.

É a mesma assimetria que `campos_a_marcar` já pratica: *"marcar de mais mata o campo (…) marcar de menos custa uma pergunta a mais"*.

### D7 — O corpus de eval continua anotado em reais

`evals/corpus/*.yaml` segue com `faixa_preco_max: 500000`, e o runner converte para centavos ao comparar.

Anotação é artefato humano. `50000000` convida ao zero a mais de quem adicionar caso novo, e um erro desses num corpus que é o baseline medido da TEC-145 aparece como regressão de acurácia que ninguém atribui a esta migração.

## Fluxo

1. O modelo devolve `extracao.faixa_preco_expressao` — o trecho literal — antes de escrever a resposta.
2. `extrair` chama `dinheiro.parsear(expressao, intencao)`.
3. O parser descarta ruído, resolve marcadores de grandeza, identifica direção e faixa, e produz `(min_centavos, max_centavos)`.
4. A banda da D3 é aplicada com a intenção deste turno. Recusa devolve motivo: `AMBIGUA`, `IMPLAUSIVEL` ou `ILEGIVEL`.
5. Recusado, o campo é descartado e logado com o motivo. `extrair` não levanta; os outros campos do turno seguem.
6. Aceito, `Extracao` carrega `faixa_preco_min_centavos` / `faixa_preco_max_centavos`, e `campos_a_gravar` os acumula como qualquer outro campo.
7. Em paralelo, a regra da banda no prompt faz o modelo pedir confirmação no mesmo turno — melhor esforço, não garantia.

**O parser mora em `src/mobia/domain/agente/dinheiro.py`.** Função pura, sem I/O e sem banco. `schemas.py` já hospeda `normalizar_regiao`, mas esta gramática é grande demais para virar vizinha dela.

| Peça | Regra |
|---|---|
| Ruído | `R$`, `reais`, `uns`, `cerca de`, `por volta de`, `mais ou menos` |
| Grandeza | `mil` / `k` → ×10³; `milhão` / `milhões` / `mi` → ×10⁶ |
| Separadores | `500.000` — ponto é milhar; `1,5` — vírgula é decimal |
| Direção | `até` / `no máximo` / `abaixo de` → só max; `a partir de` / `no mínimo` / `acima de` → só min; valor nu → só max |
| Faixa | `entre X e Y`, `de X a Y`, `X a Y` |
| Distribuição | em `entre 400 e 500 mil`, o `mil` final vale para os dois lados |

Arredondamento: parseia para `Decimal` em reais, multiplica por 100, `quantize(ROUND_HALF_UP)`. Entrada com duas casas é inteira por construção, então o arredondamento só dispara em entrada malformada.

## Testes

- **`tests/unit/test_dinheiro.py`**, novo. A tabela do Gherkin da card, mais as expressões colhidas de `evals/corpus/`. Cobre os três motivos de recusa e a distribuição do marcador na faixa.
- **`tests/unit/test_extracao.py`**. `test_preco_fora_da_faixa_e_descartado`, `test_faixa_invertida_descarta_os_dois_precos` e `test_preco_guarda_precisao_de_decimal` são reescritos para centavos. O segundo mantém o comportamento e ganha docstring com a razão da D6.
- **O runner do eval** ganha a conversão reais→centavos, com teste próprio — sem ele o eval passaria a medir a multiplicação do runner em vez da extração.
- **Integração:** `test_extracao_no_turno.py`, `test_repositorio_contexto.py`, `test_montagem.py`.
- **Orçamento do prompt:** `pytest -k margem_do_orcamento -s` antes de tocar em `SISTEMA_DO_AGENTE`, e `test_a_margem_do_orcamento_do_prompt_e_deliberada` verde depois. Passo do plano, não lembrete.
- TDD, como o resto do repo.

## Lacunas declaradas

**O modelo continua escolhendo o recorte, e isso limita o determinismo.** A card exige que o modelo não decida o inteiro final, e ele não decide. Mas ele decide **qual trecho da fala é a expressão de orçamento**, e duas passadas sobre a mesma conversa podem isolar trechos diferentes. O critério de aceite *"mesma expressão duas vezes → mesmo resultado"* fecha no parser, que é onde ele está escrito. O pipeline inteiro não é determinístico, e nada nesta card o torna.

**O parser é lista fixa de marcadores, e vai errar por falta.** *"quinhentos mil"* por extenso e *"meio milhão"* não são resolvidos. A lista não é estendida por antecipação: cada forma nova é superfície de erro, e não há conversa real deste produto dizendo quais faltam. É o mesmo argumento da lista de termos de opt-out da TEC-182, e a mesma saída — quando houver conversa real, os textos dizem.

**A pergunta no mesmo turno é melhor esforço.** A D4 garante que nada errado é gravado; não garante que o lead seja perguntado. Num turno em que o modelo não pergunte, a confirmação só acontece se o lead voltar a falar de preço por conta própria.

**`INDEFINIDA` cai na banda mais frouxa.** A união das duas faixas aceita R$ 300, que é aluguel plausível e compra absurda. Um lead ainda não classificado que diga *"uns 500"* pode ter o valor aceito como aluguel. A troca é deliberada: fechar a banda na dúvida custaria valores de aluguel legítimos, que são a maioria dos valores baixos.

**Investidor que fala em ticket cai na faixa de preço.** A conversão de ticket de investidor é campo próprio e está fora do escopo por decisão da card (H3.9, [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153)). Até lá, `INVESTIMENTO` usa a banda de compra e grava ticket como se fosse orçamento.

**Ninguém mede quantas expressões o parser recusa.** Se ele recusar um terço das falas de preço, não há alarme — só linhas de log. É métrica de observabilidade; a auditoria da [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152) é irmã disto, mas cobre recálculo de score, não extração.

**O corpus em reais e o banco em centavos divergem por uma multiplicação que só o runner faz.** O teste próprio da D7 fecha o caso conhecido; a lacuna é estrutural e permanece enquanto as duas unidades coexistirem.

## Fora de escopo

- Interpretação de datas em linguagem natural — E5, card própria.
- Conversão de ticket de investidor — H3.9, [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153). Mesma regra, campo próprio.
- A definição de lead qualificado — [TEC-147](https://eduardodurieuxlopes.atlassian.net/browse/TEC-147), que esta card destrava.
- O cálculo do score — [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150).
- A derivação de temperatura — [TEC-151](https://eduardodurieuxlopes.atlassian.net/browse/TEC-151).
- Auditoria de recálculo — [TEC-152](https://eduardodurieuxlopes.atlassian.net/browse/TEC-152).

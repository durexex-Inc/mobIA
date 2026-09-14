# TEC-154 — Indicadores de rentabilidade, com ressalva de estimativa

**Status:** desenhado em 2026-09-14.

**Card:** [TEC-154](https://eduardodurieuxlopes.atlassian.net/browse/TEC-154) — História, Could (MoSCoW), prioridade Medium. Origem: RF-07, RN-07.3, RN-07.5 (SRS v1.0). Épico [TEC-144](https://eduardodurieuxlopes.atlassian.net/browse/TEC-144). Bloqueada pela [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153) (Feito) e pela [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162) (Feito).

**A história:** *"Como Ricardo, lead investidor, quero ver o retorno estimado de cada imóvel, para comparar opções sem abrir uma planilha."*

## Objetivo

A trilha do investidor já existe (TEC-153) e já apresenta imóveis pela mesma ficha da trilha padrão (TEC-162). Esta card acrescenta, **só para quem está na trilha do investidor**, três linhas ao fim da ficha: aluguel estimado com yield bruto anual, condomínio somado ao IPTU, e a ressalva de que o número é estimativa.

## O que a exploração descobriu, e que muda o desenho

**O catálogo já tem as quatro colunas.** `preco_venda`, `preco_aluguel`, `condominio` e `iptu_mensal` estão em `Imovel` desde a TEC-156. Nenhuma migration, nenhuma coluna nova, nenhum parser a mexer.

**Mas o dado quase nunca está lá, e isto foi medido, não estimado.** No seed de 520 imóveis (`data/seed/imoveis.csv`):

| operação | linhas | com `preco_aluguel` | com `preco_venda` | com `condominio` | com `iptu_mensal` |
|---|---|---|---|---|---|
| VENDA | 375 | **0** | 375 | 375 | 375 |
| AMBOS | 53 | 53 | 53 | 53 | 53 |
| ALUGUEL | 92 | 92 | 0 | 92 | 92 |

O yield exige os **dois** preços, e só os 53 `AMBOS` os têm — 10% do catálogo, e **zero** dos 375 imóveis que são só VENDA. Nos 53 calculáveis o yield vai de 4,35% a 6,59% (mediana 5,38%). A consequência é de desenho, não de detalhe: **o cenário 3 do Gherkin ("não inventa número") é o caminho dominante de uma busca de investidor, não a exceção.** Ver a L1.

**A ficha é uma mensagem por imóvel, e só a primeira leva a prosa do modelo.** `_entregar_fichas` chama `legenda_de(ficha, prefixo=prosa if posicao == 0 else None)`. Uma ressalva escrita uma vez na prosa deixaria as fichas 2 e 3 nuas — e elas saem como mensagens independentes, encaminháveis sozinhas. Ver a D5.

**A continuação de entrega parcial não sabe em que trilha está.** `_continuar_entrega` (TEC-275) roda **antes** de `montar_contexto`, então não tem `contexto.estado` nem `ja_e_investidor` — o próprio comentário dela já declara que a telemetria subconta a trilha do investidor por essa razão. Sem conserto, a ficha 1 sairia com indicadores e as fichas 2 e 3, minutos depois, sem. Ver a D7.

**O cenário 4 já está atendido.** `SISTEMA_DO_INVESTIDOR` (TEC-153) diz *"Nao prometa rentabilidade nem projete valorizacao"*. Esta card não acrescenta texto de prompt nenhum; acrescenta o teste que prende a frase.

**O teto fixo do orçamento de prompt não é tocado.** Ele mede `SISTEMA_DO_AGENTE`, e nada aqui entra em prompt algum: o número sai determinístico na ficha.

## O estado de hoje

| Peça | Estado | Consequência |
|---|---|---|
| `Imovel.preco_aluguel` / `condominio` / `iptu_mensal` | existem, populados no seed conforme a tabela acima | D2, L1 |
| `Ficha` | oito campos da RN-10.1 + `id`, sem nada de investidor | D1 |
| `legenda_de` | teto de 600 caracteres, corta a prosa e nunca a ficha | D6 |
| `fichas_do_catalogo` | único ponto em que `domain/agente` toca `domain/catalogo` | D3 |
| `_apresentar` | um só chamador, serve as duas trilhas | D3 |
| `_continuar_entrega` | sem acesso ao estado da conversa | D7 |
| `SISTEMA_DO_INVESTIDOR` | já proíbe projetar valorização | L3 |
| `POST /api/v1/imoveis/busca` | SRS §6.3 promete `yieldBrutoAnual`; a rota não o tem | L2 |

## Decisões

### D1 — `Rentabilidade` é um objeto próprio, opcional dentro de `Ficha`

`Ficha.rentabilidade: Rentabilidade | None`. `None` significa **trilha padrão**, e é o que impede confundir "não é investidor" com "é investidor e o catálogo não tem o dado" — dois estados que a mesma ficha precisa distinguir, porque o segundo imprime uma linha e o primeiro não imprime nada.

Os oito campos da RN-10.1 continuam sendo oito. Acrescentá-los soltos em `Ficha` faria a docstring daquele dataclass (*"os oito campos da RN-10.1"*) passar a mentir, e comentário desatualizado é defeito neste repo.

```python
@dataclass(frozen=True, slots=True)
class Rentabilidade:
    aluguel_centavos: int | None
    yield_pct: Decimal | None
    custos_centavos: int | None
```

Os três campos são independentes, com **uma** invariante: `yield_pct` não nulo implica `aluguel_centavos` não nulo. As combinações que existem de verdade:

| `preco_aluguel` | `preco_venda` | linha do aluguel | ressalva |
|---|---|---|---|
| tem | tem | valor **e** yield | sim |
| tem | nulo (imóvel só de aluguel) | valor, sem yield | sim |
| nulo | qualquer | `nao informado` | não |

`custos_centavos` não entra na tabela porque não depende de nenhum dos dois: condomínio e IPTU aparecem mesmo sem aluguel, porque são fato do catálogo e não estimativa.

### D2 — O yield sai de `Imovel.preco_venda`, nunca de `Ficha.preco_centavos`

`preco_centavos` é o preço da **operação buscada** — é assim que a D7 da TEC-162 impede que toda busca de aluguel mostre preço de venda ao lead. Aqui a regra é a oposta, pelo mesmo cuidado: num investidor que buscasse `ALUGUEL`, `preco_centavos` **é** o aluguel, e `aluguel × 12 ÷ aluguel` daria um yield de 1200% ao ano numa ficha que o lead lê como fato.

A RN-07.3 define o yield sobre o preço de venda, qualquer que tenha sido a busca. `preco_venda` nulo (imóvel só de aluguel, alcançável se o investidor buscar `ALUGUEL`) implica sem yield — mas **a linha do aluguel sai mesmo assim, com o valor e sem o sufixo do yield**. Trocá-la por `nao informado` seria dizer que não sabemos um aluguel que está no catálogo, que é precisamente a mentira que o cenário 3 do Gherkin existe para impedir na direção contrária.

### D3 — O cálculo é puro; a leitura das colunas fica onde já estava

`yield_bruto_anual` e `custos_recorrentes` entram em `apresentacao.py`, que **não importa `domain/catalogo`** e por isso é testável em `tests/unit/` sem Postgres de pé. Quem lê as quatro colunas e monta `Rentabilidade` é `fichas_do_catalogo`, em `ferramenta_de_busca.py` — o único arquivo em que `domain/agente` toca `domain/catalogo`. A invariante não se mexe; ganha um parâmetro:

```python
async def fichas_do_catalogo(..., rentabilidade: bool = False) -> tuple[Ficha, ...]
```

Default `False` para que todo chamador existente siga idêntico: a trilha padrão não paga nada, nem em bytes nem em comportamento.

### D4 — O yield trunca para baixo

`reais_de` já trunca centavos para baixo, com a razão escrita: arredondar preço para cima cota ao lead acima do real, e é essa a direção que vira reclamação na visita. O yield herda o argumento invertido — arredondar para cima **promete retorno acima do real**. 4,35% vira `4,3%`, nunca `4,4%`.

Uma casa decimal, como o Gherkin ("6,0% ao ano"). O zero à direita é obrigatório: `6%` e `6,0%` dizem coisas diferentes sobre precisão.

### D5 — A ressalva sai em toda ficha que carregue número estimado

A RN-07.5 diz *todo* número. Cada ficha é uma mensagem própria no WhatsApp, encaminhável sozinha, e na entrega parcial a ficha 2 chega numa passada posterior sem a ficha 1 por perto. Uma ressalva única na prosa cobriria a primeira e deixaria as outras nuas.

O texto é um só, determinístico, e serve **duas** regras de uma vez: `Estimativa, nao e garantia de retorno.` — a ressalva de estimativa da RN-07.5 e a proibição de apresentar rentabilidade como garantia da RN-04.4.

Determinístico, e não redigido pelo modelo, pelo precedente que este repo já firmou duas vezes: o aviso de ampliação da TEC-160 e o motivo de match da TEC-163. Texto do modelo some num turno e muda de palavra no outro, e aqui o que sumiria é justamente a ressalva.

**Sem número estimado, não sai ressalva.** "Número estimado" é o aluguel, o yield, ou os dois — a tabela da D1 diz quando cada um existe. Condomínio e IPTU sozinhos não puxam ressalva: são fato do catálogo, e ressalvá-los ensinaria o lead a ignorar a linha quando ela importa.

### D6 — O bloco vai no fim da ficha, e a prosa continua sendo quem cede

Ordem das linhas: a ficha padrão inteira, e depois o bloco de três linhas terminando na ressalva. A ficha que o lead já conhece não muda de forma, e o extra fica coeso.

A linha `Condominio R$ 1.844` **permanece** mesmo com `Condominio + IPTU R$ 2.615/mes` logo abaixo. A redundância é deliberada: `condominio` é um dos oito campos da RN-10.1, e suprimi-lo para o investidor quebraria aquela regra para ganhar 20 caracteres. De quebra, as duas linhas juntas revelam o IPTU, que não tem linha própria.

Medido com um imóvel real do seed, o bloco são **122 caracteres**. Dos 600 de `MAX_CARACTERES_DA_LEGENDA`, a prosa passa a ter ~320 em vez de ~440. Nada na prioridade muda: `_prosa_que_cabe` já corta o prefixo e nunca o corpo, e é por isso que o bloco entra no corpo.

Exemplo, com os valores reais da linha `TE-1007` do seed:

```
Terreno em Balneario
Balneario - R$ 2.417.514
0 quartos - 0 vagas - 373 m2
Condominio R$ 1.844
Destaque: pet friendly e varanda gourmet
Aluguel estimado R$ 8.760 - yield bruto 4,3% ao ano
Condominio + IPTU R$ 2.615/mes
Estimativa, nao e garantia de retorno.
```

E o mesmo imóvel se o catálogo não tivesse `preco_aluguel` — o caso de ~88% dos candidatos de VENDA. Sem número estimado, some a ressalva junto:

```
...
Condominio R$ 1.844
Destaque: pet friendly e varanda gourmet
Aluguel estimado: nao informado
Condominio + IPTU R$ 2.615/mes
```

Tudo ASCII sem acento, como todo texto que sai para o lead (`Condominio`, `m2`, `nao`). "yield" fica em inglês porque é como o investidor brasileiro chama, e é a palavra da própria RN-07.3.

### D7 — A continuação lê o estado, e a apresentação sai coerente

`_continuar_entrega` chama `ler_estado` (já existe, já é chaveada por `(channel, conversation_key)`) e liga o bloco quando `intencao == INVESTIMENTO`. Uma consulta a mais numa função que já faz várias.

Sem isso, a ficha 1 sairia com yield e as fichas 2 e 3 sem — a mesma apresentação em dois formatos, e dessa vez quem vê é o lead, não quem opera.

**Custo declarado:** o estado lido é o de **agora**, não o do instante da apresentação original. Coincidem em praticamente todo caso, porque a continuação reprocessa a **mesma mensagem** e o turno que moveria a intenção é justamente o que está sendo continuado. A alternativa exata — gravar a trilha na linha de `recomendacoes` — custa coluna, migration e mais uma tabela no `TRUNCATE` de todo teste que toca banco, o que não se paga numa card Could.

### D8 — O número não entra no `tool_result`

`_candidato_serializavel` não ganha campo. É a D7 da TEC-265 outra vez: número no prompt convida o modelo a repeti-lo em prosa — sem a ressalva, com outro arredondamento, ou virando "rende 6% garantidos".

Isto **não** cega o modelo sobre o assunto: `record_agent_message` grava as legendas na linha do tempo, então num turno seguinte ele vê exatamente o que o lead viu, ressalva inclusa.

### D9 — O gatilho é a trilha, nunca o perfil

Os indicadores dependem de `intencao == INVESTIMENTO` (`ja_e_investidor or virou_investidor` em `executar_turno`). **Não** de `perfil_investidor`.

A Emenda E-01 da RN-07.2 (TEC-153) fecha isso por escrito: o perfil é `NULL`, e não `MISTO`, enquanto faltar horizonte ou tipo de retorno, e *"a RN-07.3 e a TEC-154 não podem tratar perfil ausente como misto"*. Um Ricardo que ainda não respondeu horizonte é investidor do mesmo jeito, e a ficha dele leva os números.

## Lacunas declaradas

**L1 — O yield quase nunca vai aparecer, e isso é do catálogo, não do código.** Medido acima: 53 dos 520 imóveis do seed têm os dois preços, e **nenhum** dos 375 que são só VENDA. A funcionalidade entra correta e quase sempre silenciosa — na maioria das apresentações o lead vai ler `Aluguel estimado: nao informado`. Popular o catálogo é decisão de produto, do épico E4, e esta card não a toma nem a disfarça.

**L2 — `yieldBrutoAnual` do `POST /api/v1/imoveis/busca` não é implementado.** O SRS §6.3 promete o campo na resposta da rota. O agente chama `buscar_com_relaxamento` direto, em processo, e nunca consome aquela rota: o campo nasceria sem consumidor. Fica como critério do SRS sem exercício, nomeado para quem cuidar da superfície HTTP.

**L3 — O cenário 4 não gera código nesta card.** A proibição de projetar valorização já está em `SISTEMA_DO_INVESTIDOR` desde a TEC-153. Esta card acrescenta o teste que prende a frase ao prompt; o comportamento não é novo.

## Emendas ao SRS

**RN-10.1 — Emenda E-01 (TEC-154, 14/09/2026).** A regra fixa oito campos por imóvel apresentado. Na trilha do investidor (RN-07.3), a ficha leva **três linhas além dos oito**, ao fim: aluguel estimado com yield bruto anual, condomínio somado ao IPTU, e a ressalva da RN-07.5. Os oito campos não mudam nem cedem espaço — inclusive a linha de condomínio, que permanece ao lado do somatório com o IPTU. Fora da trilha do investidor a ficha é exatamente a de hoje.

**RN-07.3 — Emenda E-01 (TEC-154, 14/09/2026).** A regra diz "valor do aluguel estimado" sem nomear a origem. Fica fixado que a origem é a coluna `preco_aluguel` do catálogo: **não existe coluna de aluguel estimado**, e nada é estimado pelo sistema nem pelo modelo. O yield usa `preco_venda` do catálogo qualquer que tenha sido a operação buscada, e não o preço apresentado ao lead. **Consequência declarada:** imóvel sem `preco_aluguel` ou sem `preco_venda` não exibe yield — no seed de 520 imóveis isso alcança 467 deles, entre eles todos os 375 que são só VENDA.

**RN-07.5 — Emenda E-01 (TEC-154, 14/09/2026).** A ressalva é texto determinístico do código, repetido em **cada** ficha que carregue número estimado, e não redigido pelo modelo — precedente do aviso de ampliação (TEC-160) e do motivo de match (TEC-163). Ela **não** acompanha condomínio e IPTU quando não há número estimado: são fato do catálogo, e ressalvá-los ensinaria o lead a ignorar a ressalva onde ela importa.

## Testes

Unitários, sem Docker de pé:

- `yield_bruto_anual` com os números literais do Gherkin: R$ 500.000 e R$ 2.500 produzem `6,0%`.
- Truncamento para baixo: 4,35% produz `4,3%` (D4).
- `preco_venda` nulo, `preco_venda` zero e aluguel nulo: sem yield, cada um por sua razão.
- Aluguel presente com `preco_venda` nulo: a linha sai com o valor, **sem** o sufixo do yield, **com** ressalva (D1, D2).
- `custos_recorrentes` com condomínio e IPTU, com só um dos dois, e com nenhum.
- `legenda_de` com `rentabilidade=None`: legenda idêntica à de hoje, byte a byte.
- `legenda_de` com número: as três linhas, na ordem, no fim.
- `legenda_de` sem aluguel: `Aluguel estimado: nao informado` **e nenhuma ressalva** (D5).
- Teto de 600 com o bloco dentro: a prosa é cortada, a ficha sai inteira.
- `SISTEMA_DO_INVESTIDOR` contém a proibição de projetar valorização (L3).

Integração:

- `fichas_do_catalogo(rentabilidade=True)` sobre linhas reais, com e sem os preços.
- Turno de investidor apresenta com o bloco; turno de comprador apresenta sem.
- `_continuar_entrega` de um lead investidor mantém o bloco nas fichas 2 e 3 (D7).

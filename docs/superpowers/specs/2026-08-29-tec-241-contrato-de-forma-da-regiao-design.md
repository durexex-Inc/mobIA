# TEC-241 — Contrato de forma para `regiao`

**Status:** aprovado em 2026-08-29. Não implementado.

**Card:** [TEC-241](https://eduardodurieuxlopes.atlassian.net/browse/TEC-241) — origem: a execução paga do gate de 28/08/2026.

**Emenda:** este spec emenda a decisão de `regiao` como texto livre tomada no spec da TEC-145.

## Objetivo

Na execução de 28/08, `regiao` sozinho respondeu por **10 das 29 discrepâncias** — o maior balde, e todas do tipo `divergiu`: o campo foi anotado, o modelo extraiu, e os dois valores não bateram.

Não é falta de anotação (`regiao` tem a maior cobertura do corpus) nem falha do modelo. É **desacordo de forma**. `_comparavel` faz apenas `strip` e `casefold`, então qualquer diferença de forma conta erro cheio.

## O que já existe

Levantado no código e no corpus antes do desenho, não presumido.

**As 18 anotações de `regiao`, e onde está o ruído.** Só **duas** carregam preposição:

| conversa | anotado | a fala |
|---|---|---|
| `aluguel-01` i0 | `perto da usp` | "alugar um kitnet **perto da usp**" |
| `aluguel-07` i0 | `perto da unicamp` | "pra alugar **perto da unicamp**" |

As outras 16 já são topônimo limpo (`brooklin`, `vila madalena`, `zona leste`, `jardins`, `paulista`, `tatuape`, `cotia`, `sp`, …).

**Isso corrige a leitura do card.** A tabela dele lista quatro turnos, mas em dois — `aluguel-02` i0 (`brooklin`, fala "na **regiao do** brooklin") e `aluguel-06` i1 (`vila madalena`, fala "perto da **estacao** vila madalena") — a anotação **já está canônica**. Nesses, a divergência não veio da anotação: veio do **modelo** devolvendo a forma suja da fala.

Consequência de desenho: o ruído aparece nos **dois** lados, e maioritariamente no lado obtido. Normalizar só a anotação, ou só a comparação, não fecha o caso.

**`_comparavel`** (`src/mobia/evals/metricas.py`) normaliza `str` com `strip().casefold()`, e é aplicada aos dois lados da comparação.

**`extrair`** (`src/mobia/domain/agente/classificador.py`) valida `regiao` só por comprimento (≤ 120 caracteres) e devolve o texto como veio.

**`lead_qualification.regiao`** é `String(32)`, filtrada por igualdade em SQL pela TEC-158.

## Decisões

### D1 — Uma função, dois consumidores

`normalizar_regiao(texto: str) -> str` em `src/mobia/domain/agente/schemas.py`, ao lado de `Extracao`.

Mora em `schemas.py` e não em `classificador.py` porque `evals/metricas.py` precisa importá-la, e `classificador.py` arrasta o cliente Anthropic e o `structlog` junto. `schemas.py` não arrasta nada, e a direção da dependência (evals → domain) é a que já existe.

Dois consumidores:

- **`extrair`** a aplica antes de devolver. `lead_qualification` passa a guardar forma canônica, que é o que a TEC-158 vai filtrar.
- **`_comparavel`** a aplica quando o campo é `regiao`. A medição passa a comparar formas comparáveis.

**Uma função só, e isso é decisão, não conveniência.** O card apresenta "normalizar na comparação" e "normalizar na extração" como alternativas; elas não são. Normalizar só na extração deixa o lado esperado sujo (`"perto da usp"` no YAML contra `"usp"` do modelo) e **não** satisfaz o critério de aceite do próprio card. Duas funções divergiriam, e o repositório já recusou isso duas vezes — `faixa_de_catastrofe` deletada no PR #10, `campos_a_gravar` extraída para o eval não divergir de produção.

### D2 — O que a normalização tira

Prefixos de referência, no início da string, depois de `casefold` e colapso de espaço:

`perto da` · `perto do` · `perto de` · `proximo a` · `proximo ao` · `proximo da` · `proximo do` · `regiao da` · `regiao do` · `regiao de` · `regiao das` · `regiao dos` · `estacao`

E nada mais. Em particular **`zona` não é tirada**: `zona leste`, `zona sul` e `zona oeste` são o nome, não ruído — três das 18 anotações dependem disso.

A remoção é de **prefixo**, não de subcadeia. `"estacao"` no meio de um nome sobrevive; só some quando abre a string.

E **repete enquanto casar**: `"perto da estacao vila madalena"` perde `perto da`, sobra `"estacao vila madalena"`, que perde `estacao` e sobra `"vila madalena"`. Um passo só deixaria metade do ruído, e a fala de `aluguel-06` i1 é exatamente esse caso. Repetir também é o que torna a função idempotente por construção, em vez de por sorte.

### D2.1 — Região que é só ruído vira `None`, não string vazia

`"perto da"` normaliza para vazio. Devolver `""` gravaria uma região vazia em `lead_qualification` e a TEC-158 filtraria por ela; devolver o original gravaria ruído.

`normalizar_regiao` devolve a string normalizada, e **`extrair` descarta o campo quando ela sai vazia** — o mesmo tratamento que já dá a preço fora de faixa e a `quartos` fora de 0–20: campo malformado é descartado um a um, sem derrubar a resposta. Em `_comparavel` o vazio não precisa de tratamento especial: se os dois lados normalizam para vazio, eram a mesma coisa.

### D3 — Normalizar perde informação, e isso é aceito por escrito

`"perto da usp"` e `"usp"` passam a ser a mesma coisa. Mas um lead que disse "perto da usp" quer **proximidade**, não o campus — e essa distinção some do banco.

Para o filtro estruturado da TEC-158 isso é ganho: `"usp"` é filtrável, `"perto da usp"` não. Para um corretor lendo o registro do lead, é perda. A decisão é a favor do filtro, porque `lead_qualification` existe para ser consultada em SQL — o texto original da fala continua no histórico de mensagens, cifrado, que é onde ele pertence.

### D4 — É mudança de comportamento de produção, sem migração retroativa

`gravar_estado` passa a escrever valores diferentes dos de hoje. Os registros já gravados ficam na forma velha, e **não há migração** — o corpus de produção é pequeno e a próxima fala do lead sobrescreve pelo mais novo (D4 da TEC-145). Declarado em vez de silencioso: por um tempo, `lead_qualification.regiao` terá as duas formas convivendo.

### D5 — O corpus não é reanotado, mas ganha a regra escrita

As duas anotações com preposição (`aluguel-01` i0, `aluguel-07` i0) **ficam como estão**: `_comparavel` normaliza os dois lados, então elas passam a casar sem edição. Reanotá-las seria mexer na régua sem necessidade.

O cabeçalho do YAML passa a dizer que `regiao` se anota como topônimo, sem preposição — para que anotação nova já nasça canônica. É a opção 3 do card, adotada como documentação e não como mecanismo.

## Contrato depois da card

- `normalizar_regiao` é a única regra de forma de `regiao`, com dois chamadores.
- `lead_qualification.regiao` guarda topônimo canônico.
- A medição compara formas canônicas dos dois lados.
- O texto original da fala segue intacto no histórico de mensagens.

## Testes

Os pares reais que o card nomeia, mais os que o levantamento do corpus revelou:

1. `"perto da usp"` → `"usp"`; `"perto da unicamp"` → `"unicamp"` (o lado **anotado** sujo).
2. `"estacao vila madalena"` → `"vila madalena"`; `"regiao do brooklin"` → `"brooklin"`; `"regiao dos jardins"` → `"jardins"`; `"regiao da paulista"` → `"paulista"` (o lado **obtido** sujo, que é o caso maioritário).
3. **`zona leste`, `zona sul`, `zona oeste` sobrevivem intactas** — o teste que impede a normalização de comer nome de região.
4. `_comparavel` casa `"perto da usp"` com `"usp"` — o teste de ponta a ponta da métrica.
5. `extrair` devolve `regiao` já canônica.
6. As 18 anotações do corpus commitado, depois de normalizadas, não colidem entre si — duas regiões distintas não podem virar a mesma string.
7. Normalização é idempotente: `f(f(x)) == f(x)`.
8. Prefixos encadeados caem no mesmo passe: `"perto da estacao vila madalena"` → `"vila madalena"`.
9. `"perto da"` sozinho normaliza para vazio, e `extrair` descarta o campo em vez de gravar `""`.

## O que esta card não entrega

**O critério "as divergências de `regiao` caem para perto de zero numa execução do gate" exige execução paga, e ela não será feita nesta card.** O que é entregue é o mecanismo e os testes com os pares reais; o número medido depende de autorização para gastar.

E fica declarado que **não há baseline comparável**: os 29 de 28/08 são de um corpus que mudou duas vezes desde então (TEC-239 levou as anotações de 47 para 59; TEC-238 acrescentou 37 turnos negativos).

## Fora de escopo

- Sinônimos de `tipo_imovel` (kitnet, república, sobrado) — 8 discrepâncias na mesma execução, e **nenhuma card as trata hoje**. O card manda-as para a TEC-239, que é sobre cobertura de campos sem anotação e não sobre sinônimos; essa referência está errada e a dívida segue sem dono.
- Taxonomia fechada de bairros e cidades. A decisão da TEC-145 de manter `regiao` como conjunto aberto continua de pé — esta card dá forma, não vocabulário.
- Migração dos registros já gravados (ver D4).
- O prompt (TEC-240).

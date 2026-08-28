# TEC-145 — Extrair critérios de qualificação da fala do lead

**Status:** aprovado em 2026-08-28. Não implementado.

**Card:** [TEC-145](https://eduardodurieuxlopes.atlassian.net/browse/TEC-145) — Must (MoSCoW), origem RF-05, RN-05.1, RN-05.4 (SRS v1.0).

## Objetivo

O agente hoje conversa e não extrai nada. A tabela `lead_qualification` existe, tem
os nove campos, e o docstring dela diz literalmente *"Esta historia le; TEC-145
escreve."* Esta card é o lado da escrita: fazer o que o lead diz virar estado
estruturado, para que TEC-147 (quando o lead está qualificado), TEC-150 (score) e
TEC-158 (filtro do catálogo) tenham por onde consultar.

## O que já existe

Levantado no código antes do desenho, não presumido:

- `lead_qualification` (`src/mobia/domain/context/models.py:78`), PK
  `(channel, conversation_key)`, nove campos anuláveis mais `updated_at`. **Em
  claro** por decisão registrada no próprio docstring: cifrar forçaria carregar a
  tabela inteira em memória para TEC-147/150/158 filtrarem em SQL.
- `ler_estado` (`src/mobia/domain/context/repositorio.py:102`). Não existe
  `gravar_estado`.
- `montar_prompt` já renderiza `Estado de qualificacao:` no prompt
  (`src/mobia/domain/context/montagem.py:424`), e `SISTEMA_DO_AGENTE` já instrui a
  não reperguntar campo preenchido. **Isso é prompt, não controle:** não há teste
  nem garantia.
- A chamada do turno usa `output_config.format` com `json_schema` e devolve
  `{intencao, confianca, resposta}`. **Não há tools em nenhum lugar do
  repositório** — `_chamar` recusa todo `stop_reason` que não seja `end_turn`.

## Decisões e divergências do card

### D1 — A extração viaja na chamada que já existe, não em tool call

O card manda: *"O modelo propõe a atualização por tool call; a gravação no estado é
feita pelo código."* **Divergimos da primeira metade e mantemos a segunda.**

`SCHEMA_DA_RESPOSTA` ganha um objeto `extracao`. Não há chamada nova, não há tool.

Por quê: o contexto de entrada já foi pago nessa chamada, e o docstring de
`desambiguar` registra que *input domina a contagem de tokens* — uma chamada
separada pagaria o contexto inteiro de novo, em 100% dos turnos, o preço que hoje
só o turno ambíguo paga. Tool call teria um custo adicional: `tool_use` é um
`stop_reason` diferente de `end_turn`, e a recusa de `_chamar` a tudo que não seja
`end_turn` é exatamente a invariante que impede resposta truncada de chegar ao
lead. Quebrá-la para extrair seria trocar uma garantia de produção por conformidade
de forma.

A segunda metade do card continua valendo: **o modelo propõe, o código grava.**
Nada do que o modelo devolve entra na tabela sem passar pela conversão e pelas
guardas descritas abaixo.

**Risco aceito:** mexer no schema da chamada cuja acurácia foi medida em 95,6% e
96,3% (gate da TEC-210) pode regredir a classificação. O gate dispara
automaticamente em PR que toque `src/mobia/domain/agente/`, então a regressão
aparece antes de produção — mas custa uma execução paga para descobrir.

### D2 — Preço é extraído aqui, apesar de a normalização ser da TEC-146

O card manda normalização monetária para a TEC-146 e ao mesmo tempo exige, no
Gherkin, que *"até 600 mil"* preencha a faixa de preço. As duas coisas não cabem
juntas na leitura literal.

Resolução: `faixa_preco_min` e `faixa_preco_max` são tipados como **número** no
schema. A conversão de *"600 mil"* para `600000` é do modelo, não de código nosso,
então a TEC-146 continua dona do que é difícil — *"uns 600 pau"*, *"meio milhão"*,
e a ambiguidade entre valor total e aluguel mensal — e desta card sai só o caminho
comum, com guardas.

### D3 — `intencao` não é extraída

A tabela tem a coluna `intencao`, e a tabela `conversation_intent` também. O campo
**não** entra no objeto de extração: gravamos a intenção que o classificador já
decidiu no mesmo turno. Duas fontes para o mesmo fato divergem, e a divergência
apareceria como bug de score na TEC-150.

### D4 — Sobrescrita pelo mais novo, sem histórico

Valor novo para campo já preenchido **vence**. O lead que diz *"zona sul"* e três
turnos depois *"na verdade zona norte"* precisa ser respeitado; corrigir-se é
comportamento normal de conversa.

**Risco aceito, decidido com o risco à vista:** como a tabela guarda só o valor
atual e não há tabela de auditoria nesta card, uma extração ruim apaga dado bom em
definitivo, sem deixar rastro de que houve troca. A alternativa considerada
(histórico de alteração de campo) foi recusada por sobrepor desenho com a TEC-152,
que já pede auditoria de recálculo de score.

### D5 — O seletor de perguntas não é desta card

O Gherkin do card inclui *"Quando o agente escolhe a próxima pergunta / Então ele
pergunta um campo ainda vazio / E não pergunta a região novamente"*. Esta card
**não** transforma isso em controle de código.

A escolha da pergunta continua do modelo, guiada pelo prompt, e passa a ter
**medição** (ver "Medição" abaixo) em vez de garantia. Por quê: TEC-148 (respeitar
recusa de campo) e TEC-149 (teto de 8 perguntas e oferecer o corretor) mexem no
mesmo seletor. Construí-lo aqui significaria reescrevê-lo duas vezes.

**Consequência declarada:** se o modelo reperguntar um campo preenchido, sabemos
por medição e não impedimos.

## Contrato de extração

### Dataclass

`Extracao`, frozen, em `src/mobia/domain/agente/schemas.py`, ao lado de
`RespostaDoAgente` e `PerguntaDeDesambiguacao`. `RespostaDoAgente` ganha
`extracao: Extracao`.

Campos, todos anuláveis (`None` significa "o lead não falou disso neste turno"):

| Campo | Tipo | Coluna |
|---|---|---|
| `faixa_preco_min` | `Decimal \| None` | `Numeric(12, 2)` |
| `faixa_preco_max` | `Decimal \| None` | `Numeric(12, 2)` |
| `regiao` | `str \| None` | `String(120)` |
| `tipo_imovel` | `TipoImovel \| None` | `String(32)` |
| `quartos` | `int \| None` | `Integer` |
| `vagas` | `int \| None` | `Integer` |
| `urgencia` | `Urgencia \| None` | `String(32)` |
| `forma_pagamento` | `FormaPagamento \| None` | `String(32)` |
| `tem_imovel_para_vender` | `bool \| None` | `Boolean` |

### Vocabulário controlado

Três `StrEnum` novos em `schemas.py`, derivados no schema do mesmo jeito que
`Intencao` já é (o comentário do enum registra que acrescentar membro muda o
conjunto que o modelo pode devolver):

- `TipoImovel`: `APARTAMENTO`, `CASA`, `TERRENO`, `COMERCIAL`, `RURAL`.
- `Urgencia`: `IMEDIATA`, `ATE_3_MESES`, `ATE_6_MESES`, `SEM_PRESSA`.
- `FormaPagamento`: `A_VISTA`, `FINANCIAMENTO`, `CONSORCIO`, `FGTS`, `INDEFINIDA`.

`regiao` fica **texto livre**: bairro e cidade são conjunto aberto, e inventar
taxonomia aqui seria decisão de produto que este desenho não tem. As colunas dos
três enums são `String(32)`; texto livre nelas envenenaria os filtros SQL da
TEC-158, e é por isso que só `regiao` escapa.

### Forma no JSON Schema

Todos os campos internos são **obrigatórios e aceitam `null`**. Forçar o modelo a
dizer `null` explicitamente é mais confiável que aceitar chave ausente.

**A forma da anulabilidade é `anyOf`, não `type` em lista.** Verificado na fonte do
SDK, não presumido: `.venv/Lib/site-packages/anthropic/lib/_parse/_transform.py`
declara `SupportedTypes` como `Literal` de tipos **únicos** e encerra o dispatch de
tipo em `assert_never(type_)`. Um `{"type": ["string", "null"]}` não casaria com
nenhum ramo e estouraria ali. Como `_SCHEMA_COMPILADO` é calculado no import do
módulo, a falha seria na carga — barulhenta e pega por qualquer teste, mas total.

A forma correta é a que o mesmo arquivo trata na linha 100, recursando em cada
variante, com `"null"` entre os tipos suportados:

```python
{"anyOf": [{"type": "string"}, {"type": "null"}]}
```

`minimum` e `maximum` continuam **não** suportados — está no comentário de
`_SCHEMA_COMPILADO`, que registra que enviá-los seria 400 na primeira chamada real.
`transform_schema` os dobra para dentro de `description`. Por isso as guardas de
faixa são de código, não de schema.

### Guardas de código

Aplicadas depois do parse, antes de gravar. Campo que falha na guarda é
**descartado com log**; os outros campos do mesmo turno seguem.

- Preço negativo é descartado.
- `faixa_preco_min > faixa_preco_max` descarta os dois.
- Preço fora de `[1, 10^9]` é descartado como magnitude absurda.
- `quartos` ou `vagas` fora de `[0, 20]` é descartado.
- Valor de enum que não converte é descartado.

### Extração inválida não derruba o turno

Como a extração agora divide a chamada com a resposta ao lead, um valor malformado
não pode fazer `RespostaInvalida` matar uma resposta entregável. **Extração é
enriquecimento; a resposta é o produto.**

Concretamente: o parse da extração fica em bloco próprio, e sua falha vira
`Extracao` toda-`None` mais log — nunca `RespostaInvalida`. As checagens de
`intencao`, `confianca` e `resposta` continuam exatamente como estão, incluindo o
`RespostaInvalida` que elas levantam.

## Caminho de escrita

`gravar_estado` novo em `src/mobia/domain/context/repositorio.py`, irmão de
`gravar_resumo`, com upsert `ON CONFLICT (channel, conversation_key) DO UPDATE`.

Chamado **de dentro do bloco de sessão que já existe** em
`src/mobia/domain/agente/turno.py:132-142`, junto de `gravar_intencao`: os dois
fatos vêm da mesma chamada ao modelo, e um commit só os torna atômicos entre si.
Nenhum bloco de sessão novo.

### `null` não apaga

A regra que faz "o mais novo vence" funcionar em vez de destruir tudo: só campo com
valor não-nulo é escrito. `null` é *"o lead não falou disso"*, nunca *"esqueça o
que sabia"*.

**Consequência aceita:** não existe como limpar um campo — só sobrescrever.

### Saída bloqueada não descarta a extração

Isto é deliberadamente o **oposto** da correção feita na TEC-233, e a razão da
diferença é qual lado da conversa gerou o fato.

Lá, saída bloqueada não podia marcar `desambiguado_em` porque *a pergunta nunca foi
feita* — fato sobre o que **nós** dissemos. Aqui o fato é sobre o que **o lead**
disse, e ele disse independentemente de a nossa resposta ter sido entregue. Mesma
lógica para `EnvioForaDaJanela`.

Entrada bloqueada não chega a classificar, então não há extração — consistente sem
esforço.

### Qual intenção permite escrever

Todas menos `FORA_DE_ESCOPO`.

O card diz *"campos para COMPRA e ALUGUEL"*, mas isso descreve quais intenções
**precisam** dos campos, não um filtro de gravação. Um lead ainda em `INDEFINIDA`
que diz *"apto de 2 quartos na zona sul"* já entregou dado real, e descartá-lo
contradiz a própria história do card — *"quero que o atendimento aproveite o que eu
falei"*. `INVESTIMENTO` também escreve: os campos de investidor são da TEC-153, mas
região e preço são os mesmos.

### Retentativa

O sweeper reenfileira turno que falhou. Upsert com os mesmos valores é idempotente,
então retentativa é segura sem tratamento extra.

## Medição

### O eval sai quase de graça

Consequência direta de D1: como a extração viaja na chamada que o gate já paga, as
136 chamadas do corpus atual passam a medir extração **sem nenhuma chamada nova**.

Os `evals/corpus/*.yaml` existentes são estendidos com os campos esperados anotados
por turno. Corpus novo não é criado: as 50 conversas já são realistas e já estão
pagas.

### Como a precisão de 85% é definida

Aplicando a lição da TEC-233 (*"um moderador que bloqueia tudo passa em corpus
só-positivo"*), a métrica pune os dois lados:

- Campo anotado como esperado que **não** veio conta erro.
- Campo que veio **sem o lead ter dito** conta erro.

Contar só o primeiro daria 100% a um modelo que acerta o esperado e inventa mais
quatro campos. Contar só o segundo daria 100% a um modelo que nunca extrai nada.

`PISO_DE_PRECISAO_DA_EXTRACAO_PCT = 85` entra em `src/mobia/evals/metricas.py`,
seguindo o padrão de `ALVO_PCT` e `PISO_DE_BLOQUEIO_PCT`.

### A medição do não-repergunta é um proxy

Detectar *"o agente perguntou a região"* em texto livre exigiria heurística de
palavra-chave ou um juiz-modelo pago. Usamos heurística por campo.

**Isto fica declarado no README:** a heurística tem falso negativo — mede uma cota
inferior de reperguntas, não uma garantia. D5 prometeu medição, não garantia, e a
diferença fica escrita em vez de implícita.

### Testes de código

**Unitários:**
- Forma do schema e derivação dos três enums novos (o repositório já testa
  `SCHEMA_DA_RESPOSTA` assim).
- Extração inválida não levanta `RespostaInvalida` e não derruba o turno.
- Cada guarda: preço negativo, `min > max`, magnitude fora de faixa,
  `quartos`/`vagas` fora de faixa, valor de enum inválido.
- `null` não apaga campo preenchido.

**Integração:**
- Quatro campos de uma frase só (Gherkin 1): *"procuro apto de 2 quartos na zona
  sul até 600 mil pra mudar em janeiro"*.
- Campo isolado em resposta direta (Gherkin 3): *"uma só"* → `vagas = 1`.
- Campo já conhecido não é reperguntado (Gherkin 2), pelo estado montado no prompt.
- Sobrescrita pelo mais novo (D4).
- Saída bloqueada ainda grava a extração.
- `FORA_DE_ESCOPO` não grava.

## Fora de escopo

- Normalização monetária de casos difíceis — TEC-146 (ver D2).
- Campos específicos de investidor — TEC-153.
- Cálculo do score — TEC-150.
- Seletor de perguntas em código — ver D5; vizinhos são TEC-148 e TEC-149.
- Histórico de alteração de campo — ver D4; vizinho é TEC-152.

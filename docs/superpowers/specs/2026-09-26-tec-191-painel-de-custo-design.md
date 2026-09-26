# TEC-191 — Exibir o painel de custo de IA

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-191](https://eduardodurieuxlopes.atlassian.net/browse/TEC-191) — épico TEC-189
**Branch:** `feat/tec-191-painel-de-custo`
**Origem:** RF-17, RN-17.4, RNF-06 (SRS v1.0) · fonte na TEC-126 · orçamento sobre a TEC-198 · tela TEC-319

## O problema

O custo de cada resposta do agente já é gravado desde a TEC-126: `message_telemetry` tem `model`, os quatro contadores de token e `cost_usd`, uma linha por mensagem do agente. Falta agregar esses registros, e falta o orçamento: *"o orçamento configurado"* que a card cita não existe em lugar nenhum.

## D1 — O período conta quando o gasto aconteceu

Decisão do Eduardo, 26/09/2026. **Todo número do painel é sobre `message_telemetry.created_at` dentro do período**, e não sobre a coorte do funil (conversas que nasceram no período). O funil pergunta *"o que aconteceu com os leads que chegaram neste mês"*; o painel de custo pergunta *"quanto gastamos neste mês"*. Com a coorte, o custo de um mês fechado continuaria crescendo enquanto as conversas daquele mês falassem, e o alerta de orçamento compararia um valor que ainda muda com um orçamento que já passou.

| indicador | numerador | denominador |
|---|---|---|
| `custoTotalUsd` | soma de `cost_usd` no período | — |
| `custoPorConversaUsd` | o total | conversas distintas com ao menos uma resposta registrada no período |
| `custoPorLeadQualificadoUsd` | o total | leads com `qualificado_em` no período |
| `tokensPorModelo` | soma de cada contador, por `model` | — |

Denominador zero dá média **nula**, e não zero: *"não houve conversa"* não é *"a conversa custou zero"*. O quarto cenário (período vazio) sai com o total em 0, as médias nulas e `tokensPorModelo` vazio, tudo com 200.

**Por lead qualificado é o gasto do período dividido pelos que se qualificaram nele**, e não o custo das conversas desses leads. É custo de aquisição: o dinheiro gasto com quem não qualificou também entra, porque foi gasto para achar quem qualificou. É também o que a RNF-06 mede (*"≤ US$ 0,12 por conversa qualificada"*).

**Os filtros são os do funil** — `de`, `ate`, `canal`, `intencao`, `temperatura`, com a mesma recusa de `corretorId` —, montados pelo mesmo `montar_recorte`. `canal` filtra a conversa da mensagem; `intencao` e `temperatura` filtram pela qualificação **atual** da conversa, como no funil.

## D2 — O painel não recalcula, e diz o que falta

A card diz que o painel *"não recalcula nada, só agrega"*. `cost_usd` é nulo quando o modelo não tinha preço cadastrado (a TEC-126 escolheu nulo em vez de 0,00 para a lacuna aparecer). **A soma ignora os nulos, e a resposta traz `mensagensSemPreco`**, a quantidade de linhas que não entraram: um total que omite custo sem dizer que omitiu parece menor do que foi.

Os tokens entram por modelo como quatro números — `entrada`, `saida`, `cacheLeitura`, `cacheEscrita` —, e não como um total só como o exemplo da seção 6.6 do SRS. Somar leitura de cache com saída misturaria tarifas que diferem em uma ordem de grandeza.

## D3 — O orçamento é mensal, fica na configuração do agente, e é proporcional ao período

Decisão do Eduardo, 26/09/2026. **Um campo novo na configuração da TEC-198: `orcamentoMensalUsd`**, nulo por padrão, editável sem deploy pela mesma rota (`PATCH /api/v1/configuracao/agente`), com a mesma permissão (`CONFIGURAR_AGENTE`) e o mesmo histórico. A migration `0060` acrescenta a coluna `orcamento_mensal_usd numeric(10,2)` a `configuracoes_do_agente`, com CHECK de positivo. Faixa: de 0,01 a 100.000; `null` limpa o orçamento.

**O orçamento do período é o mensal proporcional aos dias**: `mensal × dias / 30`. Com 30 dias, é o mensal inteiro — o terceiro cenário (orçamento de US$ 100, custo de US$ 80) é um período de 30 dias com orçamento mensal de 100. **O alerta acende com `consumido / orçamento do período ≥ 0,80`.**

**O consumo do alerta é o da operação inteira, sem os filtros.** O orçamento é da operação: comparar o custo só do canal web com o orçamento de tudo apagaria o alerta justamente quando alguém filtra para investigar. A resposta traz os dois totais quando há filtro.

Sem orçamento configurado, o bloco `orcamento` sai `null` e não há alerta. Não há padrão inventado.

## D4 — O alvo

`alvoPorLeadQualificadoUsd: 0.12`, a constante da RNF-06, escrita uma vez no código de domínio, e `acimaDoAlvo` (booleano, ou nulo sem lead qualificado). A card diz *"alvo exibido junto ao valor"*; o alvo não é configurável porque é requisito, e a card não pede que seja.

## D5 — A rota

```
GET /api/v1/metricas/custo-ia?de=&ate=&canal=&intencao=&temperatura=
```

Mesma permissão do funil, **`VER_FUNIL`** (ADMIN, GERENTE, LEITURA). A história é da gerente comercial, e o painel não tem dado pessoal — só somas.

## Arquivos

```
alembic/versions/0060_orcamento_de_ia.py
src/mobia/domain/configuracao/{models,vigente,repositorio}.py   # o campo novo
src/mobia/api/routes/configuracao.py                             # o campo na rota
src/mobia/domain/metricas/custo.py                               # a agregação e as contas puras
src/mobia/api/routes/metricas.py                                 # a rota
```

## Testes

- **Unitários** — o orçamento proporcional (30 dias = mensal; 15 dias = metade); o alerta em 80% exato e abaixo; média nula com denominador zero; a validação do orçamento (zero, negativo, acima do teto, nulo aceito).
- **Os quatro cenários, contra banco** — 50 conversas e os quatro indicadores; dez mensagens somando US$ 0,84 dão 0,84; orçamento 100 e custo 80 acendem o alerta; período vazio dá zeros e nulos com 200.
- **As bordas** — mensagem sem preço conta em `mensagensSemPreco` e não no total; o filtro de canal não muda o consumo do orçamento; CORRETOR leva 403.

## Emendas ao SRS

- **RN-17.4, Emenda E-01** — o período pelo instante do gasto, os denominadores, os nulos, os tokens em quatro contadores, `mensagensSemPreco`, o orçamento e o alvo.
- **RN-19.3, Emenda E-03** — `orcamentoMensalUsd` entra na configuração do agente.

## Lacunas declaradas

- **L1 — só o custo gravado em `message_telemetry` entra**, e ele é o das respostas do agente. A moderação, o resumo da conversa, a geração de embeddings e o texto de follow-up fazem chamadas pagas que não têm linha ali. O painel mostra menos do que a conta do provedor cobra, e a diferença não é medida. Fechar isso é gravar telemetria nessas chamadas, o que é outra card.
- **L2 — o mês do orçamento é de 30 dias**, sempre. Um período de 31 dias usa 103% do mensal.
- **L3 — o alerta é só visual e só na consulta.** Ninguém é avisado se ninguém abrir o painel; o alerta por e-mail está fora do escopo (RNF-38).

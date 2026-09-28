# TEC-319 — Exibir o painel de custo de IA com alerta de orçamento

**Card:** [TEC-319](https://eduardodurieuxlopes.atlassian.net/browse/TEC-319) — épico TEC-303
**Branch:** `feat/tec-319-painel-de-custo-de-ia`
**Relaciona-se a:** TEC-191 (o endpoint, já implementado), TEC-337 (configuração do agente, ainda não existe no frontend)

## O que já existe quando a card começa

O backend inteiro (TEC-191): `GET /api/v1/metricas/custo-ia` (`metricas.py::custo_de_ia`) já devolve `custoTotalUsd`, `custoPorConversaUsd`, `custoPorLeadQualificadoUsd`, `tokensPorModelo`, `conversas`, `leadsQualificados`, `mensagensSemPreco`, `alvoPorLeadQualificadoUsd`, `acimaDoAlvo` e `orcamento` (ou `null`), com a mesma permissão (`VER_FUNIL`) e o mesmo `montar_recorte` do funil. **Esta card é só frontend**: nenhuma linha de backend muda.

Nada no frontend consome essa rota hoje — busquei `custo-ia`, `custoTotalUsd`, `orcamentoMensalUsd` em `frontend/src` inteiro e não há nada.

## Decisão do Eduardo: o link "configurar orçamento" aponta para `/admin`

A card pede um link para configurar o orçamento quando não há nenhum configurado. A tela que teria esse campo (`orcamentoMensalUsd`) é a "Configuração do agente" — TEC-337, que **ainda não existe no frontend**: `app/(painel)/admin/page.tsx:22` lista a seção sem `href`, só o texto "ainda não disponível". Perguntado ao Eduardo, a decisão foi: o link aponta para `/admin` (a listagem, onde a seção já aparece nomeada) — sem inventar uma rota nova fora do escopo desta card. Quando a TEC-337 entrar, o link passa a levar direto ao formulário sem precisar mexer aqui.

## D1 — Rota nova (`/custo-ia`), não seção dentro do funil

O funil e o custo de IA usam o MESMO recorte de período/canal/intenção/temperatura na URL, mas com semânticas diferentes por baixo: o funil é sobre a COORTE (quem chegou no período), e o custo é sobre QUANDO O GASTO ACONTECEU (docstring do módulo `custo.py`, D1 daquele desenho). Colocar os dois na mesma página misturaria dois `<Filtros>` que parecem idênticos mas filtram coisas diferentes por trás — confuso e sem necessidade. Uma rota nova, `/custo-ia`, com o mesmo componente `<Filtros>` (ele é genérico, não tem nada específico do funil) e o mesmo padrão de guarda de página (`exigirPermissao`, `VER_FUNIL`) resolve isso sem duplicar nada.

Menu novo em `lib/navegacao.ts`: "Custo de IA" → `/custo-ia`, visível para quem tem `VER_FUNIL` (mesma permissão da rota).

## D2 — `custoTotalUsd` nunca é "Ainda não medido"; as duas médias podem ser "sem dados no período"

`custo.py::custo_do_periodo` sempre devolve `total_usd` como `Decimal` (via `COALESCE(SUM(...), 0)`) — nunca `None`. Um período sem gasto mostra **US$ 0,00 de verdade**, não `AindaNaoMedido`: é exatamente o quarto cenário do Gherkin.

`custoPorConversaUsd`/`custoPorLeadQualificadoUsd` (`custo.py::media`) viram `null` com denominador zero, e o comentário do próprio backend é a razão: **"nula com denominador zero: 'não houve conversa' não é 'custou zero'"**. A leitura mais estrita do Gherkin ("os indicadores mostram US\$ 0,00") entraria em conflito com essa regra — a mesma tensão entre prosa solta do Gherkin e a implementação já vista na TEC-190/315/367. Sigo a regra que o próprio backend documenta: as duas médias usam `estadoDe`/`Vazio` ("sem dados no período") quando nulas, e nunca "Ainda não medido" (`disponivel` é sempre `true` aqui — não há indicador sem fonte neste painel, diferente do funil).

## D3 — Alerta é o mesmo molde de `AvisoDeCoorteIncompleta`

`orcamento.alerta` já vem calculado do backend (`>= 80%`, `custo.py::LIMIAR_DO_ALERTA` e `custo.py::avaliar_orcamento`). O componente só decide SE mostra (quando `alerta === true`) e COMO: ícone `⚠` + texto curto sempre visível, no molde de `Funil.tsx::AvisoDeCoorteIncompleta` — não um tooltip que dependeria de mouse.

Sem orçamento (`orcamento === null`), nenhum alerta aparece e o texto convida a configurar, com o link da decisão acima.

## D4 — `alvoPorLeadQualificadoUsd`, não "por conversa qualificada"

A card escreve a referência como "alvo: US\$ 0,12 por conversa qualificada", mas o campo que o backend expõe (RNF-06, `custo.py::ALVO_POR_LEAD_QUALIFICADO_USD`) é **por LEAD qualificado**, ao lado de `custoPorLeadQualificadoUsd` — não existe no contrato um alvo "por conversa". Sigo o contrato implementado (mesma decisão de seguir o código quando a prosa da card diverge, já usada em cards anteriores deste painel) e mostro o alvo ao lado do custo por lead qualificado, com `acimaDoAlvo` como indicação textual ("acima do alvo" / "dentro do alvo").

## Testes

- **`lib/custo.test.ts`** (novo): `buscarCusto` manda o filtro certo e lê o erro do FastAPI, no molde de `metricas.test.ts`.
- **`components/CustoDeIA.test.tsx`** (novo): custo total sempre numérico (nunca "Ainda não medido"); médias nulas mostram "sem dados no período"; alerta aparece só com `orcamento.alerta`; sem orçamento, link para `/admin` e nenhum alerta; tokens por modelo renderizam uma linha por modelo.
- **`app/(painel)/custo-ia/page.test.tsx`** (novo): os quatro cenários do Gherkin, no molde de `page.test.tsx` do funil (duble do `fetch`, não do módulo).

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `next dev` e API locais, sessão GERENTE. `message_telemetry`, `lead_qualification` e a configuração de orçamento semeados diretamente no banco.

| passo | resultado |
| --- | --- |
| `/custo-ia?de=2026-09-01&ate=2026-09-30`, orçamento US$100 | custo total US$0,84; custo por conversa e por lead qualificado corretos; "acima do alvo" ao lado do custo por lead; tabela de tokens por modelo; sem alerta (bem abaixo de 80%) |
| Orçamento reduzido para US$1,00, mesmo período | alerta "⚠ Orçamento em 84,5% do período (US$ 0,84 de US$ 1,00)" |
| Orçamento removido (`orcamento_mensal_usd = None`) | nenhum alerta; link "Configurar orçamento" → `/admin` |
| Período sem nenhuma conversa (`2020-01-01` a `2020-01-31`) | custo total "US$ 0,00"; custo por conversa "sem dados no período"; nenhum "Ainda não medido" na tela |

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Exibir o custo total do período | `CustoDeIA.test.tsx` + `page.test.tsx` |
| Alertar ao atingir 80% do orçamento | `CustoDeIA.test.tsx` (`orcamento.alerta`) |
| Sem orçamento configurado | `CustoDeIA.test.tsx` + `page.test.tsx` (link para `/admin`) |
| Período sem conversas | `CustoDeIA.test.tsx` (D2) |

## Lacunas declaradas

- **L1 — O link de configuração aponta para `/admin`, não para um formulário.** Decisão do Eduardo, registrada acima; a TEC-337 ainda não existe.
- **L2 — Sem teste de integração ponta a ponta com dado de custo real.** Verificado no navegador com dados semeados diretamente no banco (`message_telemetry`), documentado abaixo.

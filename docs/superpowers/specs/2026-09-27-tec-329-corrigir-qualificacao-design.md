# TEC-329 — Corrigir a qualificação do lead e ver o score recalculado

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-329](https://eduardodurieuxlopes.atlassian.net/browse/TEC-329) — épico TEC-304
**Branch:** `feat/tec-329-corrigir-qualificacao`
**Depende de:** TEC-194 (`PATCH /leads/{leadId}/qualificacao`), TEC-323 (o detalhe), TEC-311 (o aviso de alteração não salva), TEC-302 (o `/bff/*`)

## O que existe quando a card começa

`PATCH /api/v1/leads/{leadId}/qualificacao` existe desde a TEC-194 (Emenda E-01 da RN-18.3). Ele exige `ATENDER_LEAD` e aplica o recorte do detalhe. O pedido é parcial: campo ausente não muda, e `null` limpa. O score é recalculado na mesma transação, com a causa `EDICAO_MANUAL` e o autor, e cada campo alterado grava um `QUALIFICACAO_ALTERADA`. A resposta é `{alterados, scoreAnterior, scoreAtual, temperatura}` e não traz a ficha: quem quer a ficha nova relê o detalhe.

Os editáveis são estes, e a intenção fica de fora de propósito:
- faixa de preço (mínimo e máximo, em centavos);
- `regiao`;
- `tipoImovel`, `urgencia` e `formaPagamento`, que são enums;
- `quartos` e `vagas`, de 0 a 50;
- `temImovelParaVender`.

**Três coisas que a card pressupõe e que não existem:**

1. **a região não é vocabulário fechado.** A card a cita como exemplo de lista de seleção, mas a TEC-145 e a TEC-241 decidiram que `regiao` é conjunto aberto: tem forma canônica e não tem taxonomia de bairros;
2. **nenhuma rota expõe os vocabulários.** A tela já tem os rótulos escritos à mão em `lib/detalhe.ts`;
3. **o 422 tem duas formas.** Uma é a lista de erros do pydantic, com `loc: ["body", "<campo>"]`. A outra é a string `"faixa_invertida"`, a regra de domínio que confere o pedido contra o que já estava gravado.

## D1 — A região é texto, e o backend a grava na forma canônica

A tela não inventa taxonomia que o backend decidiu não ter. **A região é um campo de texto.** Os três enums (`tipoImovel`, `urgencia`, `formaPagamento`) são listas de seleção, e o booleano é Sim / Não / Não informado.

**O `PATCH` passa a gravar `regiao` por `normalizar_regiao`**, que é o que a extração do agente já faz. Sem isso, a correção manual seria a única porta que grava região fora da forma canônica. O filtro estruturado da TEC-158 compara `regiao` por igualdade, e "Perto do Campeche" digitado pelo corretor nunca casaria com o `campeche` do catálogo. Texto que se normaliza para vazio vira `null`.

Vira a **Emenda E-02 à RN-18.3**.

## D2 — O vocabulário do backend é o da tela, e um teste prende isso

As opções das listas saem dos mapas de rótulo de `lib/detalhe.ts`, que passam a ser exportados. **Um teste unitário do Python lê esses mapas e os compara com os enums de `agente/schemas.py`.** Um valor novo no backend sem rótulo na tela, ou um valor que só a tela tem, reprova antes de alguém descobrir pelo 422.

Uma rota de vocabulário seria a outra saída. Ela custaria uma chamada a mais por abertura do detalhe para servir três listas que mudam uma vez por trimestre, e a divergência que ela evita é a mesma que o teste pega.

**O `TipoImovel` do catálogo não serve**: ele tem `COBERTURA`, que o do agente não tem, e o `PATCH` valida contra o do agente.

## D3 — O formulário

`components/EdicaoDaQualificacao.tsx`, `'use client'`, fica dentro da seção Qualificação e embaixo da lista. Quem tem `ATENDER_LEAD` vê **Editar qualificação**. O clique abre o formulário com os valores atuais.

- **A faixa de preço é digitada em reais inteiros** e vai em centavos.
- **Só o que mudou vai no `PATCH`**, e é o que mantém a trilha fiel: campo reenviado com o mesmo valor não conta, mas o corpo também não o carrega. Campo esvaziado vai como `null`. Formulário sem mudança fecha sem chamar a API.
- **Sujo registra `registrarAlteracaoNaoSalva('qualificacao', true)`** (D4 da TEC-311). Salvar, cancelar ou desmontar desfaz o registro.
- **Sem qualificação** (o agente ainda não extraiu nada), o formulário abre vazio. O backend cria a linha.
- **Conversa encerrada** não mostra o botão. A seção diz que a qualificação não se edita mais. É o 409 `conversa_encerrada` da TEC-194, dito antes do clique.

## D4 — Depois de salvar: o score anterior e o novo lado a lado

Com o 200, a seção mostra **"Score 47 → 62"** a partir de `scoreAnterior` e `scoreAtual`, com `—` para nulo. O formulário fecha, e a tela recarrega do servidor com `router.refresh()`, como na D4 da TEC-327. A lista de campos e o score do cabeçalho passam a vir do detalhe relido, e nada é montado localmente. A linha do antes e depois é estado do componente, então sobrevive ao `refresh` e some ao sair da tela.

## D5 — Recusas

| resposta | onde aparece | texto |
| --- | --- | --- |
| 422 do pydantic | ao lado do campo de `loc[1]` | tradução pelo `type` (`less_than_equal`, `greater_than_equal`, `string_too_long`, `enum`, `int_parsing`); o `msg` do backend quando o tipo é outro |
| 422 `faixa_invertida` | ao lado da faixa de preço | O valor mínimo não pode passar do máximo. |
| 409 `conversa_encerrada` | topo do formulário | A conversa foi encerrada: a qualificação não pode mais ser editada. |
| 401 / 403 / 404 / rede | topo do formulário | como na TEC-327 |

**Em toda recusa o formulário continua aberto com o que foi digitado, e o score continua o anterior**: não há `refresh`.

A card pede que "a mensagem do backend" apareça ao lado do campo. O que aparece é a tradução dela: o `msg` do pydantic é inglês e fala de tipo Python, e quem lê é o corretor.

## D6 — O proxy libera o `PATCH`

`ROTAS_PERMITIDAS` ganha `PATCH api/v1/leads/*/qualificacao`, e o Route Handler já exporta `PATCH`. A regra de `Origin` recusa mutação de outra origem.

## Fora do escopo

- **A intenção** não se edita (Emenda E-01 da RN-18.3).
- **Os campos de investidor** não estão entre os editáveis da TEC-194.
- **"Recusou informar" não se limpa** quando o corretor preenche o campo recusado (L7 da TEC-194). A tela pode mostrar o valor e a recusa ao mesmo tempo, e isso é decisão de produto em aberto.
- **Forçar recálculo** (`POST .../score/recalcular`) é outra rota, e a card não a pede.

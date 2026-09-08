# TEC-265 — Ligar a busca híbrida ao turno do agente

**Status:** desenhado em 2026-09-08 na branch `feat/tec-265-busca-no-turno`.

**Card:** [TEC-265](https://eduardodurieuxlopes.atlassian.net/browse/TEC-265) — Must (MoSCoW), prioridade Highest. Origem: RF-09 (RN-09.2 e RN-09.4), RF-10, RNF-26 e RT-01. Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155).

**Bloqueia [TEC-161](https://eduardodurieuxlopes.atlassian.net/browse/TEC-161) e [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162)** — as duas partem de "os candidatos retornados pela busca" e nenhuma entrega o elo. A card nasceu desse achado.

## Objetivo

O turno passa a obter candidatos do catálogo, por tool call que o agente pede. Depois desta card, a busca da TEC-158 deixa de ser código que só a rota HTTP chama, e a TEC-161 passa a ter contra o que validar.

## O estado de hoje, medido

- `domain/catalogo/busca.py::buscar` tem dois chamadores: `api/routes/imoveis.py` e os testes. `executar_turno` não a conhece.
- O agente não tem tool call nenhum. `classificador._chamar` faz uma requisição e **recusa qualquer `stop_reason != "end_turn"`**, com o comentário: *"end_turn e a unica parada normal em qualquer chamada deste modulo: nenhuma declara tools, nenhuma configura stop_sequence."*
- A saída é forçada por structured outputs (`output_config={"format": {"type": "json_schema", ...}}`), não por prompt.
- O modelo do agente é `claude-sonnet-5` (`config.py`), trocado de Opus por custo.
- A margem do orçamento do prompt é de **6,2 tokens** (líquido 648,8 contra teto fixo de 655), medida em 2026-09-08 por `pytest -k margem_do_orcamento -s`.

## Decisões

### D1 — Tool use de verdade, porque a RNF-26 é literal

A alternativa recusada era pré-busca determinística: o turno chamaria `buscar` sempre que a qualificação tivesse critérios e injetaria os candidatos no contexto. Ela é mais barata (nenhum round-trip extra) e não inventa topologia.

Foi recusada porque a RNF-26 diz que *"dado factual só sai de tool call validada"* e essa frase é a mitigação declarada do RT-01 — risco de probabilidade alta e impacto crítico. Lida como intenção, a pré-busca a satisfaria e o SRS precisaria de emenda; lida como requisito, ela não satisfaz. **A leitura literal foi confirmada como decisão de produto em 2026-09-08**, e é por isso que a alternativa mais barata não está aqui.

Consequência declarada: turnos que buscam passam a custar duas chamadas ao modelo, e o modelo pode decidir não chamar a ferramenta (ver a lacuna 3).

### D2 — O laço vive no `_chamar`, e `tool_use` deixa de ser parada inválida

`_chamar` é o ponto único por onde toda chamada do módulo passa: ele mede latência, aplica o `cache_control` do prefixo e decide o que é parada aproveitável. A política passa a distinguir três casos em vez de dois:

- `end_turn` — resposta, como hoje;
- `tool_use` — esperado, entra no laço;
- `max_tokens` e `refusal` — continuam inaproveitáveis, pelo motivo que a docstring de `classificar` já registra (nenhum dos dois produz JSON que valha decodificar).

O comentário que diz que nenhuma chamada declara tools **sai junto com a mudança**: ele passaria a mentir, e este repo trata comentário desatualizado como defeito.

As alternativas recusadas foram o `tool_runner` do SDK e um subagente no molde do `desambiguar`. O `tool_runner` é beta e esconde exatamente o que o `_chamar` controla à mão — medição de latência, telemetria por chamada, disciplina de `stop_reason` e a asserção de prefixo cacheável. O subagente pagaria duas chamadas em **todo** turno que busca, mais a dobra da desambiguação quando ela ocorre, e faria a resposta ser escrita por quem não chamou a ferramenta.

### D3 — A busca entra como porta, não como sessão

`classificar` recebe um callable, no molde do `embedador` que `indexar_catalogo` já recebe pelo `ctx`. O classificador não ganha `AsyncSession` nem importa `busca.py`; quem monta a sessão é `executar_turno`, que já tem `session_factory`.

Duas razões: o domínio do agente não passa a fazer I/O de banco, e o teste unitário do laço continua com falso, sem container.

**A porta é também quem traduz.** O input do tool call chega com `tipo` e `operacao` como string livre (D5); é a porta que monta o `FiltroDeBusca`, e portanto é nela que a D6 acontece. O `classificar` não conhece `FiltroDeBusca`, e `busca.py` não conhece o formato do tool call — a tradução tem um lugar só, e ele é nomeável nos testes.

### D4 — Teto de um round-trip por turno, e `tool_choice` em `auto`

Um segundo `tool_use` depois do `tool_result` não é atendido: o turno segue pelo caminho conservador da D9. Sem esse teto, quantas chamadas o turno faz é decisão do modelo, e a RNF-02 (p95 ≤ 6 s) e a RNF-06 (US$ 0,12 por conversa qualificada) ficam à mercê dela.

`tool_choice` fica em `auto`. O `claude-sonnet-5` aceita forçado — a proibição de `any`/`tool` é dos modelos Fable 5.1 e Mythos 5.1 —, mas forçar gastaria uma busca em todo turno, inclusive nos que não pedem imóvel.

### D5 — A ferramenta leva o filtro completo, com `tipo` e `operacao` como string livre

Três variantes foram medidas em 2026-09-08, no mesmo proxy `len/4` que o teste do orçamento usa:

| Variante | Custo | Líquido | Reserva | Preço por turno |
|---|---|---|---|---|
| V1 — filtro completo com `enum` | 161,2 | 810,0 | 1035,0 | 155,0 de 12000 (1,29%) |
| **V2 — filtro completo, `tipo`/`operacao` como string** | **121,5** | **770,3** | **995,3** | **115,3 de 12000 (0,96%)** |
| V3 — só `consulta_texto`, filtro vindo do estado | 73,8 | 722,5 | 947,5 | 67,5 de 12000 (0,56%) |

A coluna "líquido" é a subcontagem que o teste imprime; os números escritos à mão no código são os inteiros acima dela.

**A V2 é a base, e a D11 acrescenta um `enum` a ela.** Com `operacao` como `enum` de dois valores e os nomes de campo finais (`preco_max_centavos`, não `preco_max`), a ferramenta custa **131,2**: líquido **780,0**, teto **780**, reserva **1005**, preço de **125,0 de 12000 — 1,04% do contexto** (ver D10 e D11). Os 7,5 tokens do `enum` compram o que a D11 explica.

**`preco_min_centavos` fica fora do schema**, embora `FiltroDeBusca` o aceite: o orçamento do lead entra na RN-09.6 como *teto* (a aderência é medida contra ele), e nenhuma regra da RF-09 pede piso. Lacuna declarada: "quero acima de 500 mil" não é expressável por esta ferramenta.

A **V3 é a mais barata e tem defeito**: no instante do tool call, os critérios que o lead disse **neste turno** ainda não estão persistidos — a extração volta no mesmo JSON final da resposta. A V3 buscaria com o estado do turno anterior, e "quero três quartos" só valeria no turno seguinte.

A **V1 paga ~40 tokens por validação que já existe**: `busca.py` dobra região com `dobrar`, a tabela de exceção da TEC-262 já mapeia o vocabulário de tipo, e `FiltroDeBusca` valida. O precedente é exato — a TEC-257 escolheu lista de strings livre em vez de enum dos nove campos porque o enum custava +56 contra +18,5.

### D6 — Valor que o domínio não reconhece derruba a dimensão, não a busca

`tipo: "LOFT"` tira a dimensão de tipo do filtro e registra evento; não levanta e não devolve vazio.

O sentido importa: filtro que o domínio não sabe ler **não pode estreitar** a busca em silêncio. Alargar produz candidatos que alguém vê e um evento que alguém conta; estreitar produz zero resultados que parecem catálogo vazio.

### D7 — O `tool_result` leva fato sobre o imóvel, e não diagnóstico nosso

A primeira metade da RN-09.4 já está pronta desde a TEC-158: `Candidato` carrega `imovel_id` e `preco_centavos` — o preço da **operação buscada**, e não outra coluna.

Vão no `tool_result`: `imovel_id`, `codigo`, `titulo`, `bairro`, `preco_centavos`, `quartos`, `vagas`, `area_util_m2`, e o `total_candidatos` do resultado. Ficam fora `score` e `tem_vetor`: são diagnóstico do nosso lado, e mandar `score` convida o modelo a dizer "97% de compatibilidade" ao lead — dado inventado com aparência de número.

`total_candidatos` entra porque a RN-09.2 quer que o agente saiba que está vendo 10 de 40.

O preço vai em **centavos inteiros**, não formatado. Formatar é apresentação (TEC-162), e inteiro é o que a TEC-161 vai comparar. **Consequência declarada:** o modelo escreve "R$ 749.000" em texto ao lead, então a validação da TEC-161 terá de normalizar formato antes de comparar. A dificuldade é dela, mas o formato decidido aqui é o que a define.

### D8 — Os candidatos saem do laço junto com a resposta

O que a ferramenta devolveu fica disponível no retorno de `classificar`, e não só dentro do `_chamar`.

Isso existe para a TEC-161: se os candidatos morressem no laço, ela precisaria refazer a busca para validar a resposta — e validar contra uma segunda busca é validar contra outra coisa, não contra o que o modelo viu.

### D9 — Falha de busca vira `is_error: true`, não exceção

| Situação | O que acontece |
|---|---|
| Provedor de embedding caído | `busca.py` já degrada (`consulta_vetorizada: False`, ordena por aderência de preço). O turno não vê erro |
| Zero candidatos | `tool_result` com lista vazia e `total_candidatos: 0`. Não é erro; relaxar é a TEC-160 |
| `consulta_texto` ausente | `buscar` recebe `None`, não vetoriza nada e ordena por aderência de preço. Mesmo caminho da degradação, sem erro: o filtro estruturado sozinho ainda é uma busca válida |
| Busca levanta (banco fora) | `tool_result` com `is_error: true`; o modelo responde sem imóvel e o turno não cai |
| Segundo `tool_use` | Recusado (D4); o turno segue pelo `_entregar_texto_fixo` que já existe, com evento próprio |

Exceção aqui mataria o turno inteiro por causa de uma busca, e a regra que o `indexar_catalogo.py` documenta é a oposta: falha de busca não bloqueia o atendimento.

### D10 — O teto do orçamento sobe, com o preço escrito

`test_a_margem_do_orcamento_do_prompt_e_deliberada` passa a ter uma quinta parcela em `_decomposicao` — a definição da ferramenta, que é enviada e nunca contada, como o schema de saída já é. O teto vai de 655 para **780** (líquido medido: 780,0) e `contexto_headroom_de_tokens` de 880 para **1005**. Os dois números só ficam finais depois da lacuna 1: se `strict` obrigar todas as propriedades a entrarem em `required`, o schema cresce e a medição refaz a conta.

A pergunta que a docstring manda fazer foi feita antes: **o que sai do prompt para isso entrar?** A resposta honesta é que não há corte de ~115 tokens que não toque algo medido — o `SISTEMA_DO_AGENTE` são 298,8 tokens de cláusulas que o gate mede uma por uma, e o schema compilado são 372,8 de campos que a extração usa. O que **foi** cortado é dentro da própria ferramenta: a V2 em vez da V1 economizou ~40 tokens trocando enum por string livre, e é o mesmo movimento que a TEC-257 fez.

Preço desta subida, no formato das três anteriores: **125 tokens a menos de literais e resumo por turno, de 12000 — 1,04% do contexto**. Fica entre a primeira (3,3%) e as duas últimas (0,4% e 0,25%), e é a segunda maior da história do projeto.

### D11 — `operacao` é `enum` no schema, porque os dois vocabulários discordam

O agente fala `COMPRA` e o catálogo fala `VENDA`. `Intencao` (`domain/agente/schemas.py`) tem `COMPRA`, `ALUGUEL`, `INVESTIMENTO`, `VENDER_IMOVEL`; `Operacao` (`domain/catalogo/enums.py`) tem `VENDA`, `ALUGUEL`, `AMBOS`. O prompt inteiro do agente é escrito no primeiro vocabulário, então `operacao: "COMPRA"` no tool call não é hipótese: é o valor que o modelo tende a produzir, e `Operacao("COMPRA")` levanta `ValueError`.

Duas saídas foram medidas. Tabela de alias na porta (`COMPRA` e `INVESTIMENTO` → `VENDA`) custa 0 token de prompt e é código que ninguém vê falhar quando o modelo inventa um quinto valor. `enum` de dois valores no schema custa **+7,5 tokens** e faz o próprio modelo traduzir, com `strict: true` garantindo o valor.

O `enum` ganha, e é a escolha oposta à da D5 para `tipo` — deliberadamente. `tipo` é dimensão **descartável**: valor que o domínio não lê sai do filtro (D6) e a busca acontece. `operacao` não é: ela escolhe a coluna de preço, `FiltroDeBusca` recusa default para ela por decisão da TEC-158 (D2 daquele desenho), e sem ela não há busca nenhuma. Pagar 7,5 tokens para a única dimensão que não pode ser descartada nunca chegar errada é barato.

**A porta ainda trata valor não reconhecido em `operacao` como `is_error: true`**, e isso não é redundância: a garantia do `enum` depende de `strict`, que a lacuna 1 ainda não verificou. Se `strict` sair, o `enum` vira sugestão e a porta é o que sobra.

Este é o mesmo formato de problema que a TEC-262 resolveu para `tipo`, e a D1 dela recusou unir os enums. A D11 não os une: ela põe a tradução no lugar mais barato onde ela é verificável.

**Nomes de evento** ficam para o plano, e seguem os prefixos que já existem no log estruturado (`catalogo.` para o que é do catálogo, `message.` para o que é do turno). O desenho fixa que existe evento nos três pontos — dimensão derrubada (D6), busca falhando (D9) e segundo `tool_use` recusado (D4) —, não como cada um se chama.

## Fluxo

1. `executar_turno` monta a porta de busca sobre a sua `session_factory` e a passa ao `classificar`.
2. `classificar` chama o modelo com `tools=[buscar_imoveis]`, o mesmo `output_config` de hoje e `tool_choice: auto`.
3. Se veio `end_turn`, nada mudou: o JSON é decodificado como hoje e o turno segue.
4. Se veio `tool_use`, a porta executa `buscar` com o filtro do tool call (D5, D6), o `tool_result` é montado (D7) e o modelo é chamado de novo.
5. A segunda resposta é `end_turn` na expectativa; um segundo `tool_use` cai na D4.
6. `classificar` devolve a resposta e os candidatos (D8). A moderação e o `outbound.send` seguem como hoje.

## Testes

Unitários, com falso de cliente e sem rede:

- o laço feliz: `tool_use`, porta chamada com o filtro do tool call, segunda chamada, JSON final;
- o segundo `tool_use` não é atendido e o turno vai para o texto fixo;
- a porta levantando produz `is_error: true` e resposta sem imóvel;
- `tipo` que o domínio não lê derruba só a dimensão, e a busca acontece;
- `score` e `tem_vetor` **não** aparecem no `tool_result`.

Integração, com catálogo real: turno completo com candidatos chegando à geração; turno sem pedido de imóvel não apresentando imóvel.

E o gate de orçamento é entrega, não efeito colateral: a quinta parcela entra em `_decomposicao`, o teto sobe para ~770 com a quarta linha do histórico na docstring, e o preço de 0,96% entra no comentário de `contexto_headroom_de_tokens`.

## Emendas ao SRS

**Nenhuma.** A leitura literal da RNF-26 é a que a D1 implementa, então a regra não muda de sentido. Se a decisão de produto tivesse sido a outra, a pré-busca exigiria emenda à RNF-26 e à linha do RT-01 — e é por isso que a pergunta foi feita antes do desenho, não durante.

## Lacunas declaradas

1. **`strict: true` com `required` parcial não foi verificado contra a API.** A referência exige `additionalProperties: false` e `required`, e não diz se `strict` obriga todas as propriedades a entrarem em `required`. Se obrigar, o schema cresce ou `strict` sai — e a medição da D5 muda. O plano verifica antes de fixar o número.
2. **A latência do turno com duas chamadas não foi medida.** A RNF-02 pede p95 ≤ 6 s ponta a ponta, o `job_timeout` do worker é 240 s, e o comentário do `workers/main.py` já registra que um turno com dobra "passava de". Não existe medição de latência de turno hoje — a instrumentação é a TEC-211.
3. **O modelo pode não chamar a ferramenta.** Com `tool_choice: auto` (D4), um turno em que o lead pede imóvel e o modelo responde sem buscar é possível, e esta card não põe guarda contra isso. A TEC-161 **não** cobre a lacuna: ela valida imóvel citado fora da lista, não ausência de busca. Fica registrada como risco desta decisão.
4. **`preco_min_centavos` não é expressável pela ferramenta** (D5). O lead que diz "acima de 500 mil" não tem como estreitar por baixo; a RF-09 não pede piso, e `FiltroDeBusca` aceita um se algum dia pedirem.
5. **O custo por conversa não foi recontado.** A RNF-06 dá US$ 0,12 por conversa qualificada. O prefixo cacheado cobre `tools` e `system` (a ordem de renderização é `tools` → `system` → `messages`, e o breakpoint já está no `system`), mas os candidatos entram em `messages` e não são cacheados. O delta não foi medido.

## Fora de escopo

- A validação anti-alucinação e a regeneração — [TEC-161](https://eduardodurieuxlopes.atlassian.net/browse/TEC-161).
- A ficha estruturada por canal e o teto de 3 imóveis por turno na apresentação — [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162).
- O registro da recomendação e a realimentação pela reação — [TEC-163](https://eduardodurieuxlopes.atlassian.net/browse/TEC-163).
- O SLA de 400 ms da busca — [TEC-159](https://eduardodurieuxlopes.atlassian.net/browse/TEC-159).
- O relaxamento automático quando não há resultado — [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160).
- A suíte de avaliação de alucinação no CI, que já existe desde a TEC-210.

# TEC-198 — Configurar o agente sem deploy

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-198](https://eduardodurieuxlopes.atlassian.net/browse/TEC-198) — épico TEC-189
**Branch:** `feat/tec-198-configurar-o-agente`
**Origem:** RF-19, RN-19.3, RN-19.5, CA-19.1 (SRS v1.0) · TEC-150, TEC-183, TEC-206 · tela TEC-337

## O problema

Os cinco itens que a card pede configuráveis são hoje constantes de módulo, e três deles o próprio código já marcava como lacuna desta card:

| item | onde mora | quem lê |
|---|---|---|
| nome do assistente | não existe — o prompt diz *"o assistente virtual de uma imobiliaria"* | `classificador.SISTEMA_DO_AGENTE` |
| tom de voz | *"em tom de conversa"*, dentro do mesmo prompt | idem |
| limite de perguntas | `qualificacao.TETO_DE_PERGUNTAS = 8` | `excedeu_o_teto`, duas vezes no turno |
| pesos do score | `_PONTOS_POR_URGENCIA`, `_PONTOS_POR_CAPACIDADE`, `PONTOS_POR_CAMPO_OBRIGATORIO`… em `score.py` — *"Constantes de modulo, e nao configuracao (…) pertence ao epico de configuracao"* | `calcular_score`, via `registrar_recalculo` |
| cadência de follow-up | `followup/cadencia.py::CADENCIA` | `tentativa_devida`, `esta_dormente`, o corte `INTERVALO_MINIMO` e o `CASE` SQL da varredura |

## D1 — Uma tabela de versões, só de acréscimo

```
configuracoes_do_agente (
  id                 uuid PK,
  nome_do_assistente varchar(30) NULL,
  tom                varchar(16) NOT NULL,
  teto_de_perguntas  smallint NOT NULL,
  peso_completude, peso_urgencia, peso_catalogo,
  peso_engajamento, peso_capacidade     smallint NOT NULL,
  cadencia           jsonb NOT NULL,       -- {"QUENTE": [2, 24, 72, 168], ...} em horas
  autor              varchar(120) NOT NULL,
  criado_em          timestamptz NOT NULL DEFAULT clock_timestamp()
)
```

**Cada alteração é uma linha nova com a configuração inteira; a vigente é a mais recente.** Sem linha nenhuma, vale o padrão — as constantes de hoje, que continuam no código como `PADRAO`. O quarto cenário (*"constam autor, valor anterior, valor novo e timestamp"*) sai da comparação de cada versão com a anterior, sem uma segunda tabela de diffs que pudesse divergir da primeira.

**Nada de cache.** Cada leitor carrega a vigente na hora em que precisa — uma consulta por `criado_em DESC LIMIT 1` sobre uma tabela de poucas linhas. É o que faz a CA-19.1 (*"sem reiniciar a aplicação"*) ser verdade sem invalidação: não há o que invalidar. **Uma leitura por turno**, e não uma por uso: o turno lê uma vez em `montar_contexto` e usa o mesmo retrato até o fim, para um turno não pontuar com um peso e contar perguntas com outro limite.

**A trilha de auditoria também registra**, com uma `Acao.CONFIGURACAO_ALTERADA` nova e um evento por campo alterado, sem o valor. A tabela guarda os valores porque eles não são dado pessoal; a trilha diz quem mudou o quê, e é o que a RNF-18 lê. A migration (`0058`) recria o CHECK de `acao`, como a `0056` e a `0057` fizeram.

## D2 — Os limites

| campo | faixa | por quê |
|---|---|---|
| `nome_do_assistente` | 1–30 caracteres, uma linha só, ou nulo | vai para dentro do prompt (D6) |
| `tom` | `CORDIAL` · `FORMAL` · `DESCONTRAIDO` | vocabulário fechado, decisão do Eduardo (26/09) |
| `teto_de_perguntas` | 1–20 | a card recusa zero; acima de 20 o SDR vira interrogatório |
| cada peso | 0–50 | a card recusa negativo |
| soma dos pesos | 1–100 | os cortes de temperatura (70 e 40) supõem uma escala de 0 a ~100 |
| cadência | a mesma **quantidade** de tentativas por temperatura (4, 3, 2), cada intervalo entre 1 h e 90 dias, estritamente crescente | ver D5 |

Valor fora da faixa é **422** com a regra violada escrita, e **nenhuma linha é gravada** — o terceiro cenário (*"o valor anterior permanece"*) é consequência de a vigente ser a última linha.

## D3 — O peso é o teto do fator, e as notas internas escalam

Decisão do Eduardo, 26/09/2026. Cada fator tem um peso, que é o máximo que ele pode dar; os pontos internos escalam na proporção. Os pesos padrão são os tetos de hoje, então **com a configuração padrão o score é idêntico ao atual**:

| fator | teto padrão | escala |
|---|---|---|
| completude | 20 (5 por campo × 4) | `pontos × peso / 20` |
| urgência | 25 (IMEDIATA) | IMEDIATA 25, ATÉ 3 MESES 15, ATÉ 6 MESES 8 → × `peso / 25` |
| catálogo | 20 | × `peso / 20` |
| engajamento | 15 | × `peso / 15` |
| capacidade | 15 (à vista) | × `peso / 15` |

Arredondamento para o inteiro mais próximo, fator a fator. Com peso de urgência 30: IMEDIATA 30, ATÉ 3 MESES 18, ATÉ 6 MESES 10. A penalidade de não comparecimento (TEC-172) não é peso de fator e fica fora.

**A trilha de score não muda de forma.** Ela já guarda a contribuição de cada fator, e com peso novo a contribuição é a nova — o recálculo seguinte registra a mudança com as causas derivadas do diff, como qualquer outro.

## D4 — O limite de perguntas

`excedeu_o_teto` passa a receber o teto. O turno usa o da configuração lida em `montar_contexto`. O texto que o lead recebe ao estourar o limite não cita o número e não muda.

## D5 — A cadência: os intervalos mudam, a quantidade não

**Só os intervalos são configuráveis.** A quantidade de tentativas por temperatura aparece em três lugares que precisam concordar: `tentativa_devida`, `esta_dormente` e o `CASE` SQL que `followup/repositorio.py` gera **na importação do módulo** para o corte de candidatura. Deixar a quantidade configurável obrigaria a gerar aquele SQL a cada varredura, e o `test_dormente_e_a_negacao_exata_do_corte_de_candidatura` avisa que só a metade Python dessa igualdade é testada. A card pede *"intervalos da cadência"*, e intervalo é o que muda.

O corte barato `INTERVALO_MINIMO` passa a ser calculado da cadência vigente em cada varredura, e não da constante: com o primeiro intervalo encurtado, o corte antigo esconderia leads que já estão devidos.

## D6 — Nome e tom entram no prompt, trocando o que já estava lá

Decisão do Eduardo, 26/09/2026: vocabulário fechado, nesta card.

`SISTEMA_DO_AGENTE` vira `sistema_do_agente(identidade)`, e a constante continua existindo como o resultado com a identidade padrão — **texto idêntico ao de hoje**. Duas trocas, e nenhum acréscimo fora delas:

- *"Voce e o assistente virtual de uma imobiliaria"* → *"Voce e {nome}, o assistente virtual de uma imobiliaria"*, só quando há nome;
- *"em tom de conversa"* → a frase do tom: `CORDIAL` é a de hoje, `FORMAL` é *"em tom formal e respeitoso"*, `DESCONTRAIDO` é *"em tom descontraido e proximo"*.

**O cache continua valendo.** O bloco `system` é idêntico entre chamadas enquanto a configuração não muda; mudar a configuração invalida o prefixo uma vez, e o seguinte volta a ser cacheado. **Só o prompt do agente muda** — o do investidor, o da desambiguação e o da reação não falam em nome nem em tom.

**O orçamento.** O pior caso (nome de 30 caracteres, tom mais longo) entra como parcela de `_decomposicao`, e o teto fixo de `test_a_margem_do_orcamento_do_prompt_e_deliberada` sobe exatamente o custo medido — a pergunta *"o que sai do prompt?"* foi respondida antes: o tom **substitui** a frase que já estava lá, e o nome é o único acréscimo. O teto derivado (`headroom × 0,75`) tem folga de 461 e continua prendendo menos.

## D7 — As rotas

```
GET   /api/v1/configuracao/agente            → a vigente, e os limites de cada campo
PATCH /api/v1/configuracao/agente            → parcial; 422 fora da faixa; nova versão
GET   /api/v1/configuracao/agente/historico  → versões, cada uma com o que mudou
```

Permissão nova, `CONFIGURAR_AGENTE`: só ADMIN, por construção, como `VER_AUDITORIA`, e em `DE_ESCRITA`. O `PATCH` que não muda nada não grava versão.

## Arquivos

```
alembic/versions/0058_configuracoes_do_agente.py   # a 0057 ja era a da TEC-204
src/mobia/domain/configuracao/{__init__,models,vigente,repositorio}.py
src/mobia/domain/context/score.py            # pesos (D3)
src/mobia/domain/context/qualificacao.py     # teto por parametro (D4)
src/mobia/domain/context/repositorio.py      # registrar_recalculo le os pesos
src/mobia/domain/context/montagem.py         # o retrato da configuracao no contexto
src/mobia/domain/followup/cadencia.py        # cadencia por parametro (D5)
src/mobia/workers/jobs/sweep_followups.py    # le a vigente por varredura
src/mobia/domain/agente/classificador.py     # sistema_do_agente (D6)
src/mobia/domain/agente/turno.py             # o teto do contexto
src/mobia/api/routes/configuracao.py
```

## Testes

- **Unitários** — os limites (cada linha de D2); o score com pesos padrão é idêntico ao de hoje; com urgência 30 os pontos escalam como D3; `excedeu_o_teto` com teto 6; `tentativa_devida` com cadência encurtada; `sistema_do_agente(PADRAO) == SISTEMA_DO_AGENTE` de hoje, byte a byte; o orçamento no pior caso.
- **Os quatro cenários, contra banco** — peso 25 → 30 e o recálculo seguinte usa 30, sem reiniciar nada; limite 8 → 6 e o turno encaminha na sexta pergunta; peso negativo é 422 e a vigente não muda; o histórico traz autor, anterior, novo e o instante.
- **A cadência** — com o primeiro intervalo encurtado, a varredura acha o lead que o corte antigo esconderia.
- **Só ADMIN** — GERENTE leva 403.

## Emendas ao SRS

- **RN-19.3, Emenda E-01** — a tabela de versões, os limites, o peso como teto do fator, a cadência de quantidade fixa, o tom de vocabulário fechado.
- **RNF-18, Emenda E-04** — `CONFIGURACAO_ALTERADA` na trilha.

## Lacunas declaradas

- **L1 — a quantidade de tentativas de follow-up não se configura** (D5).
- **L2 — tom é vocabulário fechado**; instrução livre fica para o versionamento de prompt (TEC-199).
- **L3 — os textos fixos que o lead recebe** (encaminhamento, limite de perguntas, fallbacks) **não usam o nome do assistente.** Só o modelo o conhece.
- **L4 — mudar os pesos não recalcula ninguém.** O score de cada lead muda no próximo recálculo dele, que é o próximo turno, edição ou recálculo manual. A lista de leads mostra os dois regimes lado a lado até lá.
- **L5 — os cortes de temperatura (70 e 40) não se configuram.** A card não os pede, e a soma dos pesos limitada a 100 (D2) é o que os mantém com sentido.

# TEC-325 — Histórico de score e imóveis recomendados no detalhe do lead

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-325](https://eduardodurieuxlopes.atlassian.net/browse/TEC-325) — épico TEC-304
**Branch:** `feat/tec-325-historico-e-recomendacoes`
**Depende de:** TEC-193 (o detalhe já devolve os dois blocos), TEC-323 (a tela do detalhe)

## O que existe quando a card começa

`GET /api/v1/leads/{leadId}` devolve desde a TEC-193:

- **`historicoScore`**, em ordem cronológica crescente: `{em, anterior, novo, fatores, causas}`. As `causas` são as constantes `CAUSA_*` de `context/auditoria.py`.
- **`recomendacoes`**, na ordem em que foram apresentadas: `{imovelId, codigo, titulo, bairro, scoreMatch, motivoMatch, reacao, motivoDescarte, apresentadoEm}`. A `reacao` é `ReacaoLead` (`INTERESSE`, `DESCARTE`, `NEUTRO`, `SEM_RESPOSTA`) ou `null`, e `motivoDescarte` é `CategoriaDescarte` (`DISTANCIA`, `PRECO`, `TAMANHO`, `OUTRO`).

A tela não lê nenhum dos dois, e o tipo `DetalheDoLead` do frontend nem os declara. **Esta card é só de frontend**, mais um teste do Python que prende os vocabulários.

## D1 — As duas seções entram onde a TEC-323 as deixou

Entram entre Qualificação e Agendamentos, nas posições 4 e 5 da D5 da TEC-323.

## D2 — O histórico: gráfico de linha, e a lista é a leitura de verdade

**O gráfico é SVG desenhado à mão**, num Server Component. O painel não tem biblioteca de gráfico, e trazer uma para uma linha de até algumas dezenas de pontos custaria bundle a uma tela que hoje não tem nenhum.

- Eixo Y de 0 a 100, porque o score é limitado a essa faixa. Os pontos ficam igualmente espaçados no X: a distância entre recálculos não é o que o corretor procura, e os horários estão na lista.
- A cor é `currentColor`, então segue o tema claro e o escuro sem token novo.
- **O SVG tem `role="img"` e um `aria-label` que resume a série**, por exemplo "Score de 30 a 82 em 3 recálculos". A lista abaixo é a leitura completa, e é o que o primeiro cenário da card afirma.
- Com um recálculo só não há linha: o gráfico mostra um ponto.

**A lista** tem uma linha por recálculo, em ordem cronológica:

- a data absoluta;
- o valor, como "30 → 47", ou só "30" no primeiro cálculo;
- os motivos, pelos rótulos em português das `causas`.

Causa desconhecida aparece humanizada, como os outros vocabulários da tela.

**Sem recálculo**, a seção diz "O score deste lead ainda não foi calculado." e não desenha gráfico.

## D3 — Recomendações: o imóvel, o motivo do match e a reação

Cada imóvel mostra título, código e bairro, o motivo do match (`motivoMatch`, texto do backend), o score do match em porcentagem, quando foi apresentado e a reação:

| `reacao` | a tela |
| --- | --- |
| `INTERESSE` | Gostei |
| `DESCARTE` | Não é pra mim, com a categoria quando houver: "Não é pra mim · distância" |
| `NEUTRO` | Viu, sem opinar |
| `SEM_RESPOSTA` | Sem resposta |
| `null` | Aguardando reação |

"Gostei" e "Não é pra mim" são os rótulos da própria card e da TEC-350, os botões do chat web. O corretor lê a mesma palavra que o lead clicaria.

**Sem recomendação**, o texto é "Nenhum imóvel recomendado ainda.", um estado vazio, e não "Ainda não medido". É o terceiro cenário.

## D4 — Os vocabulários da tela são os do backend, e o teste da TEC-329 os prende

`lib/detalhe.ts` ganha `CAUSAS_DO_SCORE`, `REACOES` e `DESCARTES`, exportados. `tests/unit/test_vocabulario_da_tela.py` passa a compará-los:

- `REACOES` e `DESCARTES` com `ReacaoLead` e `CategoriaDescarte`;
- `CAUSAS_DO_SCORE` com todas as constantes `CAUSA_*` de `context/auditoria.py`.

Uma causa nova no backend sem rótulo na tela reprova lá.

## Fora do escopo

- **Os fatores do score** (completude, urgência…) não aparecem. A card pede o motivo de cada recálculo, que são as `causas`. Os fatores explicariam o valor, e isso é outra tela.
- **Link para o imóvel**: a tela de imóveis é a TEC-333.

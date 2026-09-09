# TEC-159 — Manter a busca dentro do SLA de 400 ms

**Status:** desenhado em 2026-09-09 na branch `feat/tec-159-sla-da-busca`.

**Card:** [TEC-159](https://eduardodurieuxlopes.atlassian.net/browse/TEC-159) — Should (MoSCoW), prioridade High. Origem: RF-09, RN-09.5 (SRS v1.0) e RNF-03. Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155).

**Desbloqueada pela [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158)**, que entregou a busca híbrida.

**Esta card foi encomendada por escrito pela [TEC-157](https://eduardodurieuxlopes.atlassian.net/browse/TEC-157).** A migration [`0017_indexacao_vetorial.py`](../../../alembic/versions/0017_indexacao_vetorial.py) escolheu `lists = 1` no índice IVFFlat com um argumento explicitado e datado, e nomeou esta card como a herdeira: *"O indice esta aqui por conformidade com o SRS, nao porque a busca dependa dele hoje. Quem revisita `lists`, cobra o SLA ou migra para HNSW e a TEC-159."* O desenho abaixo é, em boa parte, a execução daquele bilhete.

## Objetivo

Descobrir, com número medido, se a busca cumpre o SLA de 400 ms no p95 com 10.000 imóveis — o volume em que a própria `0017` declarou que seu argumento expira.

**O que esta card entrega:** uma base sintética no volume alvo, um benchmark que mede o p95, e a evidência versionada. Mais a correção do índice **se, e somente se**, o número exigir.

**O que ela não entrega:** teste de carga do sistema inteiro, os demais RNFs de desempenho (E9), e a latência da chamada de embedding (ver L1).

## O estado de hoje, medido

- **O índice IVFFlat existe com `lists = 1`** ([`0017`](../../../alembic/versions/0017_indexacao_vetorial.py)). Com uma partição só, a busca degenera em varredura sequencial de todos os vetores — recall perfeito, custo linear. A `0017` diz que isso resolve em milissegundos *"nesta escala"* e que a frase *"vence por volta de 10.000 imoveis"*.
- **A orientação do pgvector é `lists ≈ linhas / 1000`**, então 10.000 linhas pedem `lists = 10`. E IVFFlat **treina na construção do índice, não na inserção** — mudar `lists` exige `REINDEX`.
- **O harness de perf já existe e tem precedente.** [`tests/perf/test_ingest_latency.py`](../../../tests/perf/test_ingest_latency.py) é da TEC-122: marcado `@pytest.mark.perf`, 200 requisições, `statistics.quantiles`, p95 contra teto, p50 e p99 no print como observação. `pyproject.toml` tem `addopts = "-m 'not perf'"` e o marcador declarado como *"teste de latencia, roda so sob demanda com -m perf"*.
- **A degradação sem vetor já funciona.** A TEC-158 entregou: `busca.py` devolve `consulta_vetorizada=False`, e o docstring de `_vetor_da_consulta` diz *"o vetor da consulta, ou None -- e None nunca e erro"*. O terceiro cenário do Gherkin desta card não precisa ser construído.
- **`banco_limpo` é autouse e trunca `imoveis` antes de cada teste** ([`tests/conftest.py:464`](../../../tests/conftest.py#L464)), e `tests/perf/` não tem conftest próprio — herda. Qualquer base grande morre entre testes.
- **`EmbedadorFake(dimensoes=1536)` já existe** no conftest, e `buscar(session, filtro, consulta_texto=None, limite=..., embedador=None)` aceita injeção.
- **A coluna é `Vector(1536)`.** Dez mil vetores são ~60 MB de dados vetoriais.

## Decisões

### D1 — Medir primeiro; mudar o índice só se o número exigir

A tentação é subir `lists` para 10 junto com o benchmark, seguindo a heurística do pgvector. Recusada.

Com 520 imóveis reais no catálogo hoje, `lists = 10` faz a busca varrer ~1 partição de 10 — **troca recall de produção agora por latência num volume que ainda não existe**. E a própria `0017` argumenta contra: ela escolheu `lists = 1` porque *"com 520 a 2.000 imoveis, `lists = 100` colocaria ~5 vetores por particao e o recall despencaria"*.

Mudar o índice sem medir repetiria exatamente o erro que a `0017` teve o cuidado de não cometer — ela escolheu por argumento explicitado, não por default.

**É possível que o SLA já passe.** Varredura sequencial de 10.000 vetores de 1536 dimensões são ~15 milhões de operações de ponto flutuante por consulta, e pgvector pode muito bem resolver isso bem abaixo de 400 ms. Se passar, a entrega é a evidência mais a atualização da `0017` — o número medido no lugar da estimativa.

Se reprovar, a mesma card sobe `lists` com `REINDEX`, e aí a troca recall-versus-latência passa a ter número dos dois lados.

### D2 — Vetores clusterizados sintéticos, não uniformes

Os 10.000 embeddings da base de benchmark são gerados: N centroides aleatórios, e vetores amostrados em volta deles.

Vetores uniformemente aleatórios foram recusados por um motivo técnico e não de gosto. Em 1536 dimensões, vetores uniformes sofrem concentração de medida: ficam todos aproximadamente equidistantes. **O IVFFlat particiona por proximidade** — sobre dados sem aglomeração, o particionamento não se parece com o de produção, e o benchmark mediria o custo de varredura em vez do comportamento do índice. É justamente o índice que esta card precisa calibrar.

Embeddings reais foram recusados por preço: 10.000 chamadas ao provedor custam dinheiro, e o saldo da conta está zerado (foi o que derrubou o gate de evals em 09/09). Também tornariam a base cara de regenerar, empurrando para commitá-la no repo.

**Consequência declarada:** a semelhança com a distribuição real é assumida, não medida. Ver L2.

### D3 — A base é gerada dentro do teste, a cada execução

`banco_limpo` é autouse e trunca `imoveis` antes de cada teste. Há três formas de conviver com isso, e a escolhida é a que não o contorna: o próprio teste insere os 10.000 em lote e mede depois.

Um `tests/perf/conftest.py` que desligasse a fixture autouse do pai deixaria a base viva entre execuções — mais rápido, e enganoso: um benchmark que mede sobre o estado de ontem, num arquivo que engana quem ler depois.

Um script separado em `admin/` que semeasse a base foi recusado pelo modo de falha: se ninguém rodar o script, o benchmark mede sobre tabela vazia e **reporta p95 ótimo, passando ao afirmar o contrário do que deveria**.

**Consequência declarada:** dezenas de segundos de setup antes de medir. Aceitável num teste que só roda sob demanda com `-m perf`, e alinhado com a convenção do repo de que arquivo de teste é autocontido.

### D4 — A fronteira da medição é o banco, com embedador falso

`buscar()` vetoriza a consulta antes de ir ao banco. "A busca" tem então duas partes de natureza diferente: uma chamada de rede a um provedor externo, e uma consulta SQL com índice vetorial. **Só a segunda é o que esta card pode consertar indexando.**

O benchmark usa `EmbedadorFake` e mede o banco. Três razões: a RN-09.5 trata o orçamento da busca como fatia dos 6 segundos da RNF-02, e o custo do provedor é linha de orçamento própria; a única alavanca desta card é o índice; e um benchmark que depende de rede externa vira flake, que é exatamente por que `perf` está fora do run padrão.

**Consequência declarada, e é a mais importante desta card:** se o embedding levar 200 ms em produção, o orçamento real da busca é 400 + 200, e esta card **não mede isso**. Ver L1.

### D5 — `REINDEX` depois da carga, sempre

Com `banco_limpo` truncando antes do teste, o índice IVFFlat existente foi construído sobre zero linhas. Inserir 10.000 depois não o treina — IVFFlat treina na construção.

Com `lists = 1` isso é quase inócuo: uma partição contém tudo, e a busca varre tudo de qualquer forma. **Mas deixa de ser inócuo no instante em que `lists` sobe** — e é exatamente essa comparação que a D1 pode exigir. Um `REINDEX` depois da carga custa segundos e é o que torna válida a comparação antes-e-depois.

Fazer sempre, e não só quando `lists` mudar: um benchmark cuja validade depende de lembrar de uma etapa condicional é um benchmark que vai mentir uma vez.

### D6 — A evidência mora no docstring, versionada

A CA-2 pede que *"o resultado de latência fica registrado como evidência"*. O precedente da TEC-122 só imprime — e print some quando o terminal fecha.

O p95 medido entra no docstring do teste, com data e uma linha sobre a máquina. O repo já faz isso: o docstring de `test_a_margem_do_orcamento_do_prompt_e_deliberada` guarda o histórico de cada vez que o teto se mexeu, e é o que permite ler a série em vez de um ponto.

### D7 — O terceiro cenário do Gherkin é verificação, não construção

*"Sem índice vetorial o sistema degrada em vez de falhar"* já é verdade desde a TEC-158. Esta card escreve o teste que o afirma — e o escreve como teste normal, não `perf`, porque é asserção de comportamento e não medição de latência.

## O que a card entrega

**`tests/perf/test_busca_latency.py`** (novo, basename distinto de tudo em `tests/unit/` e `tests/integration/`), marcado `@pytest.mark.perf`, no molde do `test_ingest_latency.py`:

1. Gera e insere 10.000 imóveis com vetores clusterizados, em lote.
2. `REINDEX` (D5).
3. Executa 100 buscas com filtro de preço, quartos e bairro — o que o Gherkin especifica. **Cem buscas *diferentes*, com filtros variando dentro de faixas plausíveis, e não a mesma cem vezes.** A repetição mediria o cache quente do Postgres e o mesmo caminho de partição do IVFFlat, devolvendo um p95 otimista que não descreve atendimento nenhum. As consultas são geradas de semente fixa, para que duas execuções na mesma máquina sejam comparáveis.
4. `statistics.quantiles`, p95 contra 400 ms, p50 e p99 no print.

**Um teste de degradação** em `tests/integration/`, sem marcador `perf`, afirmando que busca sem vetor devolve resultados por filtro SQL.

**Se o p95 passar:** um comentário na `0017` trocando *"esta frase vence por volta de 10.000 imoveis"* pelo número medido, com data.
**Se reprovar:** migration nova subindo `lists` com `REINDEX`, e o benchmark rodado de novo — com os dois números no docstring.

## Testes

Basenames distintos entre `tests/unit/`, `tests/integration/` e `tests/perf/` — colisão aborta a coleta da suíte inteira e não aparece em execução isolada.

O benchmark **não entra no run padrão** e portanto não muda o número da suíte. O teste de degradação entra.

`pytest -m perf` é o comando que roda o benchmark, e ele precisa dos containers de pé.

## Lacunas conhecidas

### L1 — A latência do embedding não é medida

Consequência aceita da D4. O orçamento real da busca em produção é o desta medição **mais** a ida ao provedor, e ninguém mediu a segunda parte. Se a RNF-02 (6 segundos até a primeira resposta) apertar, é a primeira coisa a medir, e é card própria — o E9 do SRS já reserva o tema.

### L2 — Os vetores clusterizados imitam a estrutura, não a distribuição real

A D2 assume que embeddings reais são aglomerados e que amostrar em volta de centroides captura o que importa para o IVFFlat. É uma suposição razoável e não verificada. Um p95 medido sobre esta base prediz produção na ordem de grandeza, não na terceira casa.

### L3 — p95 de laptop não é p95 de produção

A medição depende da máquina, e é por isso que `perf` está fora do CI: o `CLAUDE.md` registra que medir p95 em runner compartilhado seria flake, não sinal. O número no docstring vale como série comparável na mesma máquina, e como ordem de grandeza fora dela.

### L4 — O catálogo real tem 520 imóveis, não 10.000

O benchmark mede um futuro. A `0017` já dizia isso da outra ponta: o índice está lá por conformidade, não porque a busca dependa dele hoje. Esta card não muda o presente — ela descobre quando o presente acaba.

## Fora de escopo

- Teste de carga do sistema inteiro e os demais RNFs de desempenho (E9).
- A latência da chamada de embedding (L1).
- Migração para HNSW. A `0017` a nomeia como alternativa, e ela dissolveria a tensão recall-agora versus latência-depois em vez de administrá-la — mas é troca de infraestrutura, e a D1 recusa fazer qualquer troca antes de existir número que a justifique.

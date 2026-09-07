# TEC-158 — Buscar imóveis com filtro estruturado antes da similaridade

**Status:** desenhado em 2026-09-07 na branch `feat/tec-158-busca-hibrida`.

**Card:** [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158) — Must (MoSCoW), prioridade Highest. Origem: RF-09, RN-09.1, RN-09.2, RN-09.6, RN-08.4 (SRS v1.0, em `docs/srs/`); contrato de endpoint da seção 6.3; estratégia de RAG da seção 4.4. Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155) — catálogo de imóveis e busca híbrida.

**Destravada pelas duas dependências declaradas:** [TEC-157](https://eduardodurieuxlopes.atlassian.net/browse/TEC-157), mergeada em `main` como `4fe94af` (o índice vetorial), e [TEC-146](https://eduardodurieuxlopes.atlassian.net/browse/TEC-146), mergeada como `230fd14` (a faixa de preço normalizada que alimenta o filtro SQL). **Bloqueia** [TEC-159](https://eduardodurieuxlopes.atlassian.net/browse/TEC-159) (o SLA de 400 ms), [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160) (o relaxamento sem resultados), [TEC-161](https://eduardodurieuxlopes.atlassian.net/browse/TEC-161) (o guardrail anti-alucinação), [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162) (a apresentação) e [TEC-150](https://eduardodurieuxlopes.atlassian.net/browse/TEC-150).

## Objetivo

A história é da Marina: *"como quem disse até quanto posso pagar, quero ver só imóveis que cabem no meu bolso, para não perder tempo com opção fora da minha faixa"*. Must porque é a capacidade central do módulo — sem busca correta o agente não tem o que recomendar, e o guardrail anti-alucinação da TEC-161 não tem contra o que validar.

**O que esta card entrega:** a busca em duas fases (filtro estruturado em SQL, similaridade sobre o subconjunto), a ordenação da RN-09.6, o teto de 10 candidatos, e o endpoint `POST /api/v1/imoveis/busca` do contrato da seção 6.3.

**O que ela não entrega:** o relaxamento automático sem resultados (TEC-160), a validação da resposta gerada (TEC-161), a apresentação ao lead (TEC-162) e a medição do SLA de 400 ms (TEC-159).

## O que já existe, e que o desenho reusa

**A tabela `imoveis` com as dimensões de filtro prontas.** A `0016` trouxe `tipo`, `operacao`, `preco_venda`, `preco_aluguel`, `quartos`, `vagas`, `bairro`, `cidade`, `zona` e `status`; a `0017` e a `0018` trouxeram `embedding vector(1536)` e o controle de frescor. Nada da fase estruturada precisa de coluna nova — só a região precisa, e é a D5.

**Os preços já estão em centavos, nos dois lados.** `preco_venda`/`preco_aluguel` são `BigInteger` em centavos (`0011` e a D6 da TEC-156), e `Extracao.faixa_preco_min_centavos`/`max` também. A comparação é de inteiro contra inteiro, sem conversão na borda da busca — que é exatamente o que a TEC-146 existe para garantir.

**`normalizar_regiao` já foi escrita para este filtro.** A docstring dela em `agente/schemas.py` diz, com todas as letras: *"a troca é a favor do filtro estruturado da TEC-158, que compara `regiao` por igualdade em SQL — 'usp' é filtrável, 'perto da usp' não"*. A perda de informação daquela função foi paga adiantado por esta card, e a D5 e a D6 são o que fazem a promessa se cumprir.

**`TipoImovel` do agente é vocabulário fechado por causa desta card.** A docstring: *"vocabulário fechado porque a coluna é filtrada em SQL pela TEC-158; texto livre ali envenena o filtro estruturado"*. O que ninguém conciliou é que os **dois** enums existem e divergem — ver a lacuna 2.

**O documento embeddado exclui de propósito o que esta card filtra.** A Emenda E-01 da TEC-157 à RN-08.2 tira `operacao`, `status`, `zona` e `uf` do documento *"por serem dimensões de filtro por igualdade resolvidas no `WHERE` da RN-09.1"*. Aquela decisão só faz sentido se este `WHERE` existir, e é este.

**O router e a guarda do endpoint.** `api/routes/imoveis.py` já tem `APIRouter(prefix="/api/v1/imoveis", tags=["catalogo"])` e duas rotas sob `Depends(exigir_admin)`. A busca entra como terceira rota no mesmo router — ver a D10.

**`imoveis` já está em `TABELAS` (`tests/conftest.py`).** Esta card adiciona uma coluna, não uma tabela: nenhum `TRUNCATE ... CASCADE` a mais por teste, numa suíte de 1236 testes onde a fixture é autouse.

## Decisões

### D1 — Uma consulta, com a fase estruturada em CTE e o score no `ORDER BY`

As duas fases da RN-09.1 são **uma instrução**: uma CTE com o filtro estruturado, e a similaridade calculada sobre ela. "Antes" na regra é ordem de avaliação, não número de viagens ao banco.

Duas alternativas recusadas:

- **Duas viagens** (`SELECT` dos ids do filtro, depois `SELECT` ordenado por similaridade sobre esses ids). Dobra a latência para não ganhar nada: o Postgres já avalia a CTE antes de pontuar.
- **Cosseno em Python.** Trazer o subconjunto filtrado com os vetores para calcular distância na aplicação transfere 1536 floats por linha. Numa faixa larga de preço isso é o catálogo inteiro pela rede, por consulta.

**A consulta é montada com o Core do SQLAlchemy, e não com `text()` cru** — e aqui o desenho **diverge do molde das varreduras** (`sweep_stalled`, `indexar_catalogo`), que usam SQL cru. O motivo é que aquelas têm **uma** forma fixa e esta tem seis filtros independentemente opcionais. Escrever isso em `text()` obriga a `(:preco_max IS NULL OR preco_venda <= :preco_max)` em cada cláusula, e esse predicado entrega ao planejador uma condição que ele **não pode podar** — o plano genérico passa a considerar a coluna filtrada mesmo quando o parâmetro é nulo. Isso é ruim justamente na card seguinte, que mede p95. Com o Core, só as condições presentes entram no `WHERE`, e `Imovel.embedding.cosine_distance(...)` do `pgvector.sqlalchemy` dá o operador tipado sem `bindparam` escrito à mão para vetor e para array.

Forma da consulta, em SQL equivalente:

```sql
WITH filtrado AS (
  SELECT id, codigo, titulo, bairro, quartos, vagas, area_util_m2,
         {coluna_preco} AS preco, embedding
    FROM imoveis
   WHERE status = 'DISPONIVEL'                       -- RN-08.4, e nao e parametro (D3)
     AND operacao = ANY(:operacoes)                  -- [:operacao, 'AMBOS'] (D2)
     AND {coluna_preco} IS NOT NULL
     -- e so as condicoes que o chamador informou:
     AND {coluna_preco} <= :preco_max
     AND {coluna_preco} >= :preco_min
     AND tipo = :tipo
     AND quartos >= :quartos
     AND vagas >= :vagas
     AND (bairro_busca = ANY(:regioes) OR zona = ANY(:zonas))   -- D4
), pontuado AS (
  SELECT *,
         COALESCE(GREATEST(0, 1 - (embedding <=> :vetor)), 0) AS similaridade,
         CASE WHEN :preco_max IS NULL THEN 1
              ELSE GREATEST(0, 1 - abs(preco - :preco_max)::float8 / :preco_max)
         END AS aderencia
    FROM filtrado
)
SELECT *, round((0.6 * similaridade + 0.4 * aderencia)::numeric, 3) AS score,
          count(*) OVER () AS total_candidatos
  FROM pontuado
 ORDER BY score DESC, id
 LIMIT :limite
```

**`count(*) OVER ()` e não um `COUNT` separado.** O contrato da seção 6.3 devolve `totalCandidatos`, que é a contagem **antes** do teto de 10. A função de janela é avaliada antes do `LIMIT`, então o número sai na mesma passagem; uma segunda consulta pagaria o filtro duas vezes para devolver um inteiro.

**`ORDER BY score DESC, id` — o desempate é obrigatório.** Sem ele a ordem entre scores empatados é a que o executor entregar, e ela varia entre execuções. Num repositório onde os testes de integração já flakeiam sob carga, ordem não determinística seria flake plantado à mão.

### D2 — A coluna de preço vem de um dicionário fechado, e `operacao` é obrigatória

O imóvel tem dois preços e o `CHECK` da tabela só garante que **um** deles existe. A faixa do lead é um par de centavos que não diz de qual universo é. Então `operacao` é **obrigatória** no contrato da busca, e é ela que escolhe a coluna:

```python
COLUNA_DE_PRECO = {Operacao.VENDA: "preco_venda", Operacao.ALUGUEL: "preco_aluguel"}
```

`Operacao.AMBOS` **não é chave** desse dicionário: é o que um imóvel pode ser, nunca o que uma busca pede. Uma busca de `AMBOS` não tem coluna de preço para comparar.

**O filtro é `operacao = ANY([:operacao, 'AMBOS'])`.** Igualdade crua excluiria todo imóvel anunciado para venda **e** locação, que é caso comum de catálogo real e sairia da busca em silêncio.

Duas alternativas recusadas:

- **Operação opcional com `COALESCE(preco_venda, preco_aluguel)`.** Nunca devolve vazio por falta de parâmetro, e mistura os dois universos: "até R$ 600.000" passa a casar todo aluguel do catálogo, e a Marina recebe apartamento de R$ 3.500 por mês como se fosse a compra que ela pediu. É o erro que a história dela nomeia, cometido pela infraestrutura em vez de pelo modelo.
- **A busca derivar a operação da `Intencao`.** Um parâmetro a menos, ao custo de `domain/catalogo` importar `domain/agente` e de a regra de negócio *"investimento é compra"* passar a morar na camada de consulta. A tradução fica no chamador; ver a lacuna 1.

### D3 — `status` não é parâmetro da busca

A RN-08.4 diz que imóvel com status ≠ `DISPONIVEL` é excluído dos resultados de busca **e mantido no banco para histórico**. As duas metades pedem coisas diferentes: a segunda é a razão de não haver `DELETE`, e a primeira é uma cláusula literal no `WHERE`.

`status` **não** entra na assinatura. Aceitá-lo como filtro — como o `GET /api/v1/imoveis` da seção 6.3 aceita, e ali está certo, porque aquele é o CRUD de vitrine — daria ao chamador um jeito de pedir imóvel vendido pela mesma porta que o agente usa. A regra é sobre a busca, então mora na busca.

### D4 — Região é um `OR` entre bairro e zona, e não uma classificação

O lead diz `regiao` como texto dobrado: `"zona sul"`, `"moema"`, `"centro"`. O banco tem `bairro` (texto livre do arquivo) e `zona` (enum opcional em `{NORTE, SUL, LESTE, OESTE, CENTRO}`). O cenário 1 do Gherkin exige que `"zona sul"` funcione.

A leitura óbvia era classificar: *"este texto é uma zona ou um bairro?"*. Foi recusada porque **a pergunta não tem resposta única**. `"centro"` é o nome de uma zona **e** o nome de um bairro em quase toda cidade brasileira; classificar obriga a escolher, e a escolha erra metade das vezes sem sintoma nenhum — devolve resultados plausíveis do lado errado.

O filtro é um `OR`, e some com a decisão:

```sql
bairro_busca = ANY(:regioes) OR zona = ANY(:zonas)
```

`:zonas` é o subconjunto de `:regioes` que casa o vocabulário de `Zona`, aceitando `"zona sul"` e `"sul"` para `SUL`. `"moema"` não deriva zona nenhuma e casa só bairro; `"centro"` casa os dois e devolve a união, que é a resposta certa para quem disse "centro". A derivação é uma função pura em `domain/catalogo/busca.py`, sobre o enum que já mora em `catalogo/enums.py`.

`zona` é nulável, e isso não incomoda: `NULL = ANY('{}')` é `false`, não `NULL` — imóvel sem zona cadastrada simplesmente não casa pelo lado da zona.

**O contrato da seção 6.3 pede uma lista** (`"regioes": ["Zona Sul"]`) e o lead tem uma `regiao` só. A assinatura aceita a sequência, e a busca **dobra o que recebe** antes de comparar: o chamador pode passar `"Zona Sul"` ou `"zona sul"` e o resultado é o mesmo, porque `dobrar` é idempotente (D6). Sequência vazia significa "sem filtro de região", e não "nenhuma região casa".

### D5 — `bairro_busca` materializada, escrita pelo repositório

O lead fala `"aclimacao"` (dobrado por `normalizar_regiao`) e o banco guarda `"Aclimação"` como veio do arquivo. Comparar os dois exige dobrar caixa **e** acento de um dos lados.

**A coluna `bairro_busca` guarda a forma dobrada, escrita na importação pela mesma função que dobra a fala do lead.** É a D3 da TEC-157 aplicada de novo: uma definição, uma casa, dois consumidores. Índice B-tree comum, sem extensão nova.

Três alternativas recusadas:

- **`unaccent` com índice funcional.** `CREATE EXTENSION unaccent` e comparar `unaccent(lower(bairro))` direto — sem coluna e sem backfill. Recusada porque `unaccent()` é `STABLE` e não `IMMUTABLE`, então um índice funcional sobre ela exige um wrapper `IMMUTABLE` declarado à mão: uma mentira controlada sobre a função, que quebra em silêncio se alguém trocar o dicionário do unaccent. E a regra de dobra passaria a existir em Python **e** em SQL — a divergência entre as duas se manifestaria como bairro que o lead nomeia e a busca não encontra, sem erro.
- **Coluna gerada (`GENERATED ALWAYS AS ... STORED`).** Seria o desenho ideal: derivada por construção, impossível de esquecer. Não é possível — a expressão de uma coluna gerada tem de ser `IMMUTABLE`, e é justamente `unaccent` que não é. Fica registrado que a recusa é do Postgres, não do gosto.
- **Igualdade crua, `lower(bairro) = :regiao`.** Sem coluna e sem extensão. `"moema"` casa; `"aclimacao"` contra `"Aclimação"` devolve zero resultados sem erro nenhum, e o buraco só aparece no bairro acentuado. É a classe de falha silenciosa que a D3 da TEC-157 recusou o hash em SQL para evitar.

**O preço da escolha, dito em voz alta.** `bairro_busca` é derivada e escrita à mão, então existe um caminho em que ela fica velha: quem gravar `bairro` sem gravar a dobra. Hoje há um único escritor (`repositorio.sincronizar`), e o CRUD administrativo da TEC-197 será o segundo — ele precisa lembrar. A coluna gerada eliminaria esse risco e o Postgres não a permite; a mitigação é um teste que afirma a igualdade das duas colunas depois de um upsert, e o comentário na coluna dizendo o que ela é.

**A sutileza no `repositorio.py`.** `CAMPOS_COMPARADOS` alimenta **duas** coisas: o diff campo a campo e o `SET` do `ON CONFLICT DO UPDATE`. `bairro_busca` **não pode** entrar nele — não vem do arquivo, e é derivada de `bairro`, que já é comparado; incluí-la faria a comparação olhar para um campo que o `RegistroImovel` não tem. Mas ela **tem** de aparecer no `values` do insert e no `SET` do conflito, senão a linha vencedora da corrida documentada naquele header fica com a dobra da linha perdedora. Vai como campo derivado, tratado à parte nos dois caminhos.

### D6 — A dobra mora em `domain/texto.py`, e não em nenhum dos dois domínios

`dobrar(texto)` faz caixa e acento, **e só isso**. Não faz os prefixos de referência de `normalizar_regiao`: `"estacao "` e `"avenida "` são ruído de **fala**, e aplicá-los a nome de bairro comeria o nome de um bairro chamado "Estação".

O arquivo é novo e fica fora de `catalogo/` e de `agente/`, porque os dois o usam e a D2 acabou de decidir que `catalogo` não importa `agente` — e a seta contrária seria igualmente errada. `_sem_acento` sai de `agente/schemas.py` e passa a vir daqui; `normalizar_regiao` continua onde está, agora composta sobre `dobrar`.

O critério é o mesmo da D3 da TEC-157: quem grava e quem compara têm de derivar o valor da mesma função, porque duas expressões equivalentes em arquivos diferentes divergem no dia em que uma delas muda.

### D7 — Aderência é a distância ao teto declarado

A RN-09.6 manda ordenar por `0,6 × similaridade + 0,4 × aderência ao filtro de preço` e **em nenhum lugar define aderência**. O SRS deixou um número sem denotação, e esta card tem de fixá-la.

O primeiro fato é que aderência **não pode ser "respeita a faixa"**: o filtro é duro, então todo candidato já está dentro dela e o termo valeria 1 para todos — 40% do peso zerado, e a ordenação sendo similaridade pura com um nome errado.

A definição é:

```
aderencia = clamp(1 - |preco - teto| / teto, 0, 1)
```

Sem teto informado, `aderencia = 1` para todos e a ordem vira a da similaridade — o termo para de discriminar em vez de discriminar por acidente.

Por que essa e não outra:

- **Âncora única.** Não precisa do piso da faixa, que o lead frequentemente não diz. As alternativas centradas na faixa precisam inventar um piso quando ele falta.
- **O teto é o que o SRS trata como significativo.** A RN-09.3 relaxa **a faixa em até 10%** e a CA-09.1 cobra **só o teto**. O piso não aparece em regra nenhuma da RF-09.
- **O relaxamento da TEC-160 decai sozinho.** Candidato 10% acima do teto sai com 0,9 sem uma cláusula a mais. No teto dá 1,0; na metade do orçamento, 0,5.

Alternativas recusadas:

- **Distância ao centro da faixa.** Não empurra o lead para o topo do orçamento. Mas quando só há teto — o caso comum — o piso vira 0 e o alvo vira metade do orçamento: um imóvel de R$ 300 mil passa à frente de um de R$ 590 mil para quem disse "até R$ 600 mil". Indefensável para um corretor.
- **Folga sob o teto (`1 - preco/teto`, mais barato ganha).** Alinhada com o "não quero estourar" da Marina, e inverte a convenção do mercado: o agente lideraria com o imóvel mais barato do conjunto, que costuma ser o pior, e o lead concluiria que o catálogo não tem nada bom.

**O efeito colateral fica declarado:** esta definição favorece sistematicamente o imóvel mais caro que cabe no orçamento. É o comportamento de um corretor competente, e é também a direção em que um erro de calibragem viraria upsell. Quem for medir precisão@3 na TEC-159 tem aqui o que olhar primeiro.

### D8 — Falta de vetor nunca exclui, e a degradação é visível

Três situações reais deixam a metade vetorial sem valor: imóvel recém-importado que o cron de 30 segundos ainda não varreu, catálogo inteiro sem vetor por falta de `OPENAI_API_KEY`, e busca sem texto de consulta, quando o lead só deu critérios estruturados.

**Nenhuma delas exclui ninguém.** Similaridade ausente vale **0**: o imóvel sem vetor ordena atrás de qualquer um vetorizado com similaridade positiva, e entre os sem vetor decide a aderência de preço. O catálogo nunca fica invisível, e a metade da RN-09.1 que não depende de rede continua respondendo.

A alternativa literal — só imóvel com vetor é candidato — foi recusada porque o aviso que a própria TEC-157 escreveu descreve o desfecho: *"o catálogo fica sem vetor e a busca semântica devolve vazio"*. Um ambiente sem chave passaria a responder "não há imóveis" para um catálogo de 500, e o agente concluiria isso do banco. A outra alternativa — excluir da fase vetorial e repescar quando não enche 10 — custa duas consultas e uma regra de composição a testar nos dois regimes, para um ganho que só aparece em catálogo parcialmente indexado.

**A degradação é reportada, não silenciosa.** O resultado carrega `consulta_vetorizada: bool` e quantos dos candidatos devolvidos vieram sem vetor. Sem isso, "a ordenação está estranha" e "o provedor está fora" são indistinguíveis para quem investiga.

**Um detalhe de implementação que precisa de comentário, não de esperteza.** `GREATEST` do Postgres **ignora** `NULL`, então `GREATEST(0, 1 - NULL)` já devolve `0` e os dois casos degenerados funcionariam sozinhos. O `COALESCE` fica escrito de propósito: a regra desta decisão tem de valer por decisão, não por uma peculiaridade da função que o próximo leitor não conhece.

**E a similaridade é presa em [0, 1].** `<=>` do pgvector é distância de cosseno em [0, 2], então `1 - distancia` vive em [-1, 1]. Similaridade negativa é rara em texto real, e sem o `GREATEST` ela entraria com peso 0,6 no score e poderia empurrar um candidato para trás de um sem vetor nenhum — que é ordem sem significado.

### D9 — O embedador é injetado, e a topologia da TEC-157 ganha uma emenda

A busca precisa de um vetor de consulta, e produzi-lo é uma chamada de rede dentro do turno. `buscar()` recebe o embedador injetado, no molde de `ctx["embedador"]` da varredura: a suíte exercita o caminho inteiro sem credencial e sem rede.

**Isso atravessa uma afirmação que hoje está escrita como garantia.** A docstring de `workers/jobs/indexar_catalogo.py` diz que *"não existe caminho em que `process_message` chame o provedor de embedding"*, e deriva **dessa topologia** — explicitamente, não de um `try/except` — a regra de que falha de embedding não bloqueia o atendimento. Ela chega a dizer por que está escrita ali: *"um refactor futuro que chame o embedding de dentro do turno violaria a RN da card sem que teste nenhum reclamasse"*.

Este desenho é esse refactor, e chega avisando. A frase fica **verdadeira pela metade** e a metade que sobrevive é a que importa:

- o embedding do **catálogo** continua nunca sendo gerado no turno — a varredura em cron segue sendo o único caminho;
- o embedding da **consulta** é gerado no turno, e falha dele **não bloqueia**: cai na degradação da D8, que devolve resultados em vez de erro.

O que a topologia dava de graça agora é uma decisão que precisa de teste. Então: a docstring da varredura passa a distinguir os dois, e há um teste de que provedor caído devolve candidatos filtrados em vez de levantar. Comentário desatualizado neste repositório é defeito, e este seria o pior tipo — um que continua parecendo uma garantia.

### D10 — O endpoint entra, sob a guarda provisória que já existe

`POST /api/v1/imoveis/busca` entra nesta card, no router e na guarda que a TEC-156 já montou. O custo é baixo (router, `Depends(exigir_admin)` e o molde das duas rotas existentes) e o ganho é que a card tem um caminho executável ponta a ponta, em vez de código que ninguém chama até a TEC-161.

**A guarda não é a do SRS, e isso é declarado.** A seção 6.3 pede *"Bearer JWT ou token interno do agente"*; o que existe é o `X-Admin-Token` comparado com `compare_digest`, que a D1 da TEC-156 já registra como autenticação **provisória**. Esta card reusa o provisório em vez de introduzir JWT de raspão — mas o endpoint da busca não é administrativo, e o dia em que o JWT chegar ele precisa de papel próprio. Fica na lacuna 5.

**O que não entra na resposta:** `motivoMatch` e `yieldBrutoAnual` são RF-10 e vêm com a TEC-162; `relaxamentoAplicado` é da TEC-160. A forma da resposta não os impede de entrar depois — nenhum campo desta card precisa mudar de tipo para acomodá-los.

**A validação do teto acontece em duas camadas.** O Pydantic do endpoint recusa `limite > 10` com `422`, então um chamador HTTP recebe erro em vez de silêncio; a função de domínio faz `min(limite, MAX_CANDIDATOS)` de qualquer jeito, porque a RN-09.2 é sobre o que a busca devolve e não sobre o que o endpoint aceita. As duas camadas não são redundância a simplificar: uma informa o cliente, a outra garante a regra para quem chama por dentro.

### D11 — Pesos são constantes de módulo, e o score é `float` arredondado

`PESO_SIMILARIDADE = 0.6`, `PESO_ADERENCIA = 0.4` e `MAX_CANDIDATOS = 10` são constantes de módulo com a RN citada no comentário — não vão para `Settings`. Pesos configuráveis são RF-19, e antecipá-los aqui criaria configuração que ninguém sabe calibrar, sobre uma fórmula cuja metade acabou de ser definida nesta card (D7).

**O score sai como `float8` arredondado a três casas, e não como `Decimal`.** A tabela `Recomendacao` do SRS guarda `score_match numeric(4,3)`, e as três casas vêm daí. O tipo não: a entrada do cálculo é uma distância de cosseno em ponto flutuante devolvida pelo pgvector, e envolver isso em `Decimal` afirmaria uma exatidão que o vetor não tem. É o oposto do critério do dinheiro deste repositório — centavos são `int` porque cada unidade importa; um score de relevância é uma ordenação, e a terceira casa existe para desempatar, não para conferir.

## Modelo de dados (migration `0019`)

Uma coluna e dois índices.

| Coluna | Tipo | Papel |
|---|---|---|
| `bairro_busca` | `text NOT NULL` | O `bairro` dobrado (caixa e acento). É contra ela que a `regiao` do lead compara (D5) |

Sequência da migration: adiciona nulável → backfill → `SET NOT NULL`.

**O backfill roda em Python, dentro da migration, chamando `dobrar()`.** É o preço de manter uma definição só, e não é padrão novo neste repositório: a `0004` já importa `mobia.infra.crypto`, e é por isso que `alembic` está no escopo do `ruff` (ver `CLAUDE.md`). A alternativa era `CREATE EXTENSION unaccent` só para o backfill de uma vez — o que instalaria uma extensão permanente para uma escrita única, e deixaria no schema o convite a usá-la no caminho de leitura que a D5 recusou.

| Índice | Papel |
|---|---|
| `ix_imoveis_bairro_busca` | B-tree. Serve o lado do bairro no `OR` da D4 |
| `ix_imoveis_filtro` sobre `(status, tipo, preco_venda, quartos)` | O composto que a seção de **índices críticos** do SRS nomeia para a RN-09.1 |

**O composto entra por conformidade, não por medição** — a mesma postura que a `0017` assumiu com o `lists = 1` do IVFFlat, e vale repetir por quê: com 520 a 2.000 imóveis o filtro resolve em varredura sequencial em milissegundos, e afirmar que este índice é o que sustenta os 400 ms seria afirmar sem ter medido. Quem mede, e quem revisita a ordem das colunas dele, é a TEC-159.

**E ele só serve metade das buscas, o que é outro motivo para não o tratar como resolvido.** As colunas que o SRS nomeia incluem `preco_venda`, então uma busca de `ALUGUEL` — que compara `preco_aluguel` pela D2 — usa no máximo o prefixo `(status, tipo)` dele. A leitura fiel do SRS é a que entra; quem medir os dois regimes na TEC-159 decide se isso vira um segundo composto ou se o prefixo basta nesta escala.

`ix_imoveis_status` e `ix_imoveis_bairro` da `0016` **ficam**: o primeiro é prefixo do composto e redundante para esta consulta, mas `bairro` continua sendo filtrável pelo `GET /api/v1/imoveis` de vitrine, que não passa por `bairro_busca`. Derrubar índice por causa de uma consulta nova é decisão para quem tiver a medição das duas.

## Estrutura

| Arquivo | Papel |
|---|---|
| `domain/texto.py` | **Novo.** `dobrar(texto) -> str`. Pura, sem I/O, sem `Settings` (D6) |
| `domain/catalogo/busca.py` | **Novo.** `buscar(...)`, a derivação de zonas, `aderencia_de_preco` e as constantes da RN-09.6 |
| `domain/catalogo/schemas.py` | `FiltroDeBusca` e `Candidato` — o contrato de entrada e saída da busca |
| `domain/catalogo/repositorio.py` | Passa a gravar `bairro_busca` nos dois caminhos de escrita (D5) |
| `domain/agente/schemas.py` | `_sem_acento` sai; `normalizar_regiao` compõe sobre `dobrar` |
| `api/routes/imoveis.py` | `POST /api/v1/imoveis/busca` (D10) |
| `workers/jobs/indexar_catalogo.py` | Só a docstring: a afirmação de topologia da D9 |
| `alembic/versions/0019_busca_hibrida.py` | **Nova.** `bairro_busca`, backfill em Python, dois índices |

## Fluxo

Uma busca, de fora para dentro:

1. **O chamador monta o filtro.** `operacao` é obrigatória (D2); faixa, tipo, quartos, vagas e regiões são opcionais. `consulta_texto` é opcional.
2. **A busca dobra as regiões recebidas** e deriva as zonas que o vocabulário reconhece (D4).
3. **O vetor da consulta**, quando há `consulta_texto`: chamada ao embedador injetado. Falha ou ausência de chave → `vetor = None`, e a busca **segue** (D8, D9).
4. **Uma instrução no banco** (D1): filtro estruturado na CTE, similaridade e aderência sobre o subconjunto, score no `ORDER BY`, `LIMIT` no teto.
5. **O resultado** traz, por candidato, o `id` e o preço **lidos do banco** — que é a RN-09.4 e o quarto cenário do Gherkin — mais o score; e, no envelope, `total_candidatos`, `consulta_vetorizada` e quantos vieram sem vetor.

**O que acontece com zero resultados:** devolve lista vazia com `total_candidatos = 0`. O relaxamento da RN-09.3 é da TEC-160, e esta card não o antecipa nem o impede — a assinatura do filtro é o que ela vai relaxar.

## Contrato do endpoint

Entrada, no formato da seção 6.3 (camelCase na borda HTTP, `snake_case` por dentro):

```json
{ "consultaTexto": "apartamento com varanda perto da praia",
  "filtros": { "operacao": "VENDA", "precoMax": 60000000, "quartosMin": 2,
               "regioes": ["Zona Sul"] },
  "limite": 10 }
```

Saída:

```json
{ "itens": [{ "id": "uuid", "codigo": "AP-1042", "titulo": "...", "bairro": "...",
              "preco": 58000000, "quartos": 2, "vagas": 1, "areaUtilM2": 74,
              "scoreMatch": 0.871 }],
  "totalCandidatos": 7, "consultaVetorizada": true, "candidatosSemVetor": 0 }
```

`operacao` obrigatória; `limite` com `le=10` e **default 10** (D10). `precoMax` em **centavos**, como no exemplo do SRS e como a coluna.

**O campo é `preco`, e o SRS diz `precoVenda`.** A divergência é deliberada: o exemplo da seção 6.3 é de uma busca de venda, e copiá-lo ao pé da letra faria a busca de aluguel devolver o preço de venda do imóvel — ou o campo errado, ou nulo. O que a RN-09.4 exige é *"o preço vindo do banco"*, e o preço relevante é o da operação buscada, que é a mesma coluna que o filtro comparou (D2). Um consumidor que precise dos dois preços tem o `id` para buscar a ficha inteira; a TEC-162, que monta a ficha, é quem decide isso.

## Testes

TDD. Os nomes de arquivo são distintos entre `unit` e `integration` de propósito: basename repetido aborta a coleta da suíte inteira, não aparece em execução isolada, e já custou duas cards.

**`tests/unit/test_busca_pontuacao.py`** — sobre as funções puras:

- aderência sem teto informado vale 1 para todos, e o score vira similaridade pura;
- aderência no teto vale 1,0; na metade do orçamento, 0,5; a 10% acima do teto, 0,9 — este último é o que amarra a D7 ao relaxamento da TEC-160 antes de ele existir;
- aderência é presa em 0 e nunca negativa;
- `dobrar` é idempotente, e dobra cedilha junto com acento;
- `dobrar` **não** come prefixo de referência — `"estacao vila madalena"` sai inteira, ao contrário de `normalizar_regiao` (D6);
- as zonas derivadas de `"zona sul"`, `"sul"`, `"centro"` e `"moema"` — a última não deriva nenhuma;
- `min(limite, MAX_CANDIDATOS)` no domínio.

**`tests/integration/test_busca_hibrida.py`** — os quatro cenários do Gherkin, mais o que o desenho decidiu:

- **cenário 1:** filtro de 2 quartos, até R$ 600.000, zona sul — nenhum resultado acima do teto, nenhum com menos de 2 quartos, todos da zona sul;
- **cenário 2:** imóvel compatível marcado `VENDIDO` não aparece **e continua existindo no banco** — as duas asserções, porque a RN-08.4 tem duas metades e um `DELETE` passaria na primeira;
- **cenário 3:** filtro que casa 40 imóveis devolve no máximo 10, e `total_candidatos` diz 40 — é o que prova que a contagem é antes do teto;
- **cenário 4:** cada candidato traz `id` e preço lidos do banco;
- imóvel `operacao = AMBOS` entra na busca de `VENDA`, e imóvel de `ALUGUEL` não;
- busca de `ALUGUEL` compara `preco_aluguel` — o imóvel de R$ 580.000 de venda e R$ 3.000 de aluguel entra numa faixa de "até R$ 4.000" e não numa de "até R$ 600.000" de aluguel;
- imóvel com `embedding NULL` **entra**, e ordena atrás de um vetorizado com similaridade positiva (D8);
- **embedador que levanta devolve candidatos filtrados, não erro** — a asserção que a D9 tornou necessária ao trocar topologia por decisão;
- busca sem `consulta_texto` não chama o embedador nenhuma vez, e ordena por aderência;
- `"centro"` casa o imóvel da zona `CENTRO` **e** o do bairro "Centro" (D4);
- bairro acentuado casa o texto dobrado do lead — `"aclimacao"` encontra `"Aclimação"` (D5);
- **o upsert mantém `bairro_busca` igual à dobra de `bairro`**, depois de inserir e depois de atualizar o bairro de uma linha existente. É a mitigação escrita da D5, e é o teste que pega quem gravar `bairro` sem a dobra;
- ordem estável entre scores empatados (D1).

**`tests/integration/test_busca_endpoint.py`:**

- `200` com o contrato da seção 6.3;
- `422` para `limite > 10` e para `filtros` sem `operacao`;
- `403` sem o `X-Admin-Token`.

Nenhum teste de latência: `addopts = "-m 'not perf'"` já exclui `perf`, e o SLA é da TEC-159. Nenhuma chamada de rede na suíte — o embedador é falso, como na TEC-157.

## Emendas ao SRS

**RN-08.2 — Emenda E-02 (TEC-158, 07/09/2026).** A E-01 desta mesma regra estabeleceu que o embedding do catálogo nasce numa varredura em cron, e a TEC-157 derivou daquela topologia a garantia de que falha de embedding não bloqueia atendimento. A emenda distingue os dois embeddings: o do **catálogo** continua nunca sendo gerado no turno; o da **consulta** é, e a não-obstrução passa a vir de degradação declarada — sem vetor, a busca devolve o subconjunto filtrado ordenado por aderência de preço, em vez de vazio ou erro. Ver a D9.

**RN-09.6 — Emenda E-01 (TEC-158, 07/09/2026).** A regra dá o peso (`0,4`) sem definir *aderência ao filtro de preço*. Como o filtro é duro, "respeita a faixa" valeria 1 para todo candidato e zeraria o termo. A emenda fixa `aderencia = clamp(1 - |preco - teto| / teto, 0, 1)`, e `1` quando não há teto informado. Consequência declarada: a ordenação favorece sistematicamente o imóvel mais caro que cabe no orçamento. Ver a D7.

**RN-09.1 — Emenda E-01 (TEC-158, 07/09/2026).** A regra lista *"bairro"* entre as dimensões estruturadas. O filtro de região é a **união** de bairro e zona (`bairro_busca = ANY(...) OR zona = ANY(...)`), porque `"centro"` é nome de zona e de bairro simultaneamente e classificar o texto do lead como um ou outro erra em silêncio. A comparação é contra a coluna `bairro_busca` — o bairro dobrado —, e não contra `bairro`. Ver a D4 e a D5.

## Lacunas declaradas

1. **A tradução `Intencao` → `operacao` não existe nesta card.** `catalogo` não importa `agente` (D2), então quem chama a busca traduz. Um lead com `Intencao.INDEFINIDA` não tem operação e a busca não é chamada — TEC-161/162 decidem o que fazer nesse caso.
2. **Os dois `TipoImovel` divergem, e ninguém conciliou.** O de `agente/schemas.py` tem `RURAL`; o de `catalogo/enums.py` não. O do catálogo tem `COBERTURA`; a fala do lead nunca a produz. Consequência: um lead que pede sítio filtra para zero resultados, e quem pede apartamento **nunca** vê uma cobertura. Não é desta card consertar vocabulário — mas é um zero-resultado que a TEC-160 vai tentar relaxar e não vai conseguir, porque o relaxamento dela é de preço e de bairro, não de tipo.
3. **`bairro_busca` pode ficar velha por caminho de escrita novo** (D5). Um escritor hoje, dois quando a TEC-197 trouxer o CRUD. A coluna gerada resolveria e o Postgres não permite; a mitigação é teste e comentário.
4. **O `lists = 1` do IVFFlat fica intacto**, e nesta escala a fase vetorial é varredura sequencial do subconjunto filtrado. A D7 da TEC-157 já datou a validade desse argumento em ~10.000 imóveis; revisitá-lo é da TEC-159.
5. **O endpoint da busca herda a autenticação provisória** do administrativo (D10). Ele não é administrativo, e o dia do JWT precisa dar a ele papel próprio.
6. **Precisão da busca não é medida nesta card.** O SRS pede um conjunto de 30 consultas com gabarito e precisão@3 (mitigação do risco RT-06); os testes daqui provam que o filtro é respeitado e que a ordem é determinística, não que ela é boa. A D7 diz onde olhar primeiro quando alguém medir.
7. **`ix_imoveis_status` fica redundante** para esta consulta, sendo prefixo do composto novo. Derrubá-lo exige medir o efeito nas outras consultas de `imoveis`.
8. **Não há filtro de cidade, e o bairro homônimo atravessa cidades.** A RN-09.1 não lista cidade entre as dimensões estruturadas, então esta card não a filtra: `"centro"` casa o Centro de todas as cidades do catálogo. A Emenda E-01 da TEC-157 **previu exatamente isso** e pôs `cidade` no documento embeddado *"porque bairro homônimo em cidades diferentes colide e o filtro estruturado da RN-09.1 filtra por bairro"* — mas isso mitiga pela similaridade, que tem 60% do peso e vale zero quando não há vetor (D8). Enquanto o catálogo é de uma cidade só, é inócuo; num catálogo multicidade, o filtro precisa da dimensão, e ela vem com emenda à RN-09.1 e um parâmetro novo, não com ajuste de peso.

## Fora de escopo

- **Relaxamento automático sem resultados** (RN-09.3) — TEC-160.
- **Validação da resposta gerada e bloqueio de citação fora dos candidatos** (RN-09.4) — TEC-161.
- **Apresentação ao lead, `motivoMatch` e a tabela `Recomendacao`** (RF-10) — TEC-162.
- **O SLA de 400 ms, `lists` do IVFFlat e a ordem do índice composto** (RN-09.5) — TEC-159.
- **Ligação no turno**: `process_message` não passa a chamar a busca. Sem o guardrail da TEC-161, o agente citaria imóvel sem validação nenhuma — o risco RT-01 do SRS, aberto de propósito.
- **Pesos configuráveis** — RF-19.
- **JWT no endpoint** — a autenticação provisória segue sendo a da TEC-156.

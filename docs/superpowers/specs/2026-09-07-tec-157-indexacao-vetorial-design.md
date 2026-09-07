# TEC-157 — Indexar imóvel com embedding e reindexar na alteração textual

**Status:** desenhado em 2026-09-07 na branch `feat/tec-157-indexacao-vetorial`.

**Card:** [TEC-157](https://eduardodurieuxlopes.atlassian.net/browse/TEC-157) — Must (MoSCoW). Origem: RF-08, RN-08.2, RN-08.3 (SRS v1.0, em `docs/srs/`); estratégia de RAG da seção 4.4. Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155) — catálogo e busca híbrida.

**Destravada por [TEC-156](https://eduardodurieuxlopes.atlassian.net/browse/TEC-156)**, mergeada em `main` como `bb4c0b8` (mais `f8be7f0`), único bloqueio declarado. **Bloqueia [TEC-158](https://eduardodurieuxlopes.atlassian.net/browse/TEC-158)** (a busca com filtro antes da similaridade) e, por transitividade, as outras quatro histórias do épico.

## Objetivo

A história é do agente: *"quero que cada imóvel tenha uma representação pesquisável por semelhança, para encontrar o que o lead descreveu em palavras que não estão literalmente no cadastro"*. Must porque o RAG híbrido é o diferencial técnico declarado no Anexo A — sem índice vetorial a busca da RN-09.1 vira filtro SQL puro.

**O que esta card entrega:** a infraestrutura vetorial (extensão, colunas, índice), o documento textual normalizado por imóvel, e a indexação automática que se mantém correta sozinha.

**O que ela não entrega:** a busca. Quem consome o vetor é a TEC-158, e o SLA de 400 ms é da TEC-159.

## O que já existe, e que o desenho reusa

**A tabela `imoveis` e o `updated_at` que não mente.** A `0016` criou a tabela sem `embedding`, e o comentário dela diz por quê com todas as letras: a imagem do compose não tem pgvector, e *"colunas nulas agora antecipariam a troca sem antecipar nada que a use"*. A infra pertence a esta card, por escrito.

**O diff campo a campo, preservado de propósito.** O `repositorio.py` mantém `CAMPOS_COMPARADOS` (22 campos) e `_mudou` em vez de resolver tudo num `ON CONFLICT` esperto, e a D4 da TEC-156 declara o motivo: *"a RN-08.3 manda regerar embedding quando campo TEXTUAL muda e não quando só o preço muda; `IS DISTINCT FROM` responde apenas SE mudou, nunca O QUE mudou"*. O gancho existe para esta card — e a D2 abaixo explica por que ele **não** vira a fonte de verdade, e onde segue útil.

**`updated_at` não é bumpado em linha inalterada.** O comentário em `models.py` é explícito: bumpar o carimbo numa linha que não mudou faria a coluna mentir sobre quando o imóvel mudou pela última vez. Essa decisão da TEC-156 é o que torna o pré-filtro desta card viável — reimportação inócua não gera candidato falso.

**O molde da varredura.** `sweep_stalled` (TEC-122) e `sweep_followups` (TEC-183): SQL cru com `FOR UPDATE SKIP LOCKED`, teto por passagem, registro em `functions` e `cron_jobs`. A indexação é a terceira dessa família.

**O molde do cliente de provedor.** `infra/anthropic.py` tem `get_client()` com `lru_cache`, constantes `TIMEOUT_SEGUNDOS` e `MAX_TENTATIVAS` amarradas por comentário ao `job_timeout` do worker, guarda `ConfiguracaoInsegura` para a chave e `motivo_do_provedor(exc)` traduzindo erro de provedor em motivo legível. O cliente de embedding espelha essa forma.

**`imoveis` já está em `TABELAS` (`tests/conftest.py`).** Esta card adiciona colunas, não tabelas: nenhum `TRUNCATE ... CASCADE` a mais por teste.

## Decisões

### D1 — O provedor é OpenAI `text-embedding-3-small`, e a Anthropic não tem endpoint de embeddings

A API da Anthropic tem Messages, Batches, Files, Token Counting e Models. **Não tem embeddings.** O repo declara só `anthropic>=1.0`, então esta card introduz necessariamente um segundo provedor — isso não é preferência, é consequência.

Vai `text-embedding-3-small` a 1536 dimensões, que é o que a tabela da seção 3 do SRS recomenda e o que a seção 5.1 já fixa como `vector(1536)`. Escolher a alternativa que o próprio SRS lista (BGE-M3 self-hosted, 1024d) exigiria emenda à dimensão do modelo de dados, adicionaria CPU/GPU ao container e deixaria a suíte mais lenta — que já é o ponto frágil deste repo.

Vale registrar que **a tabela do SRS é conselho, não mandato**, e este repo já divergiu dela duas vezes: a linha de workers recomenda Celery e o repo usa ARQ; a de orquestração recomenda LangGraph e o repo não usa nenhum. A escolha foi feita olhando o trade-off, não por obediência.

**Custo, para ninguém superdimensionar a fila:** US$ 0,02 por milhão de tokens. Um catálogo de 500 imóveis a ~200 tokens cada dá ~100 mil tokens, cerca de **US$ 0,002**. A retomada desta card existe pela indisponibilidade do provedor, não pelo custo.

### D2 — A pendência é derivada do estado da linha, e não avisada por quem escreve

**Esta é a decisão central da card.** "Precisa reindexar" é uma pergunta que o banco responde sobre a linha, não um recado que a importação manda.

A alternativa natural era usar o gancho que a TEC-156 preservou: a importação sabe quais campos mudaram, então ela enfileira reindexação para quem mudou texto. É a leitura óbvia da D4 daquela card, e foi recusada por três motivos concretos, todos já pagos por este repo:

1. **O caminho de corrida não passa por `_mudou`.** O header do `repositorio.py` documenta que, entre o `SELECT` e o `INSERT`, o `ON CONFLICT DO UPDATE` dispara sem consultar o diff. Uma linha atualizada nessa via nunca seria reindexada, e **não haveria sintoma** — o imóvel simplesmente não apareceria para quem busca pelo texto novo.
2. **Os 520 imóveis já importados exigiriam backfill próprio**, um caminho a mais para escrever e testar.
3. **Enfileiramento que falha não retoma.** É exatamente o bug que a TEC-156 corrigiu no endpoint (`35ec649`) e a lacuna que a TEC-261 existe para fechar. Repetir o padrão na terceira card seguida seria escolher o erro conhecido.

Derivando do estado, nenhum caminho de escrita precisa lembrar de nada: importação, seed, o caminho de corrida, e o CRUD administrativo da TEC-197 quando existir ficam cobertos porque a pendência é propriedade da linha.

**E a cobertura do caminho de corrida cai de graça.** Aquele caminho bumpa `updated_at` mesmo sem mudança de conteúdo; a linha vira candidata, o hash bate, e a varredura não chama a API — só carimba. O buraco documentado pela TEC-156 fica fechado ao custo de um hash.

**O gancho não fica órfão:** `CAMPOS_COMPARADOS` e `_mudou` continuam sendo o que produz os cinco totais do relatório de importação. Eles só não são a fonte de verdade para reindexação.

### D3 — O documento mora em Python, e o hash é do texto pronto

O portão preciso é `documento_hash`: o hash do documento que gerou o vetor. Se ele difere do hash do documento de hoje, o vetor está velho.

A tentação é calcular esse hash em SQL — `md5(titulo || descricao || ...)` — para que a varredura resolva tudo numa consulta. **Recusado.** A lista de campos passaria a existir em dois lugares, e o dia em que divergissem o sintoma seria embedding silenciosamente velho, sem erro nenhum. Comentário desatualizado conta como defeito neste repo; definição duplicada de documento é a mesma classe de problema com consequência pior.

Então a definição mora em `domain/catalogo/documento.py`, em função pura, e a varredura faz o resto em duas etapas: um pré-filtro barato em SQL que não repete campo nenhum, e a comparação exata em Python sobre os candidatos.

**O hash é `sha256` em hexadecimal**, 64 caracteres em `text`. A escolha não é de segurança — é impressão digital para detectar mudança — e `sha256` custa o mesmo nesta escala e não deixa ninguém interpretar `md5` como decisão criptográfica que não é.

### D4 — Quatro campos textuais ficam fora do documento, pelo mesmo princípio do preço

Entram no documento: `titulo`, `descricao`, `tipo`, `bairro`, `cidade`, `caracteristicas`.

Ficam fora todos os numéricos — `preco_venda`, `preco_aluguel`, `condominio`, `iptu_mensal`, `area_util_m2`, `quartos`, `suites`, `banheiros`, `vagas`, `latitude`, `longitude` — o que é o critério de aceite da card (*"o texto embeddado não contém preço nem número de quartos"*) e a RN-08.1.

Ficam fora também quatro **textuais**: `operacao`, `status`, `zona` e `uf`. São dimensões de filtro por igualdade, resolvidas no `WHERE` da RN-09.1. A seção 4.4 do SRS justifica isso para o preço — *"evitando o erro clássico de pedir ao vetor que entenda 'até 600 mil'"* — e o raciocínio é idêntico para "para alugar": pedir ao vetor que decida operação é pedir que faça o trabalho de um `WHERE`, pior.

`fotos` fica fora por não ser texto descritivo.

### D5 — Indexação eventual em cron, e a regra de não bloquear sai da topologia

A importação grava os imóveis e fecha o relatório como hoje; a indexação corre depois. `CONCLUIDO` continua significando "o arquivo foi processado", e não "o catálogo está pesquisável".

**A consequência, dita em voz alta:** existe uma janela em que o imóvel está no banco e não aparece na busca. Numa demonstração, importar e buscar em seguida pode não encontrar. A cadência da D8 encurta essa janela; não a elimina.

O alternativo — embedar dentro do job de importação — transformaria 500 imóveis em 500 chamadas externas dentro de um job com `job_timeout` de 240s, e faria a importação **falhar quando o provedor cair**, que é o oposto do que a regra da card pede.

**E a regra "falha de embedding não bloqueia o atendimento" sai da topologia, não de um `try/except`.** A indexação é um cron separado; não existe caminho em que `process_message` chame o provedor de embedding. Isso é mais forte que capturar exceção — e é o que precisa estar escrito na docstring do job, porque um refactor futuro que chamasse o embedding de dentro do turno violaria a regra sem que teste nenhum reclamasse.

### D6 — A imagem do Postgres troca nos dois lugares, e o volume local é recriado

`postgres:16-alpine` → `pgvector/pgvector:pg16`, em `docker-compose.yml` **e** em `.github/workflows/ci.yml`. Não existe imagem pgvector oficial em Alpine, então a troca muda a distro base de musl para glibc.

**Trocar só o compose deixa a `main` vermelha para todo mundo com os gates passando na máquina de quem mexeu.** É o modo de falha mais provável desta card.

**O volume local é recriado, não reaproveitado.** Mesmo sendo PG16 nos dois lados, o data dir viria de uma base musl para uma glibc, e collation de texto difere entre as duas — reaproveitar arrisca ordenação de índice de texto incorreta. A base local é reproduzível por `alembic upgrade head` mais o seed, então o custo é baixo e a alternativa é um risco silencioso.

### D7 — O IVFFlat entra por conformidade com o SRS, não porque a busca dependa dele hoje

O SRS pede IVFFlat, e vai `vector_cosine_ops` porque a recuperação da seção 4.4 é por cosseno.

**Mas IVFFlat é um índice treinado.** Construído sobre tabela vazia na migration, nasce com `lists=1` e recall ruim. Nesta escala isso não custa nada — 2.000 vetores em varredura sequencial resolvem em milissegundos, muito abaixo dos 400 ms da RNF-03 — e é justamente por isso que precisa estar escrito: quem ler o código não deve concluir que a busca depende deste índice hoje. Quem cobra o SLA, e quem eventualmente revisita `lists` ou migra para HNSW, é a TEC-159.

### D8 — Cadência de 30 segundos, como a `sweep_stalled`

A `sweep_stalled` roda de 30 em 30 segundos; a `sweep_followups`, de 5 em 5 minutos, porque a menor janela da RN-13.1 é de duas horas e precisão de segundos não compraria nada.

Aqui o caso é o da primeira. O pré-filtro é uma consulta que não devolve nada quando não há pendência, então a passagem ociosa é barata — e a janela entre importar e poder buscar é exatamente o que a D5 custou. Encurtá-la é o uso mais óbvio de um cron barato.

### D9 — Indexa em qualquer `status`, inclusive `VENDIDO`

A RN-08.4 tira o imóvel não disponível dos **resultados** da busca, mas mantém a linha no banco para histórico. Filtrar por status na indexação economizaria centavos e criaria um caso ruim: reativar um imóvel o deixaria sem vetor até alguém tocar o texto dele.

O corte por status é da busca, não da indexação.

### D10 — Chave ausente: recusa em produção, aviso único em desenvolvimento

Este é o único ponto da card em que duas regras boas se contradizem: "falhar alto" e "não poluir o log a cada 30 segundos" não cabem juntas num cron.

Segue o `ConfiguracaoInsegura` do `infra/anthropic.py`: em produção, recusa. Em desenvolvimento sem chave, a varredura não faz nada e avisa **uma vez**, não a cada passagem.

**Consequência declarada:** em desenvolvimento sem chave, o catálogo fica sem vetor e a busca da TEC-158 devolve vazio. Quem cair nisso precisa achar a causa no primeiro aviso, porque não haverá um segundo.

## Modelo de dados (migration `0017`)

`CREATE EXTENSION IF NOT EXISTS vector`, e três colunas em `imoveis`, todas nuláveis:

| Coluna | Tipo | Papel |
|---|---|---|
| `embedding` | `vector(1536)` | O vetor. 1536 casa com `text-embedding-3-small` e com a seção 5.1 do SRS |
| `embedding_atualizado_em` | `timestamptz` | Controle da RN-08.3, e o pré-filtro barato da varredura |
| `documento_hash` | `text` | O portão preciso: diz se o texto que gerou o vetor ainda é o texto de hoje |

Índice IVFFlat com `vector_cosine_ops` sobre `embedding`, com a ressalva da D7 escrita na migration.

As três nuláveis é o que faz os 520 imóveis já importados entrarem como pendentes **sem backfill nenhum** — hash nulo é pendência por definição.

## Estrutura

| Arquivo | Papel |
|---|---|
| `domain/catalogo/documento.py` | **Novo.** `documento_de(imovel) -> str` e `hash_do_documento(texto) -> str`. Puras, sem I/O |
| `infra/embeddings.py` | **Novo.** Cliente do provedor no molde do `infra/anthropic.py` |
| `workers/jobs/indexar_catalogo.py` | **Novo.** A varredura |
| `workers/main.py` | Registra em `functions` e `cron_jobs` |
| `app/config.py` | Chave, modelo, dimensão, teto por passagem |
| `alembic/versions/0017_indexacao_vetorial.py` | **Novo.** Extensão, colunas, índice |
| `docker-compose.yml` | Imagem |
| `.github/workflows/ci.yml` | Imagem |

## Fluxo

Uma passagem da varredura:

1. **Pré-filtro em SQL**, com teto por passagem e `FOR UPDATE SKIP LOCKED`:

   ```sql
   WHERE embedding IS NULL
      OR documento_hash IS NULL
      OR embedding_atualizado_em IS NULL
      OR updated_at > embedding_atualizado_em
   ```

   O `embedding_atualizado_em IS NULL` está explícito de propósito: sem ele, `updated_at > NULL` dá `NULL` e imóvel recém-inserido nunca seria candidato.

2. **Para cada candidato**, monta o documento e calcula o hash em Python.

3. **Hash diferente ou nulo** → embeda em lote, grava `embedding`, `documento_hash` e `embedding_atualizado_em = now()`.

4. **Hash igual** → **nenhuma chamada à API**; só carimba `embedding_atualizado_em = now()`.

O passo 4 é o que cumpre *"alteração de preço não regera embedding"*, e cumpre de forma demonstrável: a mudança de preço bumpa `updated_at`, a linha vira candidata, o hash bate, nada é chamado. O carimbo é o que impede a linha de ficar candidata para sempre.

**Não há laço.** `updated_at` não tem `onupdate` — é escrito explicitamente pelo `repositorio.py`, e o comentário de `models.py` declara que linha inalterada não o bumpa. Carimbar `embedding_atualizado_em` não realimenta o pré-filtro.

**Falha do provedor.** A linha só é gravada em caso de sucesso, então falha deixa o candidato como estava e a passagem seguinte o pega. A retomada não depende do retry do ARQ: o cron roda de novo em 30 segundos de qualquer modo. A "fila" da card é o estado derivado — e é por isso que não há enfileiramento que possa se perder.

**Lote é tudo-ou-nada.** A chamada com array falha inteira ou volta inteira, então um lote que falha não grava nada e é retentado na íntegra. Sem estado parcial para conciliar.

**Os dois números, e por que são dois.** Teto de **100 candidatos por passagem**, como o `limite` da `sweep_stalled`; lote de **50 por chamada**, então no máximo duas chamadas e dois commits por passagem. O lote é menor que o teto de propósito: com um lote só por passagem, "comita por lote" não significaria nada — uma falha desfaria a passagem inteira. Com dois, uma falha na segunda chamada preserva os 50 primeiros.

**O teto amarra no `job_timeout`.** O worker roda com 240s, número que o comentário em `workers/main.py` amarra ao custo do turno; duas chamadas de embedding cabem nele com folga larga. O `TIMEOUT_SEGUNDOS` do cliente tem de ser estritamente menor que o `job_timeout` — mesmo raciocínio que o comentário do `infra/anthropic.py` já faz. O backfill dos 520 sai em 6 passagens, cerca de 3 minutos na cadência da D8.

## Testes

**Nenhuma chamada de rede na suíte.** O cliente de embedding é falso. Uma suíte de 22 minutos não pode passar a depender de provedor externo — seria flake por rede, não sinal.

Unitários, sobre a função pura:

- nenhum valor numérico do imóvel aparece no documento — afirmado buscando o preço e o número de quartos na string, que é o critério de aceite da card virado teste;
- hash estável quando só o preço muda;
- hash muda quando a descrição muda.

Integração, sobre a varredura:

- imóvel novo com `embedding NULL` é indexado;
- **mudança de preço não faz chamada nenhuma** — asserção de zero chamadas no falso, e não "o vetor parece igual";
- mudança de descrição gera vetor novo e hash novo;
- falha do provedor deixa a linha pendente e a passagem seguinte a indexa;
- duas varreduras concorrentes não indexam a mesma linha duas vezes.

**Basename sem colisão.** Basename de teste repetido entre `unit` e `integration` aborta a coleta da suíte inteira e não aparece em execução isolada — já custou duas cards. Vão como `test_documento_do_imovel.py` e `test_indexacao_do_catalogo.py`.

Nenhum teste de latência aqui: `addopts = "-m 'not perf'"` já exclui `perf`, e o SLA é da TEC-159.

## Emendas ao SRS

**RN-08.2** — o documento embeddado inclui `titulo` e `cidade` além dos quatro itens que a seção 4.4 lista (*"descrição, bairro, tipologia e diferenciais"*). O título porque é texto livre descritivo do imóvel; a cidade porque bairro homônimo em cidades diferentes colide, e o filtro estruturado da RN-09.1 filtra por bairro. A emenda declara também os quatro textuais **excluídos** (`operacao`, `status`, `zona`, `uf`) e o princípio que os exclui, que é o mesmo que a seção 4.4 aplica ao preço.

## Lacunas declaradas

1. **Janela entre importar e poder buscar** (D5). Encurtada pela cadência, não eliminada.
2. **Em desenvolvimento sem chave, a busca devolve vazio** (D10), com um único aviso no log.
3. **O IVFFlat nasce sem treino real** (D7). Inofensivo nesta escala, e revisitá-lo é da TEC-159.
4. **A reindexação por CRUD administrativo não tem teste** porque o CRUD não existe — a TEC-197 o traz. O desenho a cobre por construção (D2), mas cobertura por construção sem consumidor não é cobertura demonstrada.
5. **O caminho de corrida do `ON CONFLICT` gasta um hash** por linha tocada sem mudança de conteúdo. Barato, e é o preço de fechar o buraco.
6. **Duas varreduras simultâneas podem gastar uma chamada em duplicidade.** O `FOR UPDATE SKIP LOCKED` impede que selecionem a mesma linha no mesmo instante, mas o lock é solto antes do I/O de rede — deliberadamente, herdado da `sweep_stalled`, porque segurar lock de linha atravessando chamada a provedor externo é pior. Uma varredura que comece depois do rollback da outra vê a linha ainda sem vetor e a indexa também. É desperdício **idempotente**, não incorreção: o mesmo texto gera o mesmo vetor, e a última escrita tem o conteúdo da primeira. O teto por passagem limita o desperdício a 100 imóveis por janela de 30 segundos, e só numa operação com mais de um worker. Fechar isso exigiria uma coluna de claim, que é complexidade sem problema medido.

## Fora de escopo

- **A busca em si** — TEC-158.
- **O SLA de 400 ms, `lists` do IVFFlat e migração para HNSW** — TEC-159; o SRS marca HNSW como necessário só acima de 100 mil imóveis (PR-02).
- **Banco vetorial dedicado** (Pinecone, Qdrant).
- **Reindexação disparada por interface administrativa** — TEC-197 traz o CRUD.

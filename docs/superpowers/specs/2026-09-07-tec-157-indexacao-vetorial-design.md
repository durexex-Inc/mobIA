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

**O hash cobre também a identidade do provedor** (revisão de branch, 07/09/2026). O `sha256` do texto sozinho não distingue vetor gerado por `text-embedding-3-small` de vetor gerado por `text-embedding-3-large`. Uma troca de **dimensão** falha alto — a coluna `vector(1536)` recusa o vetor —, mas uma troca de **modelo na mesma dimensão** (`dimensions=1536` é opção do provedor) não mudaria hash nenhum: nenhuma linha viraria candidata, e o catálogo passaria a guardar vetores de dois espaços incompatíveis. Cosseno entre eles é ruído, sem erro e sem caminho de reindexação — a mesma classe de falha que esta decisão recusou o hash em SQL para evitar, alcançada pela configuração do provedor em vez da lista de campos.

Então `hash_do_documento(texto, modelo, dimensoes)` hasheia os três juntos. **O documento não muda:** o que vai para a API continua sendo `documento_de(imovel)` e nada mais — prefixar o nome do modelo no que se embeda mudaria o vetor de todo imóvel por um motivo que não é semântico. Quem ganha o prefixo é o material hasheado, porque ele responde outra pergunta: "o vetor guardado ainda vale?".

**O hash sozinho não dispara a reindexação, e a segunda revisão de branch (07/09/2026) corrigiu esta frase.** A versão anterior dizia que "trocar o modelo faz todo hash diferir, e a varredura reindexa o catálogo sozinha" — e isso era falso pelo mesmo motivo que a D3 escolheu não consultar hash no SQL: o pré-filtro seleciona por coluna nula e por `updated_at > embedding_atualizado_em`, e **uma troca de modelo no `Settings` não toca linha nenhuma**. A linha já indexada tem as três colunas preenchidas e o carimbo mais novo que `updated_at`: ela nunca viraria candidata, o hash novo nunca chegaria a ser comparado, e o catálogo ficaria com metade dos vetores em cada espaço até que um importador tocasse cada linha. O apelo ao mecanismo da D2 não transferia: a D2 fala de mudança de texto, que bumpa `updated_at`; mudança de configuração não bumpa nada.

A resposta foi tornar a frase verdadeira, e não retirá-la. `imoveis` ganha `embedding_modelo` (migration `0018`), escrita junto com o vetor, e o pré-filtro ganha `OR embedding_modelo IS DISTINCT FROM :modelo` com o modelo configurado ligado como parâmetro. Uma lacuna declarada dizendo "quem trocar o modelo roda `UPDATE imoveis SET documento_hash = NULL`" seria honesta, mas reintroduziria exatamente o "alguém precisa lembrar" que a D2 existe para eliminar.

**As três peças são simétricas, e o código diz qual estágio cada uma serve:** `updated_at` é o pré-filtro barato em SQL para mudança de **texto**, `embedding_modelo` é o pré-filtro barato em SQL para mudança de **configuração**, e `documento_hash` continua sendo o portão preciso em Python para as duas. O hash seguir cobrindo o modelo não é redundância a remover: é o mesmo desenho de dois estágios que a card já usa, e um comentário em cada lugar diz isso para que ninguém "simplifique" um dos dois. A **dimensão** fica fora do pré-filtro de propósito: trocá-la já falha alto na coluna `vector(1536)`, e o pré-filtro só precisa cobrir o que falharia em silêncio.

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

**Mas o argumento da topologia cobre correção, não capacidade** (revisão de branch, 07/09/2026). Ele diz que `process_message` nunca chama o provedor; não diz que ele não disputa vaga com quem chama. Os dois jobs dividem o mesmo pool do worker ARQ, e o `cron(..., unique=True)` cunha um id de job por tick — cada tick de 30 segundos é um job **distinto**, e `WorkerSettings` não fixa `max_jobs` (o default do ARQ é 10). Passagens sobrepostas portanto são fenômeno de **um** worker, não de vários: com o pior caso de 200s desta card, quase sete ticks, até 8 das 10 vagas poderiam estar indexando exatamente quando o provedor está lento.

Por isso a varredura se auto-exclui: `SELECT pg_try_advisory_lock(<chave>)` no início da passagem, e `return 0` imediato quando não é concedido. O lock é de **sessão** — precisa sobreviver ao rollback que solta os locks de linha e atravessar as sessões de escrita do laço de lotes — e é solto num `finally`, porque lock de sessão vazado dura o que durar a conexão, e a conexão volta para o pool.

**"Sessão" ali é a do Postgres, que é a conexão — não a `Session` do SQLAlchemy** (segunda revisão de branch, 07/09/2026). A primeira implementação tomou o lock numa `AsyncSession` e chamou `rollback()` nela, e `Session.rollback()` devolve a conexão ao pool: o lock era solto uma instrução depois de ser tomado. Medido, as duas consequências apareceram juntas — duas passagens seguidas recebendo `true` para a mesma chave (locks consultivos são reentrantes por conexão, e o pool devolve a mesma conexão à passagem seguinte, que é justamente a geometria do tick de 30 segundos com uma passagem parada no provedor), e um `pg_advisory_unlock` caindo em conexão diferente, devolvendo `false` e deixando o lock pendurado numa conexão do pool. Com `pool_recycle = -1` isso é permanente: toda passagem posterior sairia com `indexacao_do_catalogo_ja_em_curso` até o worker reiniciar. A varredura se desligando sozinha é pior que a sobreposição que o lock veio fechar.

A correção é dar ao lock uma casa fixa: a passagem inteira roda dentro de `engine.connect()`, e uma `AsyncConnection` sobrevive ao `rollback()` — só é devolvida ao pool no `close()`. **O custo, dito em voz alta: uma vaga do pool fica ocupada pela duração inteira da passagem.** O engine (`infra/db.py`) é criado sem `pool_size`, então são os defaults do SQLAlchemy — 5 conexões permanentes e até 10 de _overflow_. É **uma** vaga, não uma por tick: só uma passagem por vez ganha o lock, e a que não ganha devolve a conexão na instrução seguinte. Com o pior caso de 200s, isso é uma das 5 permanentes ocupada por boa parte do tempo, e `process_message` divide o mesmo pool — cabe, mas é uma conta que quem mexer em `max_jobs` ou no tamanho do pool precisa refazer.

A soltura é escrita para dois casos ruins que a passagem alcança: uma exceção vinda dela, e o cancelamento do `job_timeout` de 240s caindo no meio do `unlock` (o pior caso desenhado é 200s, então o cancelamento ali é alcançável). Quando o `unlock` não completa, a conexão é **invalidada** em vez de devolvida ao pool — fechar a conexão física encerra a sessão do Postgres e solta o lock de qualquer jeito. E o bloco não repropaga: exceção vinda de um `finally` substituiria a exceção da passagem e esconderia o erro de verdade. Um lock de transação (`pg_try_advisory_xact_lock`) exigiria manter transação aberta durante todo o I/O de rede, que é o que o rollback antes do laço existe para evitar. A chave é derivada do nome do job (`sha256` de `mobia.indexar_catalogo`, primeiros 8 bytes, big-endian com sinal) e a reprodução está escrita no módulo: o espaço de `pg_advisory_lock(bigint)` é global no banco, então número redondo escolhido a dedo é exatamente o que colide com o próximo job a fazer o mesmo. Sendo do banco e não do processo, a exclusão vale também entre workers.

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

**Onde cada metade mora** (revisão de branch, 07/09/2026). A recusa está no `startup()` de `workers/main.py`, ao lado da guarda de `WHATSAPP_ACCESS_TOKEN` e decidindo produção pelo mesmo `Settings.em_producao` dos validators de `config.py`. O aviso único está no começo de `indexar_catalogo`, com flag de módulo, **antes** de qualquer consulta — sem ele o `ConfiguracaoInsegura` do `get_client()` cairia dentro do `except Exception` do laço de lotes, que loga e segue: nenhuma linha seria indexada nunca, o retorno da passagem ociosa jamais dispararia, e sobraria um aviso por lote a cada 30 segundos, para sempre. E `OPENAI_API_KEY` entra no `.env.example`, como toda credencial deste repo entrou na card que a introduziu.

## Modelo de dados (migration `0017`)

`CREATE EXTENSION IF NOT EXISTS vector`, e três colunas em `imoveis`, todas nuláveis:

| Coluna | Tipo | Papel |
|---|---|---|
| `embedding` | `vector(1536)` | O vetor. 1536 casa com `text-embedding-3-small` e com a seção 5.1 do SRS |
| `embedding_atualizado_em` | `timestamptz` | Controle da RN-08.3, e o pré-filtro barato da varredura |
| `documento_hash` | `text` | O portão preciso: diz se o texto que gerou o vetor ainda é o texto de hoje |

Índice IVFFlat com `vector_cosine_ops` sobre `embedding`, com a ressalva da D7 escrita na migration.

As três nuláveis é o que faz os 520 imóveis já importados entrarem como pendentes **sem backfill nenhum** — hash nulo é pendência por definição.

### Migration `0018` — `embedding_modelo`

| Coluna | Tipo | Papel |
|---|---|---|
| `embedding_modelo` | `text` | O modelo que gerou o vetor guardado. É o pré-filtro barato para mudança de **configuração**, como `embedding_atualizado_em` é o de mudança de texto |

Nulável, e **sem backfill**: a migration não sabe qual modelo gerou os vetores que já existem. `NULL` é `IS DISTINCT FROM` de qualquer modelo configurado, então toda linha já indexada entra como candidata na passagem seguinte; lá o hash decide, e se o modelo não mudou nenhuma chamada é feita ao provedor — a varredura só carimba a coluna. É a mesma conciliação-sem-backfill das três nuláveis da `0017`, e é ela que impede a linha de ficar candidata para sempre. Sem índice: a coluna só aparece num `OR` de um pré-filtro que já varre `imoveis` inteira nesta escala.

## Estrutura

| Arquivo | Papel |
|---|---|
| `domain/catalogo/documento.py` | **Novo.** `documento_de(imovel) -> str` e `hash_do_documento(texto, modelo, dimensoes) -> str`. Puras, sem I/O |
| `infra/embeddings.py` | **Novo.** Cliente do provedor no molde do `infra/anthropic.py` |
| `workers/jobs/indexar_catalogo.py` | **Novo.** A varredura |
| `workers/main.py` | Registra em `functions` e `cron_jobs` |
| `app/config.py` | Chave, modelo, dimensão, teto por passagem |
| `alembic/versions/0017_indexacao_vetorial.py` | **Novo.** Extensão, colunas, índice |
| `alembic/versions/0018_modelo_do_embedding.py` | **Novo.** `embedding_modelo`, o pré-filtro de mudança de configuração |
| `docker-compose.yml` | Imagem |
| `.github/workflows/ci.yml` | Imagem |

## Fluxo

Uma passagem da varredura, precedida de `pg_try_advisory_lock` — não concedido significa que outra passagem está em curso, e a passagem devolve 0 sem tocar em `imoveis` (D5):

1. **Pré-filtro em SQL**, com teto por passagem e `FOR UPDATE SKIP LOCKED`:

   ```sql
   WHERE embedding IS NULL
      OR documento_hash IS NULL
      OR embedding_atualizado_em IS NULL
      OR updated_at > embedding_atualizado_em
      OR embedding_modelo IS DISTINCT FROM :modelo
   ```

   O `embedding_atualizado_em IS NULL` está explícito de propósito: sem ele, `updated_at > NULL` dá `NULL` e imóvel recém-inserido nunca seria candidato.

   A cláusula de `embedding_modelo` liga o modelo configurado como parâmetro e é o que faz uma troca de modelo virar reindexação sem que ninguém precise lembrar de nada (D3). Ela é a **outra metade** do `updated_at`: mudança de texto bumpa a linha, mudança de configuração não bumpa nada.

2. **Para cada candidato**, monta o documento e calcula o hash em Python.

3. **Hash diferente ou nulo** → embeda em lote, grava `embedding`, `documento_hash`, `embedding_modelo` e `embedding_atualizado_em = now()`.

4. **Hash igual** → **nenhuma chamada à API**; só carimba `embedding_atualizado_em = now()` e `embedding_modelo`.

   O `embedding_modelo` vai junto no passo 4, e não só no 3, por duas razões — e a segunda é o que impede um laço. A primeira: o hash bater já **prova** que o modelo bate, porque o modelo está dentro do material hasheado; escrever a coluna aqui é verdade, não chute. A segunda: sem isso, a linha indexada antes de a coluna existir (`embedding_modelo` nulo, hash certo) seria `IS DISTINCT FROM` do modelo configurado em toda passagem, para sempre — sem nunca chamar a API e sem nunca sair da lista de candidatos.

O passo 4 é o que cumpre *"alteração de preço não regera embedding"*, e cumpre de forma demonstrável: a mudança de preço bumpa `updated_at`, a linha vira candidata, o hash bate, nada é chamado. O carimbo é o que impede a linha de ficar candidata para sempre.

**Não há laço.** `updated_at` não tem `onupdate` — é escrito explicitamente pelo `repositorio.py`, e o comentário de `models.py` declara que linha inalterada não o bumpa. Carimbar `embedding_atualizado_em` não realimenta o pré-filtro, e gravar `embedding_modelo` no passo 4 é o que impede a cláusula nova de realimentá-lo.

**Falha do provedor.** A linha só é gravada em caso de sucesso, então falha deixa o candidato como estava e a passagem seguinte o pega. A retomada não depende do retry do ARQ: o cron roda de novo em 30 segundos de qualquer modo. A "fila" da card é o estado derivado — e é por isso que não há enfileiramento que possa se perder.

**Lote é tudo-ou-nada.** A chamada com array falha inteira ou volta inteira, então um lote que falha não grava nada e é retentado na íntegra. Sem estado parcial para conciliar.

**Os dois números, e por que são dois.** Teto de **100 candidatos por passagem**, como o `limite` da `sweep_stalled`; lote de **50 por chamada**, então no máximo duas chamadas e dois commits por passagem. O lote é menor que o teto de propósito: com um lote só por passagem, "comita por lote" não significaria nada — uma falha desfaria a passagem inteira. Com dois, uma falha na segunda chamada preserva os 50 primeiros.

**O teto amarra no `job_timeout`.** O worker roda com 240s, número que o comentário em `workers/main.py` amarra ao custo do turno; duas chamadas de embedding cabem nele com folga larga. O `TIMEOUT_SEGUNDOS` do cliente tem de ser estritamente menor que o `job_timeout` — mesmo raciocínio que o comentário do `infra/anthropic.py` já faz. O backfill dos 520 sai em 6 passagens, cerca de 3 minutos na cadência da D8.

## Testes

**Nenhuma chamada de rede na suíte.** O cliente de embedding é falso. Uma suíte de 22 minutos não pode passar a depender de provedor externo — seria flake por rede, não sinal.

Unitários, sobre a função pura:

- nenhum valor numérico do imóvel aparece no documento — afirmado buscando o preço e o número de quartos na string, que é o critério de aceite da card virado teste;
- hash estável quando só o preço muda;
- hash muda quando a descrição muda;
- hash muda quando o **modelo** muda na mesma dimensão, e quando a dimensão muda (D3).

Integração, sobre a varredura:

- imóvel novo com `embedding NULL` é indexado;
- **mudança de preço não faz chamada nenhuma** — asserção de zero chamadas no falso, e não "o vetor parece igual";
- mudança de descrição gera vetor novo e hash novo;
- falha do provedor deixa a linha pendente e a passagem seguinte a indexa;
- **uma falha no segundo lote preserva o commit do primeiro** — três pendentes com `indexacao_tamanho_do_lote = 1` injetado por `ctx["settings"]`, falhando a partir da segunda chamada. É o único teste que percorre mais de uma iteração do laço de lotes, e é ele que sustenta a afirmação "comita por lote" que faz teto e lote serem dois números diferentes;
- duas varreduras concorrentes não indexam a mesma linha duas vezes;
- **a passagem sobreposta não pega o lock** — um embedador que estaciona num `asyncio.Event` dentro do `__call__` mantém a passagem A parada no provedor com as conexões de trabalho já devolvidas ao pool, que é a geometria real do tick de 30 segundos; a segunda passagem tem de devolver `0` **sem nenhuma chamada ao provedor**. É a asserção sobre a chamada, e não sobre o desfecho da linha: um lock que não exclui nada também deixaria a linha indexada no fim, gastando duas chamadas. Esta era a lacuna que deixou a primeira implementação passar — apagar o bloco do lock inteiro não deixava um teste vermelho;
- **a passagem não deixa lock pendurado** — `SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'` tem de ser `0` depois de uma passagem completa. Com mais de uma conexão no pool antes da passagem, que é o estado normal de um worker onde `process_message` divide o mesmo pool; com uma só, o pool devolve sempre a mesma conexão e o vazamento existiria sem o teste enxergá-lo;
- **a troca de modelo reindexa a linha já indexada** — `Settings` injetado com outro `embedding_modelo`, sem tocar a linha, e a asserção é sobre a chamada nova e sobre as colunas gravadas;
- **a linha sem modelo gravado concilia em uma passagem** — `embedding_modelo` nulo vira candidata, o hash bate, nenhuma chamada é feita, a coluna é carimbada, e a passagem seguinte não a encontra mais.

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
6. ~~Duas varreduras simultâneas podem gastar uma chamada em duplicidade.~~ **Fechada na revisão de branch (07/09/2026).** O texto original dizia que a sobreposição só aconteceria "numa operação com mais de um worker", e isso era falso: o `cron(..., unique=True)` cunha um id de job por tick e o worker não fixa `max_jobs`, então **um** worker já roda passagens sobrepostas sempre que uma passagem passa dos 30 segundos — e o pior caso desta card são 200s. Dizia também que fechar isso exigiria uma coluna de claim; exigiu duas linhas de `pg_try_advisory_lock` — **e uma conexão dedicada, que a primeira implementação não deu a ele** (segunda revisão de branch, 07/09/2026): tomado numa `AsyncSession` e seguido de `rollback()`, o lock voltava ao pool junto com a conexão e não excluía nada, além de ficar pendurado quando o `unlock` caía em outra conexão. O custo declarado da correção é **uma vaga do pool ocupada pela passagem inteira** (5 permanentes + 10 de _overflow_, defaults do `create_async_engine` em `infra/db.py`). Ver a D5 para o mecanismo, para o custo, e para por que o problema é de capacidade e não de correção.
7. **A troca de modelo custa uma passagem de conciliação sobre o catálogo inteiro** (`embedding_modelo` nulo depois da `0018`, ou diferente depois de uma troca de verdade). Com teto de 100 por passagem e cadência de 30 segundos, 520 imóveis levam ~3 minutos — sem chamada ao provedor quando o modelo não mudou, porque o hash bate e a varredura só carimba.

## Fora de escopo

- **A busca em si** — TEC-158.
- **O SLA de 400 ms, `lists` do IVFFlat e migração para HNSW** — TEC-159; o SRS marca HNSW como necessário só acima de 100 mil imóveis (PR-02).
- **Banco vetorial dedicado** (Pinecone, Qdrant).
- **Reindexação disparada por interface administrativa** — TEC-197 traz o CRUD.

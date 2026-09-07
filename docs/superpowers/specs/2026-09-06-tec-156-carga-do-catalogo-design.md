# TEC-156 — Carregar o catálogo por arquivo com relatório de falhas

**Status:** desenhado em 2026-09-06 na branch `feat/tec-156-carga-do-catalogo`.

**Card:** [TEC-156](https://eduardodurieuxlopes.atlassian.net/browse/TEC-156) — Must (MoSCoW), prioridade Highest. Origem: RF-08, RN-08.1, RN-08.5 (SRS v1.0, em `docs/srs/`); PR-02. Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155) — Catálogo de imóveis e busca híbrida.

**Branch:** `feat/tec-156-carga-do-catalogo`, a partir de `main` em `64535a7`.

**Sem dependências** — a card se declara "a raiz deste épico". Bloqueia [TEC-157](https://eduardodurieuxlopes.atlassian.net/browse/TEC-157) (embedding e reindexação) e [TEC-197](https://eduardodurieuxlopes.atlassian.net/browse/TEC-197) (CRUD de imóvel pela interface administrativa).

## Objetivo

A história é do administrador da imobiliária: *"quero carregar a base de imóveis por arquivo e saber exatamente o que falhou, para corrigir as linhas ruins sem reimportar tudo às cegas."*

Must porque sem catálogo carregado não há o que recomendar — todo o Módulo C depende desta tabela existir e ter conteúdo.

**O que esta card entrega:** a tabela `imoveis`, a tabela `importacoes`, um parser estrito de CSV/JSON que rejeita por linha sem abortar o lote, o upsert por `codigo` que distingue inserido de atualizado de inalterado, os dois pontos de entrada (CLI de seed e endpoint administrativo), e o CSV versionado com a base simulada de 500 imóveis.

**O que ela não entrega:** embedding, pgvector, busca, e qualquer operação de imóvel que não seja carga por arquivo. Ver "Fora de escopo".

**A frase que governa o desenho inteiro** está no final da história: *"sem reimportar tudo às cegas"*. O produto desta card não é a tabela — é o relatório. Toda decisão abaixo que parece rigor excessivo do parser existe porque um erro absorvido em silêncio é um imóvel com dado errado no catálogo, e o admin nunca fica sabendo.

## O que já existe, e que o desenho reusa

**O molde do módulo de domínio.** `domain/<modulo>/` com `models.py` e `repositorio.py`, mais módulos de propósito único ao lado — `optout/deteccao.py`, `followup/cadencia.py`. `service.py` existe só em `messages/`, onde há orquestração de I/O de verdade. O catálogo segue o primeiro molde, não o segundo: a maior parte do trabalho aqui é transformação pura.

**O molde do script administrativo.** `admin/reativar.py` (TEC-182): `argparse`, `main` síncrono chamando `asyncio.run`, e a lógica num `_executar` async separado — porque um teste async não pode chamar `main` de dentro de um loop já rodando. A CLI de seed é o segundo membro dessa família.

**A decisão de não expor rota administrativa sem autenticação.** A docstring de `admin/reativar.py` diz, com todas as letras, que aquilo virou script em vez de endpoint HTTP porque *"existe uma rota (o webhook, autenticado por HMAC da Meta) e nada mais — JWT, OIDC e papéis são a TEC-201"*. A TEC-201 continua "A fazer". Esta card não pode ignorar aquele precedente; a D1 explica como o resolve sem descumprir a RN-08.1.

**A guarda de produção do `content_encryption_key`.** `app/config.py` tem o molde de "segredo com default de desenvolvimento que o ambiente de produção recusa". O token administrativo o reusa.

**A infra de ARQ.** `workers/main.py` com três jobs (`process_message`, `sweep_followups`, `sweep_stalled`). O job de importação é o quarto, sem infra nova.

**A convenção de enum.** Não há um único `ENUM` do Postgres no repositório: todo domínio enumerado é `StrEnum` em Python mais coluna `String(n)`. O SRS diz "enum" nas tabelas; o repo escreve `String`. Ver D10.

## Decisões

### D1 — O endpoint existe, e a autenticação é um token compartilhado até a TEC-201

A RN-08.1 pede carga **por CLI e por endpoint administrativo**, e a seção 6.3 do SRS especifica `POST /api/v1/imoveis/importar` com `Bearer JWT | Papel: ADMIN`. Essa camada é a TEC-201, que não existe.

O precedente da TEC-182 foi recusar o endpoint. Mas o argumento daquela card não transporta inteiro: lá, a rota revertia uma proteção de LGPD sobre dado pessoal, e a conclusão foi que *"quem consegue rodar isto já tem acesso ao servidor e ao banco, e isso É a autenticação"*. Aqui o objeto é o catálogo de imóveis — não é dado pessoal, e o risco é de integridade do catálogo, não de titular. A resposta proporcional é um segredo, não a ausência da rota.

**Decisão:** `catalogo_admin_token: str = ""` em `Settings`. Uma dependência `exigir_admin` compara o header `X-Admin-Token` com `secrets.compare_digest` — tempo constante, porque comparação com `==` sobre segredo vaza o prefixo por temporização — e devolve `403`.

**Com o token vazio, a rota não é registrada.** Não é `401`, não é `503`: o router de importação simplesmente não entra no app, e o startup loga um aviso. A diferença importa. Uma rota que responde `401` está exposta e depende de o código de verificação estar certo; uma rota que não existe não pode ser aberta por engano de configuração. É a mesma família de raciocínio da guarda de produção da chave de cifra — errar para o lado de não funcionar.

`.env.example` ganha um valor de desenvolvimento, e uma guarda recusa esse valor conhecido quando `environment == "production"`.

**Consequência declarada:** quando a TEC-201 chegar, ela troca o corpo de `exigir_admin` por JWT mais papel `ADMIN`, e nenhum handler muda. O ponto de extensão é uma função.

### D2 — Assíncrono, como o SRS descreve — e a CLI não passa pelo job

O SRS especifica a importação em duas etapas: `POST` devolve `202 Accepted` com `importacaoId`, e `GET /api/v1/imoveis/importacoes/{id}` devolve o relatório. O Gherkin da card é mais frouxo — só diz *"quando o relatório é consultado"* — e 500 linhas sem embedding processam em segundos, então síncrono seria viável hoje.

**Decisão: assíncrono, como está no SRS.** Não por fidelidade cega, e sim porque o síncrono seria desfeito na card seguinte: a TEC-157 acrescenta a geração de embedding, que são 500 chamadas de API por importação. Ali o assíncrono deixa de ser escolha. Fazer síncrono agora significa emendar o SRS para trocar `202` por `200` e emendá-lo de novo daqui a uma card para voltar — churn puro, com dois contratos publicados no caminho.

**A CLI, porém, não enfileira.** Ela grava a `importacoes` com `origem='CLI'` e processa no próprio processo. O quarto cenário Gherkin diz *"executado em base vazia"*, e um seed que exige Redis e worker no ar para popular o banco não serve a esse cenário — nem ao desenvolvedor que clonou o repo. As duas entradas chamam a mesma `catalogo.importacao.executar`; o que difere é quem a chama e de onde.

### D3 — `atualizados` significa "mudou de valor", e o relatório ganha um quinto total

O terceiro cenário Gherkin reimporta 500 imóveis com 10 preços alterados e exige que **"10 imóveis apareçam como atualizados"**. Não 500. Isso fixa o significado: `atualizados` conta linhas cujo conteúdo de fato mudou, e não linhas que casaram com um código existente.

Com isso as 490 restantes ficam sem categoria, e os quatro totais da RN-08.5 param de somar.

**Decisão:** o relatório ganha `inalterados`, e passa a valer `processados = inseridos + atualizados + inalterados + rejeitados`. Os quatro totais que a card e o SRS cobram continuam existindo, com o mesmo nome e o mesmo sentido; o quinto os fecha.

A alternativa — manter quatro números e deixar a diferença implícita — produz um relatório que diz "500 processados, 0 inseridos, 10 atualizados, 0 rejeitados" e obriga quem lê a deduzir o destino de 490 imóveis. Num artefato cujo propósito declarado é *"saber exatamente o que falhou"*, silêncio sobre 98% das linhas é defeito.

Entra como emenda à RN-08.5.

### D4 — O diff é em Python, e não um `ON CONFLICT` esperto

Dá para resolver o upsert inteiro em uma instrução:

```sql
INSERT ... ON CONFLICT (codigo) DO UPDATE SET ...
  WHERE imoveis IS DISTINCT FROM EXCLUDED
  RETURNING (xmax = 0) AS inserido
```

É mais rápido e mais curto. E perde exatamente a informação que a próxima card precisa.

A RN-08.3 diz que *"alteração apenas de preço ou status não regera embedding — só campos textuais o fazem"*. Para decidir isso a TEC-157 precisa saber **quais** campos mudaram, e o `IS DISTINCT FROM` só responde *se* algo mudou. Implementá-lo agora obriga a TEC-157 a reconstruir o diff do zero, jogando fora o caminho que esta card teria acabado de escrever.

**Decisão:** por lote de 500 — `SELECT` dos códigos existentes, classificação campo a campo em Python, `INSERT` dos novos e `UPDATE` só dos que mudaram. Com 500 linhas as duas abordagens são instantâneas; a diferença é toda em qual delas deixa um gancho para a card seguinte.

**O inalterado não recebe escrita nenhuma**, nem um toque em `updated_at`. Bumpar o carimbo numa linha que não mudou faria a coluna mentir sobre quando o imóvel mudou pela última vez — e `updated_at` é justamente o que um humano consulta para responder "quando isso mexeu?".

**A corrida, dita em voz alta.** Entre o `SELECT` e o `INSERT`, outro lote pode inserir o mesmo código. O `INSERT` leva `ON CONFLICT (codigo) DO UPDATE` para não levantar, e a linha acaba contada como `inserido` quando de fato foi `atualizado`. Fica assim de propósito: a alternativa seria `SELECT ... FOR UPDATE` sobre códigos que ainda não existem, que não tranca nada. Duas importações simultâneas do mesmo catálogo são operação anômala; a integridade continua garantida pelo `UNIQUE (codigo)` e só a rotulagem de uma linha rara sai imprecisa. Vai como comentário no código, não como nota de rodapé aqui.

### D5 — O parser é puro e estrito; a tolerância é só de codificação e delimitador

`domain/catalogo/parser.py` recebe `bytes` mais o nome do arquivo e devolve um iterador de `RegistroImovel | Rejeicao`. Não conhece sessão, banco, ARQ nem `Settings`. É onde mora quase toda a densidade da card, e é testável em memória — o que importa porque a suíte deste repo é lenta e os testes de integração flakeiam sob carga.

**Estrito no conteúdo.** Coluna obrigatória ausente é rejeição. Enum em minúscula é rejeição — `apartamento` não vira `APARTAMENTO`. Inteiro que não parseia é rejeição.

O motivo não é purismo. É a TEC-146: naquela card, um comentário justificava a ordem de duas checagens com um perigo inexistente, e escondeu um bug que gravava orçamento 40% abaixo do que o lead dissera — que sobreviveu a duas rodadas de revisão. Normalizar entrada num arquivo é adivinhar; adivinhar errado num catálogo grava um imóvel com dado falso e não deixa rastro. A card pede o oposto disso: um relatório que diz o que falhou.

**Tolerante em duas coisas, ambas de forma e não de conteúdo:**

- **`utf-8-sig`.** Excel exporta CSV com BOM. Sem isso, a primeira coluna do cabeçalho vira `\ufeffcodigo` (o BOM colado no nome da coluna) (o BOM colado no nome), **toda** linha é rejeitada por "codigo ausente", e o admin recebe 500 rejeições com um motivo que não explica nada. Falha catastrófica com diagnóstico enganoso é pior que falha nenhuma.
- **Delimitador `,` ou `;`, detectado no cabeçalho.** Excel em português exporta com `;`. Sem a detecção o arquivo inteiro vira uma coluna só, e o sintoma é igualmente ilegível.

Nenhuma das duas adivinha valor. Ambas são sobre conseguir ler as células antes de julgar o que há dentro delas.

**JSON** é lista de objetos com as mesmas chaves. Sem envelope, sem `{"imoveis": [...]}`.

### D6 — Preço em reais decimais, com guarda de plausibilidade

O banco guarda centavos (`BigInteger`), e o contrato da API no SRS usa centavos (`precoMax: 60000000`). A pergunta é o que o **arquivo** carrega.

**Decisão: reais com decimais** — `preco_venda` = `580000.00` —, lido com `Decimal` e multiplicado por 100 na borda. `Decimal` e não `float`: a conversão é exata, e preço com centavo quebrado não pode virar erro de ponto flutuante.

Centavos no arquivo seria mais direto no código e é o que o banco guarda. Mas quem monta o CSV à mão e digita `580000` querendo dizer reais grava **R$ 5.800,00** — valor plausível, sem rejeição, sem sintoma. É a classe de bug da TEC-146 de novo, e desta vez em massa.

**A guarda de plausibilidade fecha o buraco simétrico.** Preço fora de `[R$ 1.000, R$ 500.000.000]` é rejeição com motivo explícito. É ela que pega quem digitou centavos achando que eram reais: `58000000` no formato reais vira R$ 58 milhões, sobrevive à faixa, e — este é o ponto — a faixa foi escolhida larga o bastante para não recusar imóvel legítimo e estreita o bastante para o erro de unidade cair fora dela na grande maioria dos casos. Não é uma guarda perfeita; é a diferença entre um erro que grita e um erro que não deixa rastro.

**A guarda só se aplica a `preco_venda` e `preco_aluguel`.** `condominio` e `iptu_mensal` passam pelo mesmo parser `Decimal` e viram centavos do mesmo jeito, mas sem `checar_faixa`: um condomínio de R$ 850 ou um IPTU de R$ 320 são o comum, não a exceção, e um piso de R$ 1.000 rejeitaria quase todo imóvel real nesses dois campos. Preço de venda ou aluguel abaixo de R$ 1.000 é implausível; encargo mensal abaixo de R$ 1.000 é a norma. A mesma faixa não serve às duas naturezas de valor.

**Não reusar `domain/agente/dinheiro.py`.** A tentação é óbvia: aquele módulo já parseia `R$ 580.000,00` e `580 mil`, com gramática testada. Mas a docstring dele diz que *"nem `parsear` nem `_faixa_de` levantam"* e que *"a gramática é lista fixa e erra por falta"* — desenhado assim porque a entrada é fala de lead vinda de uma chamada ao modelo, onde uma exceção derruba o turno e o lead fica sem resposta. Num arquivo o contrato é o inverso: valor que não parseia tem que virar rejeição visível, não `None` silencioso. Mesmo problema aparente, semânticas opostas.

### D7 — Uma rejeição por linha, com todos os motivos juntos

Linha com três campos ruins devolve **uma** `Rejeicao`:

```
Rejeicao(linha=12, motivo="preco_venda ausente; tipo invalido: 'apto'; quartos nao e inteiro: 'dois'")
```

Não três entradas no relatório.

O critério é a frase da história: *"sem reimportar tudo às cegas"*. Um relatório que revela um erro por vez faz o admin corrigir, reimportar, descobrir o segundo erro, reimportar, descobrir o terceiro — três rodadas para uma linha. O valor da card é a rodada única.

**A numeração da linha** é a física do arquivo no CSV: cabeçalho é 1, primeiro registro é 2. O número tem que bater com o que o editor de texto mostra quando o admin for corrigir; um índice 0-based sobre registros seria um segundo sistema de coordenadas para ele traduzir de cabeça. No JSON é o índice 1-based do elemento, porque não há linha física correspondente. O relatório declara qual das duas convenções está em uso.

**Código repetido dentro do mesmo arquivo** é rejeição na segunda ocorrência, com o número da linha da primeira no motivo. Sem isso a mesma entidade contaria como inserida **e** atualizada no mesmo relatório, e o admin não teria como saber qual das duas linhas venceu.

### D8 — A base simulada é um CSV versionado, e não um gerador

A RN-08.1 exige que *"a POC venha com base simulada de no mínimo 500 imóveis, com distribuição realista de bairros, preços e tipologias"*, e o quarto cenário Gherkin cobra isso.

**Decisão:** `data/seed/imoveis.csv`, ~500 linhas curadas, versionado. A CLI de seed apenas o importa.

O ganho decisivo é que **o seed passa pelo mesmo parser, o mesmo validador e o mesmo upsert da importação real**. Cada `seed` exercita o caminho do CA-08.1 de ponta a ponta. Um gerador em memória criaria um segundo caminho de escrita, que precisa ser mantido em paralelo e que diverge silenciosamente do primeiro na primeira mudança de schema.

O gerador determinístico tem uma vantagem real — volume parametrizável, útil se a TEC-159 (SLA de 400 ms) precisar de 2.000 imóveis. Fica anotada como lacuna: aquela card gera o arquivo que quiser, no formato que esta card já publicou.

Também pesa que não há `faker` nas dependências, e a lista do `pyproject.toml` é enxuta de propósito. Um gerador teria que usar `random` da stdlib com seed fixo ou introduzir dependência de produção para servir só ao seed.

Custo aceito: ~150 KB no repositório, e distribuição congelada no arquivo.

### D9 — Os bytes do arquivo ficam na `importacoes`

O job recebe só o `importacao_id`. Os bytes do arquivo enviado ficam numa coluna `arquivo` (`BYTEA`) da própria `importacoes`.

As duas alternativas são piores. Passar 10 MB no payload do ARQ enche o Redis a cada importação e transforma a fila em armazenamento de arquivo. Gravar em disco exige volume compartilhado entre o processo da API e o do worker — que hoje nem existe, já que o `docker-compose.yml` sobe apenas Postgres e Redis.

Como efeito colateral desejável, reler o arquivo exato que gerou um relatório é o que torna o relatório auditável: sem isso, "a linha 12 foi rejeitada por X" não é verificável depois.

**Os bytes não são apagados ao concluir.** Com teto de 10 MB e importação de catálogo sendo operação rara, o crescimento é irrelevante para a POC. Se a retenção virar problema, descartar é um `UPDATE ... SET arquivo = NULL` — reversível, e a decisão de reter é a que preserva a opção.

### D10 — Sem `ENUM` do Postgres, e sem pgvector

**Sem `ENUM`.** O SRS descreve `tipo`, `operacao`, `zona` e `status` como enum. Não existe um único tipo `ENUM` do Postgres neste repositório: `MessageRole`, `MessageDirection`, `MessageContentType` e a `temperatura` de `followups` são todos `StrEnum` em Python sobre coluna `String(n)`. Seguir o repo, e não a letra do SRS, evita que esta tabela seja a única cujo domínio só se altera por `ALTER TYPE` em migration.

**Sem `embedding` nem `embedding_atualizado_em`.** A card põe a geração de embedding fora de escopo (H4.2 = TEC-157). Mas não é só escopo: `postgres:16-alpine` no `docker-compose.yml` não tem pgvector, então criar a coluna hoje exigiria trocar a imagem — infra que pertence à TEC-157, junto com a extensão e o índice IVFFlat. Criar as colunas agora e deixá-las nulas seria antecipar a troca de imagem sem antecipar nada que a use.

### D11 — Commit por lote; a importação não é atômica

Cada lote de 500 comita. Não há uma transação única em volta da importação inteira.

Se algo estourar na linha 800, os 500 primeiros imóveis ficam gravados e a `importacoes` registra `FALHOU` com os totais parciais **reais**. A alternativa — um `COMMIT` no fim — desfaz trabalho bom e transforma erro tardio em "nada aconteceu", que é precisamente o resultado que a história descarta.

**A importação não é atômica, e isso é a premissa da card, não um efeito colateral.** A RN-08.5 inteira existe para descrever sucesso parcial: *"registra falhas por linha sem abortar o lote"*. Atomicidade e sucesso parcial são requisitos opostos; a card escolheu o segundo.

**A fronteira entre rejeição e falha**, então, é nítida:

| situação | resultado |
|---|---|
| linha com campo inválido, ausente ou código repetido | `Rejeicao`, o lote segue |
| arquivo ilegível, cabeçalho ausente, JSON malformado, extensão desconhecida | `importacoes.status = 'FALHOU'`, com motivo |
| exceção inesperada no meio do processamento | `FALHOU`, com os totais parciais já comitados |

Nenhum dos casos de `FALHOU` é "uma linha", então nenhum deles cabe no relatório por linha. Linha ruim **nunca** leva a `FALHOU`.

## Modelo de dados (migration `0016`)

**`imoveis`** — os campos do SRS menos os dois de embedding:

| coluna | tipo | obrig. | nota |
|---|---|---|---|
| `id` | UUID | sim | PK |
| `codigo` | String(20) | sim | **UNIQUE** — chave do upsert |
| `titulo` | String(160) | sim | |
| `descricao` | Text | sim | fonte do embedding na TEC-157 |
| `tipo` | String(16) | sim | `APARTAMENTO`, `CASA`, `COBERTURA`, `TERRENO`, `COMERCIAL` |
| `operacao` | String(8) | sim | `VENDA`, `ALUGUEL`, `AMBOS` |
| `preco_venda`, `preco_aluguel` | BigInteger | não | centavos; CHECK exige ao menos um |
| `condominio`, `iptu_mensal` | BigInteger | não | centavos |
| `bairro`, `cidade` | String(120) | sim | indexados |
| `uf` | String(2) | sim | |
| `zona` | String(8) | não | `NORTE`, `SUL`, `LESTE`, `OESTE`, `CENTRO` |
| `latitude`, `longitude` | Numeric(9,6) | não | |
| `area_util_m2` | Integer | sim | |
| `quartos`, `suites`, `banheiros`, `vagas` | SmallInteger | sim | |
| `caracteristicas`, `fotos` | `ARRAY(Text)` | não | lista vazia, nunca `NULL` |
| `status` | String(12) | sim | `DISPONIVEL`, `RESERVADO`, `VENDIDO`, `ALUGADO`, `INATIVO` |
| `created_at`, `updated_at` | timestamptz | sim | `server_default=clock_timestamp()` |

O `UNIQUE (codigo)` não é decoração: é ele que impede o duplicado do terceiro cenário mesmo com dois lotes correndo juntos, no mesmo espírito do `UNIQUE` da migration `0015`.

**`importacoes`** — o relatório durável, que é o produto da card:

| coluna | tipo | nota |
|---|---|---|
| `id` | UUID | PK; o `importacaoId` do `202` |
| `origem` | String(8) | `CLI` \| `HTTP` |
| `nome_arquivo` | String(255) | |
| `arquivo` | BYTEA | os bytes enviados (D9) |
| `status` | String(12) | `PROCESSANDO` \| `CONCLUIDO` \| `FALHOU` |
| `processados`, `inseridos`, `atualizados`, `inalterados`, `rejeitados` | Integer | os cinco totais, default 0 |
| `erros` | JSONB | `[{"linha": 12, "motivo": "preco_venda ausente"}]` |
| `criada_em`, `concluida_em` | timestamptz | |

`erros` em JSONB e não em tabela filha porque a lista só é lida inteira, junto com o resto do relatório: não há consulta por motivo nem por linha, e uma tabela filha custaria um `JOIN` e uma migration a mais para servir a nenhuma consulta.

## Estrutura

```
src/mobia/domain/catalogo/models.py        Imovel, Importacao
src/mobia/domain/catalogo/enums.py         TipoImovel, Operacao, Zona, StatusImovel,
                                           StatusImportacao, OrigemImportacao
src/mobia/domain/catalogo/schemas.py       RegistroImovel, Rejeicao, Relatorio
src/mobia/domain/catalogo/parser.py        bytes -> Iterator[RegistroImovel | Rejeicao]  (puro)
src/mobia/domain/catalogo/repositorio.py   upsert por codigo + diff campo a campo
src/mobia/domain/catalogo/importacao.py    orquestra parser + repositorio, monta o Relatorio
src/mobia/admin/seed_catalogo.py           CLI
src/mobia/api/routes/imoveis.py            POST /importar, GET /importacoes/{id}
src/mobia/api/deps.py                      + exigir_admin
src/mobia/workers/jobs/importar_catalogo.py
src/mobia/app/config.py                    + catalogo_admin_token
alembic/versions/0016_catalogo_de_imoveis.py
data/seed/imoveis.csv
```

## Fluxo

**CLI:**

```
python -m mobia.admin.seed_catalogo                              # data/seed/imoveis.csv
python -m mobia.admin.seed_catalogo --arquivo /caminho/base.csv
python -m mobia.admin.seed_catalogo --arquivo base.csv --falhar-se-rejeitar
```

grava `importacoes(origem='CLI', status='PROCESSANDO')` → `importacao.executar` no próprio processo → imprime o relatório no stdout.

Sai com `0` mesmo havendo rejeições — o primeiro cenário Gherkin exige que 3 linhas ruins terminem com *"sucesso"*. `--falhar-se-rejeitar` inverte isso, para quem quiser o seed dentro de um pipeline que deva parar.

**HTTP:**

```
POST /api/v1/imoveis/importar   multipart/form-data, teto 10 MB
  -> 202 {"importacaoId": ..., "status": "PROCESSANDO"}
  -> 403 sem X-Admin-Token valido
  -> 413 acima de 10 MB
GET /api/v1/imoveis/importacoes/{id}
  -> 200 relatorio  |  404
```

Consultar antes de o job terminar devolve `200` com `status: "PROCESSANDO"` e os totais ainda em zero — não `202`, não `404`. A linha existe desde o `POST`; o que muda é o `status`, e é ele que quem consulta deve ler.

O `POST` grava `importacoes(origem='HTTP')` com os bytes e enfileira `importar_catalogo(importacao_id)`. Erros seguem o formato único da seção 6 do SRS: `{"erro", "mensagem", "detalhes", "traceId"}`.

Acima de 10 MB (~40 mil imóveis) o caminho é a CLI. O parser itera linha a linha e o upsert vai em lotes de 500, então a memória não acompanha o tamanho do arquivo — o teto é sobre o upload, não sobre a capacidade.

## Testes

Cuidado específico deste repositório: **basename de teste que colida entre `tests/unit/` e `tests/integration/` aborta a coleta da suíte inteira**, e não aparece quando se roda o arquivo sozinho. Os nomes abaixo são todos distintos entre si e dos existentes.

| arquivo | cobre |
|---|---|
| `tests/unit/test_catalogo_parser.py` | BOM, delimitador `;`, preço decimal, guarda de plausibilidade, enum minúsculo, arrays por `\|`, motivos acumulados numa linha, numeração CSV vs JSON, código repetido no arquivo, JSON malformado |
| `tests/unit/test_catalogo_relatorio.py` | os cinco totais fecham; classificação inserido / atualizado / inalterado |
| `tests/unit/test_seed_catalogo_cli.py` | argparse, exit 0 com rejeições, `--falhar-se-rejeitar`, argumento obrigatório ausente |
| `tests/unit/test_base_simulada.py` | **cenário 4**: o CSV versionado tem ≥500 linhas e atravessa o parser sem uma rejeição sequer — puro, sem banco |
| `tests/integration/test_catalogo_upsert.py` | **cenário 1** (497 gravados, 3 rejeições com linha e motivo, processo termina com sucesso); **cenário 3** (0 novos, 10 atualizados, 490 inalterados); `UNIQUE` sob reimportação; `updated_at` intocado no inalterado |
| `tests/integration/test_importacao_http.py` | `202` + id, `GET` do relatório, `403` sem token, `404` em id inexistente, rota ausente quando o token não está configurado |

Os quatro cenários Gherkin da card estão cobertos: 1 e 3 em `test_catalogo_upsert.py`, 2 em `test_catalogo_relatorio.py`, 4 em `test_base_simulada.py`.

Os dois arquivos de integração vão flakear sob carga com `ConnectionResetError` ou erro de Redis — comportamento conhecido deste repo. Cada um roda isolado antes de qualquer falha ser atribuída ao código.

## Emendas ao SRS

Três, todas aninhadas sob a regra que alteram, sem tocar no texto de 22/08/2026.

- **RN-08.5 → E-01 (TEC-156, 06/09/2026):** o relatório ganha um quinto total, `inalterados`. Motivo na D3.
- **RN-08.1 → E-01 (TEC-156, 06/09/2026):** o contrato do arquivo, que a regra só chama de "CSV/JSON" — colunas nomeadas em `snake_case`, preço em reais decimais com guarda de plausibilidade em `preco_venda`/`preco_aluguel` apenas (`condominio` e `iptu_mensal` convertem sem guarda de faixa), `|` como separador de array, enums em maiúscula exata, leitura em `utf-8-sig`, delimitador `,` ou `;` detectado no cabeçalho. Motivos nas D5 e D6.
- **Seção 6.3, `POST /api/v1/imoveis/importar` → E-01 (TEC-156, 06/09/2026):** até a TEC-201, a autenticação é `X-Admin-Token` comparado em tempo constante, e a rota não é registrada quando o token não está configurado. `Bearer JWT | Papel: ADMIN` continua sendo o alvo. Motivo na D1.

## Lacunas declaradas

1. **O endpoint fica com autenticação mais fraca que a especificada** até a TEC-201. Um segredo compartilhado não tem expiração, rotação nem papel — quem o tem pode reimportar o catálogo inteiro. Aceito porque a alternativa (não entregar o endpoint) descumpre uma regra Must, e porque o objeto não é dado pessoal.
2. **A rotulagem inserido/atualizado sai imprecisa sob importação concorrente** (D4). A integridade não sai; só a contagem.
3. **A guarda de plausibilidade de preço não é completa.** Um erro de unidade que caia dentro da faixa passa. Ela reduz a classe do bug, não a elimina.
4. **A distribuição da base simulada é fixa no arquivo.** A TEC-159, se precisar de volume maior para medir o SLA, gera o próprio arquivo no formato que esta card publica.
5. **Sem `GET /api/v1/imoveis`**, então conferir o resultado de uma importação exige o relatório ou o banco. A listagem é a TEC-197.
6. **A `importacoes` acumula os bytes dos arquivos importados** (D9). Irrelevante na POC, decisão de retenção fora desta card.
7. **`condominio` e `iptu_mensal` não têm guarda de faixa nenhuma.** A faixa `[R$ 1.000, R$ 500.000.000]` de D6 não pode se aplicar aos dois: são cobranças mensais, tipicamente na casa das centenas de reais, e o piso de R$ 1.000 rejeitaria a maioria dos imóveis legítimos. Um erro de unidade nesses campos — por exemplo, digitar centavos num campo de reais — passa em silêncio, sem a rede que pega o mesmo erro em `preco_venda`/`preco_aluguel`.

## Fora de escopo

- `embedding`, `embedding_atualizado_em`, extensão pgvector, troca da imagem do Postgres, índice IVFFlat — **TEC-157**
- `GET /api/v1/imoveis`, `POST`, `PATCH`, `DELETE` de imóvel — **TEC-197**
- Busca híbrida e filtro estruturado — **TEC-158**
- JWT, OIDC e papéis — **TEC-201**

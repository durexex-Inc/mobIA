# TEC-132 — Registrar mídia recebida sem interpretar o conteúdo

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-132](https://eduardodurieuxlopes.atlassian.net/browse/TEC-132) — épico TEC-123
**Branch:** `feat/tec-132-midia-recebida`
**Origem:** RF-01, RN-01.4 (SRS v1.0).

## Objetivo

Quem manda uma foto ou um documento pelo WhatsApp sabe que o envio chegou, e o agente pede por texto o que a mídia traria, sem fingir que a viu. O arquivo fica guardado, cifrado, com ponteiro na mensagem.

## O que o repo tem, medido sobre `acd4a5a`

1. **A mensagem de mídia já vira linha.** `parse_meta_envelope` (`domain/messages/schemas.py`) cria um `ParsedMessage` para todo tipo. IMAGEM e DOCUMENTO já existem em `MessageContentType`. O `text_body` fica nulo, e o envelope inteiro da Meta vai cifrado em `raw_payload`, com `media_id`, `mime_type`, `sha256`, legenda e, no documento, `filename`.
2. **O arquivo nunca é baixado.** Nada chama `GET /{media-id}` da Graph API. A Meta retém a mídia por tempo limitado: o `media_id` sozinho não é ponteiro durável.
3. **Não existe armazenamento de objetos.** Não há S3, MinIO nem abstração de storage, e nenhuma dependência para isso no `pyproject.toml`. O SRS prevê S3 para mídia (diagrama de arquitetura e a coluna `midia_url` do modelo de dados).
4. **Não há resposta fixa para mídia.** O turno vai ao modelo, que vê `[LEAD] (imagem, sem descricao)` (`_SEM_TEXTO`, `domain/context/montagem.py`) e responde livremente. Nada impede que ele descreva uma imagem que não viu.
5. **A legenda é descartada.** O parser só extrai texto do tipo `text`.
6. **Mídia é só WhatsApp.** O widget web (`api/routes/widget.py`) aceita apenas frames de texto.
7. **`infra/crypto.py` só cifra `str` e `dict`.** Não há variante para bytes.

## D1 — Storage: uma porta, dois adaptadores, e o arquivo cifrado pela aplicação

Porta `ArmazemDeMidia` em `domain/midia/`, com `guardar(chave, dados)` e `ler(chave) -> bytes`.

- **`ArmazemLocal`** grava num diretório configurável. É o padrão em desenvolvimento e nos testes.
- **`ArmazemS3`** usa uma dependência nova (`aioboto3`), com bucket e região vindos da config. Só é ligado quando a config pede.

**O arquivo é cifrado antes de sair do processo**: AES-GCM com a chave de conteúdo que já existe, e AAD `aad_de(message_id, "midia")`, que o amarra à mensagem. Um bucket vazado não vaza mídia. Para isso, `infra/crypto.py` ganha a variante para bytes.

**A chave do objeto é `midias/{message_id}`.** Nem nome de arquivo nem telefone: a chave aparece em log e em listagem de bucket.

**Nesta card, nada lê a mídia de volta.** `ler` existe para o teste de ida e volta e para o dashboard futuro (TEC-193).

**Alternativas descartadas:**
- **Bytes cifrados no Postgres.** O WhatsApp aceita documento de até 100 MB, e isso incharia o banco e os backups, além de contrariar o SRS.
- **Guardar só o `media_id`.** A Meta expira a mídia, e o ponteiro morreria com ela.

## D2 — Tabela `midias_recebidas`

Uma linha por mensagem IMAGEM ou DOCUMENTO recebida:

| coluna | tipo | |
| --- | --- | --- |
| `message_id` | UUID, PK | FK para `messages.id`, `ON DELETE CASCADE` |
| `media_id_da_meta` | `String(128)` | o id que a Graph API resolve |
| `mime_type` | `String(128)` | o declarado no envelope |
| `sha256` | `String(64)`, nulável | o do envelope, conferido no download |
| `bytes` | `BigInteger`, nulável | o tamanho real, gravado ao armazenar |
| `chave_no_armazem` | `String(255)`, nulável | nula até ARMAZENADA |
| `status` | `String(16)` | PENDENTE, ARMAZENADA, RECUSADA ou FALHOU |
| `motivo` | `String(32)`, nulável | vocabulário curto (`tipo_nao_permitido`, `acima_do_teto`, `sha256_divergente`, `recusada_pela_meta`, `tentativas_esgotadas`, `expirada`) |
| `criado_em`, `atualizado_em` | `timestamptz` | |

**`motivo` saiu como `String(32)`, e não `String(64)` como esta tabela dizia antes** (desvio deliberado, feito na Task 3): o maior literal do vocabulário acima (`tentativas_esgotadas`) tem 20 caracteres, e `tarefas_de_corretor.motivo` (migration 0039) já usa `String(32)` para o mesmo tipo de vocabulário curto — repetir `String(64)` aqui teria sido a exceção, não o padrão.

**Tabela à parte, e não colunas em `messages`**, porque só mídia tem estes campos, e porque o estado do download muda depois de a mensagem ter sido gravada. O "ponteiro junto à mensagem" da card é esta FK.

O nome do arquivo do documento **não** vira coluna: ele fica cifrado em `raw_payload`, onde já está.

**Só IMAGEM e DOCUMENTO.** Áudio é a TEC-131. Vídeo, figurinha e localização continuam DESCONHECIDO, sem download.

## D3 — Ingestão e download

**Parser.** `image.caption` e `document.caption` passam a ser o `text_body`. Com isso, a legenda passa por tudo o que texto já passa: moderação, opt-out, pedido de humano e turno.

**Ingestão.** Para cada mensagem IMAGEM ou DOCUMENTO recém-gravada, o `IngestionService`:
- grava a linha PENDENTE em `midias_recebidas`, com `media_id`, `mime_type` e `sha256` tirados do envelope;
- enfileira o job `baixar_midia` com `_job_id=f"midia:{message_id}"`.

O turno é enfileirado como sempre, em paralelo, **sem esperar o download**.

**O job `baixar_midia`:**
1. `GET {whatsapp_api_base}/{media_id}`, com o bearer já configurado, devolve `url`, `mime_type` e `file_size`.
2. **Antes de baixar**, confere a allowlist e o teto. A allowlist é JPEG, PNG e WebP; PDF, DOC/DOCX e XLS/XLSX. O teto é configurável, com padrão de 25 MB. Fora de qualquer um dos dois, grava RECUSADA com o motivo e não baixa.
3. `GET url`, com o bearer, **em streaming**, abortando se passar do teto, mesmo que o `file_size` tenha mentido.
4. Confere o `sha256` contra o do envelope. Divergente, grava FALHOU.
5. Cifra, `armazem.guardar`, e grava ARMAZENADA com a chave e o tamanho.

**Falhas:**
- Um 5xx ou erro de rede vira `Retry` do ARQ com backoff, até 5 tentativas.
- Um 4xx grava FALHOU sem retentar: é mídia expirada ou token inválido.
- Esgotadas as tentativas, FALHOU com `tentativas_esgotadas`.
- **Nada disso toca a conversa.**

**Enfileiramento perdido.** Um cron próprio, `sweep_midias_pendentes`, roda de 5 em 5 minutos: re-enfileira as linhas PENDENTE com mais de 10 minutos e menos de 7 dias. As com mais de 7 dias viram FALHOU com `expirada`, porque a mídia da Meta provavelmente já não existe. *Ajuste feito ao escrever o plano:* a versão aprovada punha isso como um passo da `sweep_stalled`, mas ela varre `messages` a cada 30 segundos com um contrato documentado sobre `attempts` e status da mensagem. Misturar outra tabela nela obrigaria a reescrever esse contrato. A intenção é a mesma.

**Logs** levam `message_id`, `status` e `motivo`. **Nunca** a URL da Meta, que carrega credencial temporária, nem o nome do arquivo.

## D4 — O turno

**Sem nenhum texto do lead na rajada pendente, a resposta é fixa.** Isso vale depois das guardas de opt-out, atendimento humano e conversa encerrada, e antes da moderação e do modelo. Não há chamada paga, e não há como afirmar nada sobre o conteúdo.
- O envio usa `_entregar_texto_fixo` com `kind` próprio (`confirmacao_de_midia`), e herda a apresentação do agente no primeiro contato.
- **Imagem:** "Recebi sua imagem! Por aqui eu ainda não consigo ver fotos. Me conta em texto qual imóvel ou característica te interessou?"
- **Documento:** "Recebi seu arquivo! Por aqui eu ainda não consigo abrir documentos. Me conta em texto o que você precisa, que eu te ajudo?"

**"Na rajada pendente", e não só na mensagem do turno.** Com "quero esse" e depois a foto, o debounce agrupa as duas, e o turno roda na última, que é a foto. Uma resposta fixa ali deixaria o "quero esse" sem resposta. Então: **havendo texto do lead em qualquer mensagem pendente desde a última fala do agente** (o mesmo recorte de `ha_fala_pendente_antes`, em `domain/messages/rajada.py`), roda o turno normal. Três fotos seguidas sem texto rendem uma resposta fixa só, porque as anteriores fecham "agrupado", como hoje.

**Com legenda, ou com texto na rajada, o turno é o normal, e o modelo vê a mídia marcada:**

```
[LEAD] (imagem recebida; o conteudo nao esta visivel para voce) esse aqui ta disponivel?
[LEAD] (documento recebido; o conteudo nao esta visivel para voce)
```

Os marcadores são texto para o modelo, e não para o lead, por isso vão sem acento. Ficam em `_SEM_TEXTO`, em `montagem.py`, e passam a valer também quando há legenda. Custam alguns tokens de contexto por mídia e **nada** no prompt de sistema.

**O turno não espera o download e não lê a mídia.** O status em `midias_recebidas` não muda a resposta: "recebi" é verdade mesmo se o download falhar depois.

## Emenda ao SRS

**RN-01.4 E-01**, aninhada abaixo da regra:
- a mídia é guardada fora do banco, cifrada pela aplicação;
- só IMAGEM e DOCUMENTO são guardados;
- a legenda é tratada como texto;
- sem texto do lead, a confirmação é uma mensagem fixa;
- o download é assíncrono, e a confirmação não depende dele.

## Testes

- **Unitários:**
  - a legenda no parser (imagem e documento);
  - bytes cifrados e decifrados voltam iguais, e AAD errado reprova;
  - allowlist e teto;
  - marcadores do contexto, com e sem legenda.
- **Integração:**
  - a ingestão cria PENDENTE e enfileira;
  - `ArmazemLocal` faz ida e volta;
  - o job contra a Graph API falsa (`httpx.MockTransport`): sucesso, `sha256` divergente, 4xx, 5xx com retry, estouro do teto no streaming e tipo fora da allowlist;
  - a varredura re-enfileira PENDENTE antiga e fecha as de mais de 7 dias;
  - `ArmazemS3` contra um cliente falso.
- **Turno:**
  - imagem sem legenda recebe o texto fixo, e o modelo não é chamado;
  - documento recebe o texto dele;
  - lead em opt-out não recebe nada;
  - rajada com texto roda o turno normal;
  - imagem com legenda roda o turno normal com o marcador.
- **Features — os três cenários da card:**
  - *Reconhecer imagem recebida sem interpretá-la:* linha IMAGEM + `midias_recebidas` ARMAZENADA depois do job; o texto fixo saiu.
  - *Pedir por texto a informação que a mídia traria:* a imagem sem texto recebe a pergunta.
  - *Documento recebido segue a mesma regra:* PDF, DOCUMENTO, ARMAZENADA, texto fixo de documento.

## O que esta card não entrega

- **Retenção.** A mídia fica guardada sem prazo. A RNF-22 manda eliminar em 12 ou 24 meses, e não existe job de retenção, que é a TEC-207. É a mesma dívida das transcrições.
- **Leitura da mídia.** Não há endpoint nem tela. O "acesso restrito" desta card é não existir caminho de leitura, mais o arquivo cifrado. Autorização por papel quando o dashboard mostrar a mídia é a TEC-202, e a tela é a TEC-193.
- **Com legenda, "não afirmar nada sobre o conteúdo" é probabilístico.** O modelo é avisado de que não vê a mídia, mas pode chutar. Sem legenda a garantia é total, porque o texto é fixo.
- **Dado sensível em documento** (RG, holerite). A RNF-20 pede redação antes de persistir, e isso exige ler o documento, o que está fora do MVP (RN-01.4). O documento fica guardado cifrado.
- **S3 real.** O `ArmazemS3` é testado contra cliente falso. Bucket, credenciais e política de acesso de produção são da TEC-219.
- Vídeo, figurinha e localização. Mídia pelo widget web.
- **Falha que não é `Retry` some sem contador.** O `job_timeout` global do worker (240s, `workers/main.py`) cobre `baixar_midia` como cobre todo job, e um arquivo enorme ou uma rede lenta o suficiente para estourá-lo — assim como um erro de banco no próprio `marcar()` que grava o desfecho — não passa pelo `except graph.MidiaIndisponivel` que decide `Retry`: a linha fica PENDENTE, sem nada gravado. `midias_recebidas` não tem `attempts` (D2), então nada aqui conta essas tentativas; o único efeito é a `sweep_midias_pendentes` reenfileirando a mesma linha a cada 5 minutos, até os 7 dias em que `expirar_pendentes` a fecha como FALHOU/EXPIRADA. Declarado, não corrigido nesta card.
- **O log do `httpx` baixou para WARNING, para toda chamada HTTP do processo.** `app/logging.py` (`configure_logging`) chama `logging.getLogger("httpx").setLevel(logging.WARNING)` porque a linha `HTTP Request: GET <url>` que o `httpx` loga em INFO vazaria a URL de download da Meta — credencial temporária — a cada mídia baixada (D3: "nunca a URL"). O corte é por logger, não por chamada: qualquer outro cliente `httpx` do processo (WhatsApp, moderação, embeddings) perde a mesma linha de INFO, e é um efeito colateral aceito, não uma escolha sobre aquelas integrações.
- **Áudio no meio de uma rajada de mídia sem texto não recebe turno próprio.** Foto e áudio no mesmo debounce, sem nenhum texto do lead: o turno roda sobre a ÚLTIMA mensagem da rajada (D4), e se ela for a foto, a resposta fixa que sai é a de imagem — o áudio fecha "agrupado" junto, sem qualquer resposta sua e sem o turno normal que o trataria. É consequência do mecanismo de rajada existente (RN-01.6) combinado com a resposta fixa desta card, não uma regra nova que a TEC-132 decidiu — e não há teste de aceite que a exercite.

# TEC-131 — Transcrever áudio recebido de até 120 segundos

**Status:** desenho, implementado nesta branch
**Card:** [TEC-131](https://eduardodurieuxlopes.atlassian.net/browse/TEC-131) — épico TEC-123
**Branch:** `feat/tec-131-transcrever-audio`
**Origem:** RF-01, RN-01.3 (SRS v1.0).

## Objetivo

Quem manda áudio pelo WhatsApp é atendido como se tivesse escrito. O áudio de até 120 segundos vira texto e segue o caminho de qualquer texto. O áudio mais longo não é transcrito e recebe um pedido cordial para escrever. Se a transcrição falhar, o lead também recebe o pedido para escrever. O áudio original fica guardado, cifrado, e a transcrição fica registrada na própria mensagem.

## O que o repo tem, medido sobre `ec64c0a`

1. **O áudio já vira linha.** `parse_meta_envelope` grava AUDIO com `text_body` nulo, e o envelope, com `audio.id`, `mime_type`, `sha256` e `voice`, vai cifrado em `raw_payload`.
2. **Nada o baixa.** `linha_pendente` (`midia/repositorio.py`) só conhece IMAGEM e DOCUMENTO. O comentário ali diz "audio e a TEC-131".
3. **O turno vê `[LEAD] (audio, sem transcricao)`** (`_SEM_TEXTO`, `context/montagem.py`) e responde livremente.
4. **O OpenAI já é provedor do projeto.** `openai>=1.0` está no `pyproject.toml` (3.19.2 na venv) e `OPENAI_API_KEY` já é exigida em produção por causa dos embeddings (TEC-157). A Whisper API que o SRS escolhe (tabela de stack) sai do mesmo SDK e da mesma chave.
5. **O turno não tem folga para esperar download nem transcrição.** `test_o_pior_turno_cabe_no_job_timeout` soma 207s contra o `job_timeout` de 240s, e `test_a_folga_paga_o_banco` exige que sobrem 30s. Sobram 3s. Resolver e baixar na Graph API custa até 10s cada; uma chamada à Whisper, dezenas de segundos. Subir o `job_timeout` arrasta `sweep_inflight_after_seconds` e a carência do deploy, que foi exatamente o que a TEC-290 evitou.

## D1 — A transcrição é um job próprio, e o turno espera por ele sem ser reivindicado

O job `transcrever_audio` é enfileirado pela ingestão, sem atraso, ao lado do turno. O turno continua sendo enfileirado como sempre, com o debounce.

**Por que não dentro do turno:** pelo item 5. Um job à parte tem o próprio `job_timeout` e não toca a conta do turno.

**A espera.** No começo de `process_message`, **antes do claim**, o turno procura, na rajada, um áudio ainda sem desfecho de transcrição. A rajada é a conversa do lead, de depois da última fala do agente até esta mensagem, inclusive. Achando um, o job devolve `aguardando_transcricao` sem reivindicar nada: a linha continua QUEUED e nenhum estado muda.

Quem o acorda é o próprio `transcrever_audio`. Ao gravar qualquer desfecho, ele enfileira `process_message` para a INBOUND mais nova da conversa, sem atraso. O `_job_id` é próprio, `msg:{id}:audio:{audio_id}`, e não o `msg:{id}` de sempre, por uma corrida concreta: o turno que acabou de decidir esperar ainda pode estar em execução nesse instante, e enquanto ele roda o ARQ recusa um segundo job com o mesmo id. Com um id à parte, o pior caso é o turno rodar duas vezes, e o claim da TEC-218 faz a segunda passada sair `skipped`.

**Por que a mensagem mais nova, e não o próprio áudio.** Com um áudio seguido de "?", o "?" é quem responde a rajada (RN-01.6), e o áudio fecha "agrupado". Se o áudio acordasse só a si mesmo, fecharia agrupado e o "?", que esperava por ele, ficaria sem turno.

**A espera tem prazo.** Um áudio cuja linha em `midias_recebidas` nasceu há mais de `PRAZO_DA_TRANSCRICAO` (90s) deixa de segurar o turno. O prazo cobre o pior caso do job: até 10s para resolver, o download, e 30s da Whisper, sem retentativa. Passado o prazo, o turno roda sem a transcrição, e o áudio aparece como `(audio, sem transcricao)`. Só chega aqui um job de transcrição que se perdeu: enfileiramento que falhou ou worker que morreu. Nesse caso ninguém acorda o turno, e quem o recupera é o `sweep_stalled`, com a mensagem QUEUED há mais de 300s. **Esse é o pior caso: cinco minutos de silêncio**, e só quando o job de transcrição some.

**Alternativas descartadas:**
- **`Retry` do ARQ no `process_message`.** Consome o `max_tries` global de 5, que também decide as retentativas de cancelamento. Com esperas de 2s, esgotaria em 10s.
- **Dormir dentro do job.** O `asyncio.sleep` conta no `job_timeout` como qualquer chamada, e a folga é de 3s.
- **A ingestão deixar de enfileirar o turno do áudio.** Não resolve a rajada: o "?" que vem depois do áudio continuaria podendo rodar antes da transcrição, e o áudio fecharia agrupado.

## D2 — O job `transcrever_audio`

1. **Ler a linha** de `midias_recebidas`. Sem linha, ou com transcrição já decidida, devolve `nada_a_fazer`. É isso que torna o job idempotente.
2. **Obter os bytes.** Se a mídia já está ARMAZENADA, lê do armazém e decifra. Se está PENDENTE, baixa pela Graph API com a mesma sequência de `baixar_midia`: resolver, allowlist, teto, download em streaming, `sha256`, cifrar e guardar. Grava ARMAZENADA por `marcar`, que só muda linha PENDENTE. A função de download de `baixar_midia` passa a ser compartilhada. A allowlist ganha os tipos de áudio que o WhatsApp manda: `audio/ogg`, `audio/mpeg`, `audio/mp4`, `audio/aac` e `audio/amr`.
3. **Medir a duração antes de transcrever.** A nota de voz do WhatsApp é sempre Ogg/Opus. A duração sai da última página Ogg, lendo o *granule position* e descontando o *pre-skip* do cabeçalho `OpusHead`, sobre 48 kHz. É um parser de umas trinta linhas, sem dependência nova. O `mutagen`, que faria isso para todo formato, é GPL, e o produto não é.
4. **Acima do limite** (`transcricao_duracao_maxima_segundos`, padrão 120), grava RECUSADA com o motivo `acima_da_duracao`, **sem chamar a Whisper**.
5. **Dentro do limite**, chama `audio.transcriptions.create` com `model=transcricao_modelo` (padrão `whisper-1`), `language="pt"` e `response_format="verbose_json"`.
6. **Confere a duração de novo** com a que a Whisper devolve. Isso cobre os formatos em que o parser não mede, como MP3, M4A, AAC e AMR, que vêm de áudio encaminhado e não de nota de voz. **Nesses formatos, o áudio longo chega a ser transcrito** e a transcrição é descartada: o lead recebe a mesma recusa, mas o "não é transcrito" da card vale só para o Ogg/Opus.
7. **Grava o desfecho numa transação só:** o texto em `messages.text_body`, cifrado com o AAD que a coluna já usa, e o status da transcrição na linha de mídia. As duas escritas são condicionais, com `text_body IS NULL` e status da transcrição nulo, então duas passadas nunca sobrescrevem uma à outra.
8. **Acorda o turno** (D1).

**"Exatamente 120 segundos" é aceito, e a comparação é `duracao < limite + 1`.** A duração medida é fracionária: um áudio que o WhatsApp mostra como `2:00` pode ter 120,4s. Comparar com `<= 120` recusaria o áudio que a card manda aceitar. O corte é no segundo inteiro que o lead vê no contador.

**Falhas.** Um erro da Whisper, seja rede, 5xx, 4xx ou chave ausente, grava FALHOU com `servico_indisponivel`. Os outros casos:
- Mídia que a Meta não entrega, ou que o armazém não guarda: FALHOU com `midia_indisponivel`.
- Tipo que a Whisper não aceita (AAC cru e AMR): FALHOU com `formato_nao_suportado`, sem chamar.
- Transcrição vazia (áudio mudo): FALHOU com `transcricao_vazia`.
- Exceção inesperada: FALHOU com `erro_inesperado`, e a exceção sobe depois de acordar o turno.

**Nenhuma dessas falhas retenta.** O lead está esperando, e o que a card pede para a falha é o pedido de texto, não uma espera maior. A Whisper tem 30s e zero retentativas (`infra/transcricao.py`).

**"Registrada para reprocessamento"** é o registro durável: `status_da_transcricao = FALHOU`, com o motivo e a hora, mais um `log.warning("audio.transcricao_falhou")`. É isso que permite achar e reprocessar. **Não há job que reprocesse sozinho**, e isso é deliberado. Depois do pedido de texto, uma transcrição tardia chegaria ao contexto duplicando o que o lead já reescreveu. Ver "O que esta card não entrega".

**O download continua coberto pela varredura.** Se o job de transcrição morrer antes de guardar o áudio, a linha fica PENDENTE e a `sweep_midias_pendentes` a reenfileira em `baixar_midia` depois de 10 minutos, como faz com imagem. O áudio acaba guardado mesmo sem transcrição.

## D3 — Onde a transcrição mora

**A transcrição mora em `messages.text_body`.** É o "tratado como se fosse texto" da card, levado ao pé da letra. A partir dali, o áudio passa por tudo o que texto já passa:
- opt-out, pedido de humano e pedido de titular falados funcionam, inclusive no furo da rajada em `process_message`;
- moderação de entrada;
- o `com_texto` da confirmação de mídia (um áudio transcrito antes de uma foto conta como texto pendente);
- a tela de detalhe do lead;
- a retenção e a anonimização da TEC-207, que já esvaziam `text_body` e apagam a linha de mídia.

**O status fica em colunas novas de `midias_recebidas`** (migration `0067`):

| coluna | tipo | |
| --- | --- | --- |
| `status_da_transcricao` | `String(16)`, nulável | nula até o desfecho; TRANSCRITA, RECUSADA ou FALHOU |
| `motivo_da_transcricao` | `String(32)`, nulável | `acima_da_duracao`, `formato_nao_suportado`, `servico_indisponivel`, `midia_indisponivel`, `transcricao_vazia`, `erro_inesperado` |
| `duracao_segundos` | `Float`, nulável | a medida usada na decisão |
| `transcrita_em` | `timestamptz`, nulável | quando o desfecho foi gravado |

Nula quer dizer "ainda sem desfecho", e é o que a espera da D1 procura. Imagem e documento ficam com as quatro nulas, e a espera só olha para AUDIO.

**Nas colunas de mídia, e não em `messages`,** pela mesma razão da D2 da TEC-132: só áudio tem esses campos.

**Sem CHECK nos dois vocabulários**, pela razão que o docstring de `midia/models.py` já dá: nenhuma leitura compara literal cru.

## D4 — O turno

**Com transcrição, o turno é o normal.** O modelo vê o áudio marcado:

```
[LEAD] (audio transcrito) <texto delimitado>
```

O marcador é texto para o modelo, sem acento, e fica fora da tag do lead, como o de imagem. Existe para o modelo saber que erro de grafia pode ser erro de transcrição. Custa três tokens por áudio no contexto e nada no prompt de sistema.

**Sem transcrição, a resposta é fixa**, no mesmo ponto e com as mesmas guardas da confirmação de mídia da TEC-132 (D4 de lá):
- depois de opt-out, atendimento humano e conversa encerrada;
- antes da moderação e do modelo;
- e só sem texto do lead pendente na rajada.

A checagem de kinds reservados é a mesma da TEC-132, e é o que protege a retentativa. Os textos saem com acento, porque o lead os recebe (TEC-267):
- **Acima da duração:** "Recebi seu áudio! Por aqui eu só consigo ouvir áudios de até 2 minutos. Pode me mandar por escrito o que você precisa?"
- **Falha, ou prazo vencido:** "Recebi seu áudio, mas não consegui ouvir direito. Pode me escrever o que você disse?"

Os dois saem com o kind `aviso_de_audio` e o subagente `audio`.

**Sem a regra do "já confirmou há pouco".** Na imagem, a segunda foto em silêncio não perde nada: o "recebi" da primeira vale para as duas. No áudio, cada aviso diz o que aconteceu com *aquele* áudio. Quem recebe "até 2 minutos" e manda um de 1:50 que falha não pode ficar em silêncio. O subagente próprio (`audio`, e não `midia`) mantém as duas regras separadas: um aviso de áudio não silencia a confirmação da foto seguinte.

**Com texto pendente e áudio sem transcrição, o turno é o normal** e o modelo vê `(audio, sem transcricao)`. Como na legenda da TEC-132, pedir para o lead repetir fica a critério do modelo.

## Emenda ao SRS

**RN-01.3 E-01 (TEC-131, 27/09/2026)**, aninhada abaixo da regra:
- a transcrição é assíncrona, e o turno a espera por até 90s;
- a duração se mede antes de transcrever na nota de voz (Ogg/Opus), e depois nos outros formatos;
- o limite aceita até o 120º segundo inteiro;
- a transcrição vira o texto da mensagem;
- o áudio longo, ou o que falha, recebe um texto fixo pedindo para escrever;
- o áudio é guardado como a mídia da RN-01.4 E-01.

## Testes

- **Unitários:**
  - duração do Ogg/Opus: com pre-skip, em arquivo truncado e em não-Ogg;
  - a regra do limite em 119,9, 120,0, 120,9 e 121,0;
  - o marcador `(audio transcrito)`;
  - `linha_pendente` para áudio.
- **Integração:**
  - o job contra a Graph API falsa e um transcritor duble: transcrito; longo sem chamar a Whisper; longo pela duração que a Whisper devolve; Whisper fora do ar; formato não suportado; vazio; já ARMAZENADA, lendo do armazém; idempotência;
  - a espera em `process_message`: espera, e passa depois do prazo;
  - a ingestão enfileira `transcrever_audio`.
- **Features, um por cenário da card:**
  - 40s: transcrição em `text_body` e o classificador recebendo o texto falado;
  - 150s: sem chamada à Whisper e com o aviso de duração;
  - 120s exatos: transcrito;
  - Whisper indisponível: o aviso de falha, e FALHOU registrado.

## O que esta card não entrega

- **Reprocessamento automático.** A falha fica registrada (D2), mas nada a retenta. Reprocessar hoje é enfileirar `transcrever_audio` à mão, depois de zerar `status_da_transcricao`, e a transcrição tardia entra no contexto dos turnos seguintes.
- **Opt-out falado não fura o debounce.** A ingestão só vê texto, e o áudio espera a janela e a transcrição antes de o turno ler o "pare". O opt-out é registrado mesmo assim: só chega alguns segundos mais tarde que o escrito.
- **Nos formatos que não são Ogg/Opus, o áudio longo é transcrito antes de ser recusado** (D2, passo 6). O lead não vê diferença; a diferença é o custo de uma chamada à Whisper e a transcrição descartada.
- **AMR e AAC cru não são transcritos**, porque a Whisper não os aceita. O lead recebe o aviso de falha. É raro: a nota de voz é sempre Ogg.
- **Pior caso de cinco minutos de silêncio** quando o job de transcrição se perde (D1).
- **Áudio pelo widget web.** O widget só aceita texto.
- **Custo.** A Whisper cobra por minuto de áudio, e esta card não entra no painel de custo.
- **Os tetos da Whisper não foram medidos.** Os 30s são estimativa, pelo mesmo motivo que o `TETO_DA_CONSULTA_DO_TURNO` dos embeddings registra: não há chave do OpenAI nesta máquina para sondar.

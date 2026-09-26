# TEC-203 — Cifrar o dado pessoal do lead e proteger os segredos

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-203](https://eduardodurieuxlopes.atlassian.net/browse/TEC-203) — épico TEC-200
**Branch:** `feat/tec-203-cifra-e-segredos`
**Origem:** RNF-13, RNF-14 e RT-08 do SRS v1.0 (`docs/srs/srs-agente-sdr-imobiliario-v1.0.md`).

## O que já existia e o que falta

| Regra da card | Antes desta card | Nesta card |
|---|---|---|
| AES-256 em repouso | AES-256-GCM com AAD (`src/mobia/infra/crypto.py`) em mensagens, resumos, TOTP e mídia. **O telefone do lead, em claro**: é o `conversation_key` de ~20 tabelas | Telefone cifrado; `conversation_key` vira blind index (D2–D4) |
| Backups cifrados | Não há backup nem deploy | Fica com a TEC-219 (criptografia de snapshot do provedor) |
| TLS 1.3 em trânsito | A app não termina TLS; Postgres e Redis sem TLS exigido | TLS 1.3 exigido em produção para Postgres e Redis (D6). Borda: TEC-219 |
| Segredos no secret manager | Env e `.env` | Env e arquivo montado; `.env` recusado em produção (D5). Provedor concreto: TEC-219 |
| Rotação a cada 90 dias | Só o byte de versão do blob, reservado para isso | Keyring da chave de conteúdo, reindexação da chave de índice, aviso de vencimento (D1) |
| `gitleaks` bloqueante | Ausente | Job no CI com autoteste (D7) |

A TEC-219 declara que destrava a TEC-203 "apenas na parte de ambiente; os dois gates em si rodam no CI que já existe". O corte acima segue essa fronteira: esta card entrega tudo o que é código e registra como não exercitado o que depende de nuvem escolhida. **Não se inventa provedor para satisfazer critério.**

## Decisões tomadas com o Eduardo no desenho

1. **O telefone do lead é cifrado, com blind index** — e não mantido em claro com criptografia de disco. Isso revoga, para o lead, a doutrina da Emenda E-01 ("o que este sistema cifra é conteúdo, nunca identificador"). Corretor e usuário continuam em claro: a card fala do lead.
2. **Uma card, uma branch**, com commits ordenados por entrega.
3. **A busca do dashboard por telefone passa a exigir o número completo.** Substring (`ilike('%9876%')`) não funciona sobre HMAC; guardar índice dos últimos dígitos vazaria agrupamento e seria mais uma coluna a rotacionar.

## D1 — Chaves e rotação

### Keyring da chave de conteúdo

- Config nova: `CONTENT_ENCRYPTION_KEYS`, mapa `id → chave base64`, e `CONTENT_ENCRYPTION_KEY_ATIVA`, o id que cifra. O id é a data de criação (`20260926`), o que dá a idade da chave sem campo a mais.
- **Blob v2:** `versão=2 ‖ id da chave (4 bytes) ‖ nonce(12) ‖ ciphertext ‖ tag(16)`. Toda gravação nova sai em v2 com a chave ativa.
- **v1 continua decifrando**, mapeado para a chave legada. A config antiga `CONTENT_ENCRYPTION_KEY` vira a chave legada: quem já roda sobe sem mudar nada.
- O id vai dentro do blob, e não no AAD, porque é ele que escolhe a chave; adulterar o id escolhe outra chave e o blob não autentica.
- Id ausente do keyring é `DecryptionError` com a mesma disciplina de `crypto.py::decrypt_bytes`: a mensagem não carrega blob nem AAD.
- `crypto.py::marca_do_aad` passa a derivar a subchave da chave ativa. A docstring dela já aceita que as marcas mudem numa rotação.

**Procedimento:** acrescentar a chave e torná-la ativa → `scripts/recifrar.py` reescreve, em lotes e com o serviço de pé, todo blob de outra chave → a chave velha sai quando o script relatar zero blobs com ela.

### Chave de índice

- Config nova: `LEAD_INDICE_CHAVE`, própria, pela regra que `referencia.py` já registra — chaves com funções diferentes não se reaproveitam. Também leva id com data.
- **A rotação dela é a reindexação** (D3): o mesmo código do backfill, apontado para a chave nova. Como reescreve PK de ~20 tabelas, **roda com webhook e worker parados**. É janela de manutenção documentada, não operação quente — o preço honesto do blind index.

### Chave do `lead_ref`

Continua própria. A reindexação recalcula `eventos_auditoria.lead_ref` (a identidade guarda o valor original), então a afirmação da docstring de `referencia.py` de que a chave "não pode rodar" deixa de ser verdade e sai de lá.

### Demais segredos

- `JWT_SEGREDO`: rotação é troca de valor; derruba as sessões ativas, e isso se aceita. Keyring de JWT seria YAGNI.
- Tokens de WhatsApp, Anthropic, Google, CRM, SMTP: rotacionam no provedor deles; entram no runbook.

### Os 90 dias

Em produção, na subida, chave de conteúdo ativa ou chave de índice com id de mais de 90 dias gera log `seguranca.rotacao_vencida` em nível de **aviso**. Não reprova a subida: derrubar produção porque uma data passou é pior que o risco que a regra mitiga. O agendamento da rotação é do runbook e do provedor.

## D2 — A identidade do lead

Tabela nova `identidades_de_lead`:

| coluna | tipo | |
|---|---|---|
| `channel` | `String(32)` | PK |
| `conversation_key` | `String(64)` | PK — o HMAC |
| `valor_cifrado` | `LargeBinary` | o valor original, AES-256-GCM, AAD `identidade:{channel}:{conversation_key}` |
| `criado_em` | `timestamptz` | |

`conversation_key = HMAC-SHA256(LEAD_INDICE_CHAVE, f"{channel}:{valor}")` em hex — 64 caracteres, cabe no `String(64)` que as tabelas já têm. **Nenhuma coluna muda de tipo**, e o código do meio, que só compara igualdade, não muda.

Vale igual para o canal web: a sessão (UUID) também vira HMAC e é revelada para achar o canal Redis. Um mecanismo, sem caso especial por canal.

Módulo novo `src/mobia/domain/identidade/indice.py`, único lugar que conhece a chave de índice:

- `chave_de(channel, valor)` — o HMAC. No WhatsApp normaliza antes com `identidade/telefone.py::normalizar`.
- `registrar(sessao, channel, valor)` — upsert da identidade; devolve a chave.
- `revelar(sessao, channel, chave)` — decifra. É a única porta para o valor em claro. Identidade ausente levanta erro explícito; nunca devolve a própria chave como se fosse telefone.

O AAD do resumo (`context/models.py::aad_do_resumo`) já é montado sobre `(channel, conversation_key)`; passa a sê-lo sobre o HMAC, e a reindexação recifra `conversation_summaries`.

## D3 — Reindexação: migration `0058` e `scripts/reindexar_leads.py`, o mesmo código

1. Para cada par distinto `(channel, valor_antigo)` nas tabelas da lista: calcula a chave nova e grava a identidade.
2. `UPDATE t SET conversation_key = :novo WHERE channel = :c AND conversation_key = :antigo` em cada tabela de `TABELAS_COM_CHAVE_DE_LEAD` — lista que vive num lugar só.
3. Colunas fora do padrão:
   - `messages.sender_external_id`, só nas mensagens de entrada (na saída é o `phone_number_id` do canal, não dado do lead);
   - `rate_limit_events.chave`;
   - `vinculos_de_sessao.telefone` sai; entram `telefone_cifrado` e `telefone_indice`, este com a mesma chave e a mesma normalização do WhatsApp, para a absorção casar;
   - `eventos_auditoria.lead_ref`, recalculado;
   - `conversation_summaries`, recifrado com o AAD novo.
4. **Tabelas imutáveis.** `lead_score_audit` (0012), `conversation_intent_audit` (0035) e `eventos_auditoria` (0053) têm trigger que recusa UPDATE — e as duas primeiras guardam o telefone em claro. A reindexação faz `ALTER TABLE ... DISABLE TRIGGER` e `ENABLE` **na mesma transação**, só nessas três. É exceção declarada: trocar o pseudônimo do lead não altera o fato registrado, e manter o telefone em claro numa tabela imutável seria a violação que esta card existe para eliminar. As docstrings das três migrations ganham a ressalva.
5. **Na migration**, o valor original vem da coluna em claro. **Na rotação**, vem da identidade, decifrada, e a chave antiga é o HMAC com a chave velha. É a única diferença entre os dois usos.

**Guarda:** um teste varre os modelos e reprova se houver coluna `conversation_key` fora de `TABELAS_COM_CHAVE_DE_LEAD`. A próxima tabela não escapa da rotação em silêncio.

**Idempotência:** valor que já é chave registrada em `identidades_de_lead` é pulado. Reindexação interrompida se retoma rodando de novo — o que também cobre o banco com carimbo adiantado que o `CLAUDE.md` descreve.

**Downgrade:** revela todas as identidades e devolve o valor em claro às colunas, reabrindo as mesmas exceções de trigger. Coberto por teste, como todo downgrade do repo.

## D4 — As bordas

Regra: **o telefone em claro só existe em memória, no instante em que sai do processo por necessidade real.**

| Consumidor | Depois |
|---|---|
| Envio ao WhatsApp (os ~13 sítios que montam `"para"`) | O payload continua carregando a chave; `outbound/whatsapp.py` revela ao montar o `to`. Os sítios não mudam |
| Canal web (`outbound/web.py::canal_da_sessao`) e presença | Revelam no mesmo ponto do adaptador |
| CRM (`crm/payload.py`) | **Recebe o telefone revelado** — o CRM existe para o corretor ligar |
| Dossiê para o LLM (`handoff/dossie.py`, `handoff/contingencia.py`) | **O telefone sai do prompt.** O resumo não precisa dele; reduz o RT-08 |
| Link da transcrição (`handoff/resumo.py`) | Usa o apelido opaco de `referencias_de_lead` (TEC-195); o telefone some da URL, do e-mail e do access log |
| E-mails de agendamento (`agendamento/mensagens.py`) | **Telefone revelado** — o corretor precisa dele para a visita |
| Dashboard, listagem | Revela por linha da página e mascara |
| Dashboard, revelar (`leads/repositorio.py::valor_revelado`) | Passa por `revelar`; a auditoria de acesso continua |
| Dashboard, busca | Normaliza e compara pelo HMAC, em `conversation_key` e em `vinculos_de_sessao.telefone_indice`. Só número completo |
| Absorção web→WhatsApp (`identidade/absorcao.py`) | Casa `telefone_indice` com a chave do WhatsApp; não revela nada |
| Rotas com o par (`/assumir`, `/devolver`, auditoria `?conversationKey=`) | Recebem o apelido opaco; o telefone sai da query string |
| `admin/reativar.py --key` | Aceita o telefone e calcula a chave — ferramenta de operador |
| Entrada | `registrar` antes de persistir em `messages/service.py::IngestionService._persist` e em `api/routes/widget.py`; o rate limit de `messages/service.py::IngestionService.ingest` passa a usar a chave |
| Redis de rate limit | Chaves passam a usar o HMAC; as antigas expiram sozinhas |
| Logs | Máscara inalterada; mascarar pseudônimo é inofensivo |

Identidade ausente no envio é bug de dado: o adaptador levanta erro e o despacho falha pelo caminho de erro que já existe. Nada é enviado para um HMAC.

## D5 — Leitura de segredos

Todo secret manager de plataforma entrega segredo por variável de ambiente ou arquivo montado. A app aceita as duas e recusa a terceira:

- **Em produção o `.env` não é lido** — `env_file` só vale fora de produção.
- `secrets_dir` do pydantic-settings, via `MOBIA_SECRETS_DIR`: um arquivo por segredo, no formato de Docker, K8s e ECS.
- As guardas de produção que já existem (`ConfiguracaoInsegura`) estendem-se a `LEAD_INDICE_CHAVE` e ao keyring.

O cliente do secret manager concreto é da TEC-219.

## D6 — TLS

- **Postgres, em produção:** o engine usa `SSLContext` com `minimum_version = TLSv1_3` e verificação de certificado.
- **Redis, em produção:** exige `rediss://`, piso 1.3, na API e no ARQ.
- **Fora de produção nada muda** — o compose local segue sem TLS.
- **APIs de terceiros** (Meta, Anthropic, Google, SMTP, CRM): piso padrão do `ssl`, que negocia 1.3 quando o servidor oferece. Forçar 1.3 num servidor que não controlamos derrubaria a integração no dia em que ele oferecer só 1.2. **Divergência do "todos os canais" da card**, registrada como emenda.
- **Borda (widget e painel):** o TLS termina no proxy do provedor — TEC-219.

## D7 — gitleaks

- Job novo no `ci.yml`, com o **binário fixado por versão e checksum** — a `gitleaks-action` v2 exige licença paga em repositório de organização.
- Em PR, varre o intervalo de commits do PR; na `main`, o histórico inteiro.
- `.gitleaks.toml` estende as regras padrão, com allowlist **por valor exato** para os defaults de desenvolvimento commitados de propósito — nunca por arquivo, para que um segredo real colado no `config.py` continue sendo pego.
- **Autoteste no mesmo job**, no molde da sentinela do `verificar:bundle` (TEC-302): planta uma chave falsa num diretório temporário e exige que o gitleaks reprove. Sem ele, uma allowlist larga demais deixaria o gate verde para sempre.
- **Bloquear o merge** exige o job como *required check* na branch protection — configuração do repositório, feita pelo Eduardo; o PR traz o comando.
- **Antes de ligar o gate, o histórico inteiro é varrido localmente.** Segredo real antigo encontrado para o trabalho e volta ao Eduardo: rotacionar e reescrever histórico é decisão dele.

## Runbook

`docs/seguranca/segredos.md`: quais segredos existem, onde vivem, como rotacionar cada tipo (keyring, reindexação, troca simples, provedor) e a cadência de 90 dias.

## Testes

- **Unitários:** keyring (v1 legado decifra, v2 grava com a ativa, id desconhecido e id adulterado reprovam); `chave_de` (determinística, normalização, domínio por canal); aviso dos 90 dias; guardas de produção (`.env` ignorado, TLS exigido, chaves default recusadas).
- **Integração:** reindexação sobre banco semeado com telefones em claro em todas as tabelas da lista, inclusive as imutáveis — depois, nenhuma coluna contém o número e a trigger volta ligada (um UPDATE reprova); duas execuções dão o mesmo resultado; upgrade e downgrade devolvem os valores originais; envio revela o `to` certo e identidade ausente é erro; absorção casa; busca por número completo acha e por substring não.
- **Guarda** de `TABELAS_COM_CHAVE_DE_LEAD`.
- **Os ~121 arquivos de teste existentes** usam strings como `conversation_key` e devem seguir passando, porque a chave é opaca para o meio. Os que afirmam o `to` enviado ou o link mudam junto, cada um justificado no commit.

## Critérios de aceite

| Cenário | Situação |
|---|---|
| Dado pessoal cifrado em repouso | Exercitado: integração inspeciona o banco depois de gravar um lead |
| Segredo commitado bloqueia o pipeline | Exercitado pelo autoteste; o bloqueio do merge depende do required check |
| Aplicação lê segredos do gerenciador | Parcial: env e arquivo montado, `.env` recusado em produção; provedor é da TEC-219 |
| Comunicação usa TLS 1.3 (widget) | Não exercitado: borda do provedor, TEC-219. Postgres e Redis exigidos em produção |
| Backup cifrado | Não exercitado: não há backup; provedor, TEC-219 |

## Emendas ao SRS

Aninhadas abaixo das regras, sem reescrever o texto de 22/08/2026:

- **E-01:** a doutrina "cifra-se conteúdo, nunca identificador" deixa de valer para o telefone do lead.
- **RNF-13:** TLS com terceiros tem piso negociado, não 1.3 forçado.
- **RNF-14:** a chave de índice rotaciona por reindexação em janela de manutenção.

## Ordem dos commits

1. gitleaks
2. leitura de segredos e guardas de produção
3. TLS
4. keyring e rotação
5. identidade e índice
6. bordas
7. migration `0058` e reindexação
8. runbook, emendas e docs

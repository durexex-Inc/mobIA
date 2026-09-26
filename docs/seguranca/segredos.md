# Segredos: quais são, como chegam e como rotacionar

Runbook de operação da TEC-203 (RNF-13, RNF-14). Descreve o código como ele está — `src/mobia/app/config.py`, `src/mobia/infra/`, `scripts/recifrar.py`, `scripts/reindexar_leads.py` — e não o plano. O provedor de nuvem e o secret manager concreto são da TEC-219; onde este texto diz "secret manager", vale qualquer um que entregue o segredo como variável de ambiente ou arquivo montado.

## Quais segredos existem

Os comandos de geração são os mesmos que as mensagens de erro dos validators de `Settings` imprimem.

| Variável | Para que serve | Guarda em produção | Como gerar |
|---|---|---|---|
| `CONTENT_ENCRYPTION_KEY` | Chave AES-256-GCM **legada**: decifra todo blob v1 e cifra enquanto não houver keyring. Também deriva a subchave de `marca_do_aad` quando não há chave ativa | Recusa o default de desenvolvimento | `python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"` |
| `CONTENT_ENCRYPTION_KEYS` | Keyring da chave de conteúdo: JSON `{"AAAAMMDD": "<base64 de 32 bytes>"}`. O id é a data de criação | Id tem de ser data válida, chave tem de ter 32 bytes, e nenhuma pode ser a de desenvolvimento | o mesmo comando acima, uma vez por chave |
| `CONTENT_ENCRYPTION_KEY_ATIVA` | O id do keyring que cifra toda gravação nova (blob v2) | Tem de estar no keyring; sem keyring, tem de ficar vazia | a data de hoje, `AAAAMMDD` |
| `LEAD_INDICE_CHAVE` | Chave do HMAC que vira o `conversation_key` do lead (blind index) e o `telefone_indice` do vínculo web | Recusa o default de desenvolvimento | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `LEAD_INDICE_CHAVE_ID` | Data de criação da chave de índice, só para o aviso dos 90 dias | Tem de ser data `AAAAMMDD`. **O default é `20260926`**: quem troca a chave e esquece o id recebe o aviso na data errada | a data de hoje |
| `AUDITORIA_CHAVE_DO_LEAD` | Chave do HMAC do `lead_ref` de `eventos_auditoria` | Recusa o default de desenvolvimento | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `JWT_SEGREDO` | Assina os JWT do dashboard | Recusa o default e qualquer valor com menos de 32 bytes | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `CATALOGO_ADMIN_TOKEN` | Libera `POST /api/v1/imoveis/importar`; vazio desliga a rota | Recusa o default de desenvolvimento | `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN` | Assinatura do webhook, verificação do webhook e envio pela Cloud API | **Nenhuma**: os defaults `dev-app-secret` e `dev-verify-token` não são recusados | app secret e access token no painel da Meta; o verify token é escolhido por nós e cadastrado lá |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Modelo do agente; embeddings | A da OpenAI é exigida pelo worker em produção | no provedor |
| `SMTP_SENHA`, `CRM_WEBHOOK_SECRET`, `GOOGLE_CALENDAR_CLIENT_SECRET`, `GOOGLE_CALENDAR_REFRESH_TOKEN` | Notificação ao corretor, assinatura do POST ao CRM, calendário | Nenhuma | no provedor |
| `DATABASE_URL`, `REDIS_URL` | Carregam a senha do banco e do Redis | TLS exigido — ver "TLS", abaixo | no provedor |

As credenciais do S3 de mídia não passam por `Settings`: o `aioboto3` usa a cadeia padrão da AWS.

## Como chegam à aplicação

`get_settings` (`src/mobia/app/config.py::get_settings`) aceita duas fontes e recusa a terceira:

- **Variável de ambiente.**
- **Arquivo montado**, no diretório que `MOBIA_SECRETS_DIR` aponta: um arquivo por segredo, com o nome do campo em minúsculas (`jwt_segredo`, `content_encryption_keys`) e o valor como conteúdo — o formato de Docker, Kubernetes e ECS. O keyring vai como o mesmo JSON da variável. Quando a mesma chave existe nas duas fontes, a variável de ambiente ganha.
- **O `.env` não é lido em produção.** A decisão olha `ENVIRONMENT` em `os.environ`, antes de construir `Settings`. Por isso `ENVIRONMENT` **tem de ser variável de ambiente**: escrito só no `.env` ou num arquivo montado, o validator `_recusar_producao_declarada_em_arquivo` recusa a subida com "veio de arquivo, nao do ambiente".

`AUDITORIA_CHAVE_DO_LEAD_ANTERIOR` é exceção: `scripts/reindexar_leads.py` a lê direto de `os.environ`, então ela só funciona como variável de ambiente, nunca como arquivo em `MOBIA_SECRETS_DIR`.

## TLS

Só em produção. Fora dela o `docker compose` local segue sem TLS.

- **Postgres:** o engine conecta com o contexto de `src/mobia/infra/tls.py::contexto_tls` — `ssl.create_default_context()` com `minimum_version = TLSv1_3`, o que verifica certificado e hostname. **A cadeia é validada contra o repositório de CAs do sistema**, porque o contexto não carrega CA própria: a CA do Postgres gerenciado tem de estar confiada na imagem. Qual provedor, e portanto qual CA, é decisão da TEC-219.
- **Redis:** `REDIS_URL` tem de começar com `rediss://`, ou API e worker recusam subir. O certificado e o hostname são verificados (`ssl_cert_reqs="required"` e `ssl_check_hostname=True`, em `src/mobia/infra/queue.py::redis_settings`), também contra as CAs do sistema. **O piso TLS 1.3 não é imposto no Redis**: o `RedisSettings` do ARQ 0.28 não expõe versão mínima de TLS.
- **APIs de terceiros** (Meta, Anthropic, OpenAI, Google, SMTP, CRM): piso padrão do `ssl` do Python, que negocia 1.3 quando o servidor oferece.
- **Borda** (widget e painel): o TLS termina no proxy do provedor — TEC-219.

## Rotação a cada 90 dias

Cada tipo de segredo tem um procedimento próprio, porque cada um é usado de um jeito.

### Chave de conteúdo (keyring)

Serve para trocar a chave AES que cifra mensagens, resumos, TOTP, identidades e vínculos. **Roda com o serviço de pé.**

1. **Acrescente a chave nova ao keyring, sem ativá-la**, em todas as réplicas de API e worker. Uma réplica que leia um blob cifrado com uma chave que ela não conhece reprova com `DecryptionError`; acrescentar antes de ativar é o que deixa o rollout gradual.
   - **Na primeira vez que o keyring entra, não há passo sem ativar:** com `CONTENT_ENCRYPTION_KEYS` preenchido, `CONTENT_ENCRYPTION_KEY_ATIVA` tem de apontar para uma chave dele. Reinicie todos os processos juntos, sem rolling, para nenhuma réplica sem keyring ler um blob v2.
2. **Ative a chave nova** (`CONTENT_ENCRYPTION_KEY_ATIVA=<id novo>`) e reinicie. Daqui em diante toda gravação sai em v2 com ela.
3. **Recifre o que ficou sob outra chave:**

   ```bash
   python scripts/recifrar.py --so-contar   # só conta, por coluna e por id de chave
   python scripts/recifrar.py               # reescreve com a chave ativa
   ```

   O script percorre as colunas de `src/mobia/admin/recifrar.py::COLUNAS_CIFRADAS` em lotes de 500, cada lote numa transação curta. No relatório, `None` é blob v1 (chave legada). **O número que decide é a última linha, `blobs fora da chave ativa (leitura de verificacao): N`** — ela vem de uma segunda passada, só de leitura, feita depois da escrita, e não do relatório da própria escrita (a docstring de `scripts/recifrar.py` explica por que o relatório da escrita daria zero mesmo se ela tivesse parado no meio).
   - Se a última linha não der zero, alguma réplica ainda está gravando com a chave velha como ativa. Confira a configuração de todas e rode de novo.
4. **Remova a chave velha do keyring só quando a verificação der zero e não houver mais mídia gravada com ela.** O `recifrar` cobre as colunas cifradas do banco, **não os arquivos de mídia** (`.midias/` ou o bucket S3, TEC-132): eles continuam sob a chave com que foram gravados. Não há ferramenta que conte mídia por chave — na dúvida, a chave fica no keyring.

A chave legada `CONTENT_ENCRYPTION_KEY` não sai nunca da configuração de produção, mesmo depois que nenhum blob v1 restar: sem ela, o campo cai no default de desenvolvimento, que o validator recusa.

Trocar a chave ativa também troca a subchave de `marca_do_aad`, o identificador curto de AAD que aparece nas mensagens de erro de cifra. A correlação de log entre antes e depois da troca se perde, e isso é aceito (ver a docstring de `src/mobia/infra/crypto.py::_chave_da_marca`).

### Chave de índice (`LEAD_INDICE_CHAVE`)

O `conversation_key` de ~20 tabelas é o HMAC do telefone (ou da sessão web) com esta chave. Trocá-la é reescrever todas essas chaves, inclusive as de chave primária — **janela de manutenção, com a aplicação parada.**

1. **Pare a API e o worker.** A API é quem serve o webhook do WhatsApp e o widget; nenhum processo pode ficar conectado. Três razões:
   - a reindexação roda numa transação só e desliga as triggers de imutabilidade de `lead_score_audit`, `conversation_intent_audit` e `eventos_auditoria` até o commit. `ALTER TABLE ... DISABLE TRIGGER` toma `SHARE ROW EXCLUSIVE` nas três (medido no Postgres 16 em 26/09/2026): toda escrita nelas espera a transação acabar, e a API grava em `eventos_auditoria` a cada acesso auditado;
   - os `UPDATE` da reindexação travam as linhas de todas as tabelas com `conversation_key`, e uma escrita concorrente espera ou colide;
   - um processo com a chave velha continuaria gravando linhas sob o HMAC velho, que depois do commit não bateria com mais nada.
2. **Troque `LEAD_INDICE_CHAVE` e `LEAD_INDICE_CHAVE_ID`** (a data de hoje) no secret manager. **A chave velha não é necessária:** o script lê a chave atual de cada lead nas próprias linhas e o valor cru na identidade cifrada (`identidades_de_lead`), com a chave de conteúdo.
3. **Rode a reindexação** com a configuração nova:

   ```bash
   python scripts/reindexar_leads.py
   ```

   Ela imprime `N lead(s) reindexado(s)`. Numa transação só, move cada lead para a chave nova em todas as tabelas de `src/mobia/domain/identidade/reindexacao.py::TABELAS_COM_CHAVE_DE_LEAD`, e arrasta junto remetente e destinatário das mensagens, o evento de rate limit, o `lead_ref`, o AAD do resumo e do vínculo, a identidade e o prefixo do id de mensagem do widget; depois recalcula o `telefone_indice` dos vínculos. Se qualquer statement falhar, o rollback desfaz tudo, inclusive o `DISABLE TRIGGER`, e basta rodar de novo.
   - **O papel do banco que roda o script tem de ser dono das três tabelas de auditoria.** `ALTER TABLE ... DISABLE TRIGGER` exige ser dono; com outro papel o script reprova no `DISABLE TRIGGER`, antes de mexer em qualquer linha. Hoje a aplicação conecta como dono (ver a docstring da migration 0053).
4. **Suba API e worker** com a chave nova.

As chaves de rate limit no Redis usam o HMAC e ficam na chave velha; expiram sozinhas com a janela do limite.

### Chave do `lead_ref` (`AUDITORIA_CHAVE_DO_LEAD`)

Trocada sozinha, ela tornaria a trilha de auditoria impesquisável: todo `lead_ref` antigo deixaria de bater com o recalculado. Por isso roda pelo mesmo script, **com a mesma janela de manutenção** da chave de índice (as mesmas triggers, as mesmas travas):

1. Pare a API e o worker.
2. Ponha a chave nova em `AUDITORIA_CHAVE_DO_LEAD` e a velha em `AUDITORIA_CHAVE_DO_LEAD_ANTERIOR` — esta como **variável de ambiente** do processo do script.
3. `python scripts/reindexar_leads.py`. Para cada lead conhecido (inclusive os que só restam em `identidades_de_lead`), ele troca `lead_ref(chave velha)` por `lead_ref(chave nova)` em `eventos_auditoria`.
4. **Tire `AUDITORIA_CHAVE_DO_LEAD_ANTERIOR` do ambiente logo em seguida** e suba API e worker. Esquecida ali, ela quebra a trilha na próxima rotação da chave de índice: o script procuraria cada `lead_ref` calculado com a chave anterior, que já não existe em linha nenhuma, não casaria nada, e deixaria todo `lead_ref` calculado sobre o pseudônimo que o lead tinha antes da reindexação — a trilha fica impesquisável, sem erro nenhum. (Rodar de novo logo depois da rotação, com ela ainda definida, não muda linha nenhuma, mas o relatório conta todos os leads como reindexados.)

A chave de índice e a do `lead_ref` podem rodar na mesma execução: troque as duas e defina a anterior.

### `JWT_SEGREDO`

Troca simples de valor e reinício. Todo JWT emitido com o segredo velho deixa de validar: o token de acesso (vida de `JWT_MINUTOS`, 60 por padrão) e o token de MFA pendente. **O refresh token não é JWT** — é um token opaco guardado como digest em `sessoes_de_refresh` — e sobrevive à troca: qualquer cliente que tenha um obtém token de acesso novo por `POST /api/v1/auth/refresh`, sem entrar de novo. Hoje o `frontend/` não guarda nem renova refresh token; o login do painel é a TEC-309. Se o motivo da troca for vazamento e for preciso derrubar as sessões também, revogue os refresh abertos:

```sql
UPDATE sessoes_de_refresh SET revogado_em = now() WHERE revogado_em IS NULL;
```

### Tokens de terceiros

WhatsApp, Anthropic, OpenAI, Google, SMTP e CRM rotacionam no painel do provedor de cada um: gere o novo lá, atualize o secret manager, reinicie, e só então revogue o antigo no provedor. `CRM_WEBHOOK_SECRET` precisa mudar do lado do CRM no mesmo momento, porque ele confere a assinatura `X-Mobia-Signature-256`.

## O aviso `seguranca.rotacao_vencida`

Em produção, ao subir, a API e o worker emitem um log em nível **warning** para cada chave cujo id tem mais de 90 dias (`src/mobia/infra/rotacao.py`), com os campos `chave` e `validade_dias=90`. **Ele não recusa a subida**: derrubar produção porque uma data passou é pior que o risco que a regra mitiga. O alarme do provedor de log é que deve pegá-lo.

Os limites dele, para ninguém confiar além do que ele cobre:

- Olha só duas coisas: `CONTENT_ENCRYPTION_KEY_ATIVA` — **só quando o keyring existe**; a chave legada sozinha nunca avisa — e `LEAD_INDICE_CHAVE_ID`.
- Não cobre `AUDITORIA_CHAVE_DO_LEAD`, `JWT_SEGREDO` nem token de terceiro. Esses vão para a agenda do provedor.
- Só dispara na subida. Um processo que fica meses de pé sem reiniciar não avisa de novo.

## O gate `Segredos` e a branch protection

O job `Segredos` do `.github/workflows/ci.yml` roda o `gitleaks` 8.30.1, baixado por versão e conferido por SHA-256 — a `gitleaks-action` v2 exige licença paga em repositório de organização. Em PR varre os commits do PR; na `main`, o histórico inteiro. Antes de varrer, ele planta um token falso num diretório temporário e exige que o `gitleaks` reprove: sem esse autoteste, uma allowlist larga demais deixaria o gate verde para sempre.

A configuração está em `.gitleaks.toml`: as regras padrão, mais uma allowlist **por valor exato**, nunca por arquivo, para que um segredo real colado no `config.py` continue sendo pego. Localmente:

```bash
gitleaks git --config .gitleaks.toml --redact --log-opts="origin/main..HEAD" .
```

Se o gate acusar um segredo real, **rotacione-o primeiro**. Tirar o commit do histórico não desfaz o vazamento, e reescrever o histórico da `main` é decisão do Eduardo.

**O job só bloqueia o merge se for required check da `main`.** O comando é este (quem roda é o Eduardo):

```bash
gh api -X POST repos/durexex-Inc/mobIA/branches/main/protection/required_status_checks/contexts -f 'contexts[]=Segredos'
```

**Hoje ele não funciona.** Medido em 26/09/2026, a leitura da proteção da `main` (`gh api repos/durexex-Inc/mobIA/branches/main/protection/required_status_checks`) volta `403 Upgrade to GitHub Pro or make this repository public to enable this feature`: branch protection em repositório privado exige plano pago. Até isso mudar, o job reprova o PR mas não impede o merge. E, se a `main` ainda não tiver proteção nenhuma quando o plano mudar, o endpoint acima volta 404: a proteção precisa ser criada antes (`PUT .../branches/main/protection`).

## A primeira reindexação: a migration 0058

A migration `0058_identidade_do_lead_cifrada` faz a primeira reindexação, na subida: tira o telefone em claro de todas as tabelas e grava as identidades cifradas. Ela usa a mesma máquina do script (`src/mobia/domain/identidade/reindexacao.py::reindexar`), e portanto tem as mesmas exigências, pelas mesmas razões: aplicação parada, e o papel que roda o `alembic upgrade` dono das três tabelas de auditoria. A descida devolve o valor em claro às colunas.

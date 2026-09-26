# TEC-195 — Mascarar dado pessoal por permissão, com auditoria

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-195](https://eduardodurieuxlopes.atlassian.net/browse/TEC-195) — épico TEC-189
**Branch:** `feat/tec-195-mascarar-dado-pessoal-com-auditoria`
**Origem:** SRS v1.0 — RF-18, RN-18.5, RNF-12, RNF-18 · RT-08 · TEC-192, TEC-202, TEC-206

## O achado: o telefone e o identificador são a mesma string

Não existe coluna de telefone de lead neste sistema. **No WhatsApp, `conversation_key` É o telefone**, e é também a identidade do lead — o par `(channel, conversation_key)` é o que `handoffs`, `optout_events`, `agendamentos` e `lead_qualification` usam no lugar de uma tabela de leads que não existe.

Isso faz a card ser menos "acrescente uma máscara" e mais "o identificador vazou o dado pessoal e precisa parar". Dois módulos já escreveram isso, cada um pela sua ponta:

- `auditoria/referencia.py` (TEC-206): *"No WhatsApp, `conversation_key` E o telefone do lead (…) Gravar o par na trilha seria gravar o dado pessoal que a card proibe"* — e por isso a trilha guarda um HMAC.
- `api/routes/handoffs.py` (TEC-206): *"Esta rota NAO e o unico caminho que revela dado pessoal (…) `GET /api/v1/leads` devolve a mesma chave **sem registro nenhum**."*

**São três os vazamentos hoje, e o segundo não estava declarado em lugar nenhum:**

| onde | o que sai | quem vê |
|---|---|---|
| `GET /api/v1/leads` → `itens[].conversationKey` | o telefone, em claro | todo papel com `VER_LEADS` — inclui CORRETOR e LEITURA, que **não** têm `VER_DADOS_COMPLETOS` |
| `GET /api/v1/leads` → `proximoCursor` | o telefone, em base64 | idem |
| `GET /handoffs/{id}/resumo` → `link` | o par | já registra `DADO_PESSOAL_ACESSADO` (TEC-206) |

O cursor é o achado desta card. `Cursor.codificar()` serializa `{"s":…,"c":channel,"k":conversation_key}` em base64, e a docstring dele já avisa: *"Opaco nao e seguranca -- qualquer um decodifica base64"*. Verdadeiro e, até aqui, inofensivo — o que muda é que o conteúdo dele é dado pessoal.

## D1 — Máscara com furo é pior que máscara nenhuma

O caminho barato era acrescentar um campo `telefone` mascarado e deixar `conversationKey` como está. **Recusado**: a mesma resposta traria `"conversationKey": "5511999990021"` ao lado de `"telefone": "+55 11 9****-**21"`. Quem auditasse o sistema encontraria a máscara e concluiria que o dado está protegido; ele não estaria. Para uma card cujo motivo declarado é o RT-08 (impacto crítico), entregar o teatro é pior do que entregar nada, porque o teatro encerra a pergunta.

**Decisão: o par para de sair da API do dashboard.** Nem no item, nem no cursor.

## D2 — O identificador vira um handle opaco, numa tabela de referência

Se o par sai, é preciso outra coisa para apontar para um lead. Três formas foram consideradas:

- **HMAC**, como o `lead_ref` da trilha. **Não serve**: não é reversível, e a revelação precisa voltar ao par para ler o valor. O módulo da trilha ainda avisa que *"chaves com funcoes diferentes nao se reaproveitam"*.
- **Cifrar o par** com `infra/crypto.py`. **Não serve**: `encrypt_bytes` usa `os.urandom(NONCE_BYTES)`, então o blob muda a cada requisição — um identificador que muda a cada chamada não é endereço, e não sobrevive a um F5.
- **Uma linha de referência**, com UUID estável. É o que fica.

```
referencias_de_lead (
  id                uuid    PK,
  channel           varchar(32)  NOT NULL,
  conversation_key  varchar(64)  NOT NULL,
  criado_em         timestamptz  NOT NULL,
  UNIQUE (channel, conversation_key)
)
```

Criada sob demanda na listagem (`get-or-create`), com `ON CONFLICT DO NOTHING` — duas requisições simultâneas para o mesmo lead não podem produzir dois handles, senão o mesmo lead teria dois endereços e a trilha registraria os dois como entidades diferentes.

**Isto revisita a D2 da TEC-192**, que decidiu *"Nao existe `leadId`"*. Aquela decisão era sobre não haver **entidade** lead — não há tabela, não há dono, e inventar uma faria o sistema afirmar uma identidade que ele não apura. Isto não cria entidade: cria **referência**, que é um apelido para o par, sem nenhum atributo próprio. A distinção é a mesma que a trilha já faz com `lead_ref`. Vira emenda.

**O custo de compatibilidade é zero hoje e cresce depois.** Nenhuma tela consome `conversationKey` — TEC-321 e TEC-323 não existem. Fazer isto depois delas seria quebrar dois consumidores.

## D3 — O cursor passa a carregar o handle

`Cursor` perde `channel` e `conversation_key` e ganha `lead_id`. A ordenação não muda: o desempate continua sendo por um valor único por lead, e o UUID serve tão bem quanto o par — a consulta junta `referencias_de_lead` para recuperar a ordem.

A docstring atual (*"Opaco nao e seguranca (…) e sim contrato"*) continua verdadeira e agora é **suficiente**: o que trafega já não é dado pessoal.

**Cursor do formato antigo é recusado com 422**, e isso já funciona sem mudança: `decodificar_cursor` captura `KeyError` e levanta `FiltroInvalido`, e a docstring dele já nomeia esse caso — *"o JSON bem formado com as chaves erradas, que e o caso de um cursor de uma VERSAO anterior deste formato"*.

## D4 — Todo mundo recebe mascarado, inclusive quem pode ver

A tentação é devolver o valor cheio para quem tem `VER_DADOS_COMPLETOS` e mascarado para os outros. **A card de tela decide o contrário** (TEC-330): *"Quem tem a permissão vê mascarado por padrão e um botão 'Revelar'; o clique chama o endpoint de revelação, que registra a auditoria, e só então o valor completo aparece."*

Adotado, e a consequência é boa: **a resposta da lista nunca contém dado pessoal, para ninguém.** Não há ramo por papel para errar, não há teste de "o GERENTE vê o quê" a manter, e o único lugar do sistema que devolve o telefone cheio é um endpoint que registra antes de responder.

**Isso muda uma afirmação da TEC-202**, e o comentário tem de mudar junto. `usuarios/permissoes.py` diz hoje que `VER_DADOS_COMPLETOS` é *"capacidade consultada DENTRO de um handler, pela TEC-195"* e que *"rota nenhuma exige"*. Com esta decisão, ela passa a ser exigência de rota — a da revelação — e nenhum handler a consulta por dentro.

## D5 — A revelação é `POST`, e registra a tentativa

```
POST /api/v1/leads/{leadId}/revelar
  Exige(Permissao.VER_DADOS_COMPLETOS)
  body: { "campo": "telefone" }
  → 200 { "campo": "telefone", "valor": "+5511999990021" }
```

`POST` e não `GET`: a chamada tem efeito — ela grava uma linha de auditoria. Um `GET` que escreve é o tipo de coisa que um proxy repete e um pre-fetch dispara.

O registro segue o molde que `handoffs.py` firmou na TEC-206, incluindo o erro para o lado de registrar:

- `acao=DADO_PESSOAL_ACESSADO`, `entidade=LEAD`, `entidade_id=<handle>`, `campo="telefone"`, `lead=(channel, conversation_key)` — que vira `lead_ref`, nunca o par.
- **Commita antes do `return`.** Se a escrita falhar, a resposta é erro e o valor não sai sem registro.
- **Registra a tentativa**, não o sucesso: a linha entra antes de o valor ser montado.
- O valor revelado **não** vai para a trilha. Ela diz qual campo foi lido, não o que ele dizia.

`Entidade.LEAD` é valor novo, e o CHECK `ck_eventos_auditoria_entidade` tem cópia literal na migration `0053`. A `0056` recria o CHECK, e `tests/unit/test_auditoria_vocabulario.py` — que prende as duas cópias por `ast` — passa a ler a migration mais recente que o define.

## D6 — A forma da máscara

**Telefone**, a partir da forma canônica de `identidade/telefone.py::normalizar` (só dígitos, com o 55):

```
5511999990021  →  +55 11 9****-**21
```

País e DDD ficam: não identificam ninguém e são o que dá à tela alguma utilidade. Do número, sobram o primeiro dígito e os dois últimos — é o formato que a TEC-330 escreve por extenso, e ele é o contrato com quem vai desenhar a tela.

**O telefone sai de dois lugares**, como `_onde_a_busca_bate` já registra: no WhatsApp é o próprio `conversation_key`; no web a sessão é anônima e o número só existe se o lead o digitou, em `vinculos_de_sessao`. Lead web que nunca digitou número tem `telefone: null` — nulo é "não há", nunca máscara de nada.

**E-mail**:

```
marina@exemplo.com  →  m****a@e*****o.com
```

Primeiro e último caractere do local, primeiro e último do domínio antes do TLD, TLD inteiro. Entrada curta demais para essa regra é mascarada por inteiro menos o último caractere — a máscara **nunca** revela mais do que a regra, e o degrau é sempre para o lado de esconder.

## D7 — O e-mail não tem fonte, e a regra entra assim mesmo

**Nenhuma tabela deste sistema guarda e-mail de lead.** `corretores.email` e `usuarios.email` são de gente da operação, não de lead.

A regra de mascaramento de e-mail entra escrita e testada, **sem chamador** — o mesmo estado em que `ciclo.py::marcar_realizado` esperou a TEC-374. Ela custa uma função pura e um teste; quando a coluna nascer, o mascaramento já está decidido e verificado, em vez de ser improvisado por quem estiver criando a coluna.

Vira emenda ao SRS e vai no comentário da card como critério de aceite não exercitado.

## D8 — A busca por telefone continua, e é confirmação, não revelação

`GET /api/v1/leads?busca=99999` casa contra o telefone, e isso é a RN-18.1 (*"busca por nome, telefone ou bairro"*). Um CORRETOR pode portanto **confirmar** um número que já suspeita, mesmo sem poder lê-lo.

Declarado, e não consertado: é um oráculo de confirmação, não de descoberta — o espaço é grande demais para varrer, e remover a busca por telefone tiraria da tela a forma mais usada de achar um lead. Quem decide o contrário decide contra a RN-18.1, e isso é card de produto.

## D9 — Dois critérios do Gherkin já estão atendidos, e por outras cards

- **"Registro de auditoria é imutável"** — feito pela TEC-206. A `0053` cria o trigger `eventos_auditoria_imutavel`, que levanta `'eventos_auditoria e imutavel: UPDATE recusado (RNF-18)'`. Esta card **aponta** para o teste que já existe, em vez de escrever um segundo que afirmaria a mesma coisa.
- **"Mascaramento vale na exportação"** — **não exercitável**: não existe exportação de lead. A própria TEC-330 registra que *"hoje nenhuma exportação de lead está no escopo (RN-FE-10.4)"*. Declarado, não inventado — escrever o cenário contra um endpoint de exportação criado só para ele é o modo de falha que o CLAUDE.md nomeia.

## Emendas ao SRS

- **RN-18.5, Emenda E-01** — o que é mascarado, a forma, o endpoint de revelação, a auditoria, e as duas lacunas (e-mail sem fonte, exportação inexistente).
- **RN-18.1, Emenda E-01** — a lista passa a devolver `leadId` no lugar de `conversationKey`, e o cursor deixa de carregar o par; a busca por telefone permanece e o oráculo de confirmação fica declarado.
- **RNF-12, Emenda E-02** — `VER_DADOS_COMPLETOS` passa a ser exigência de rota, e não capacidade consultada dentro de um handler.

## Fora do escopo

- **Autenticação e definição dos papéis** (E9) — a card já os põe fora.
- **Direitos do titular** — acesso, portabilidade e eliminação são a TEC-207.
- **A tela** — TEC-330. Esta card entrega a API e as regras.
- **O detalhe do lead** — TEC-193. O `leadId` que esta card cria é o que aquela vai usar como endereço.

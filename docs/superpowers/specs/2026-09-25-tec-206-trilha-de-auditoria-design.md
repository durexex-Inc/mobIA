# TEC-206 — Registrar trilha de auditoria imutável

**Status:** implementado
**Card:** [TEC-206](https://eduardodurieuxlopes.atlassian.net/browse/TEC-206) — épico TEC-200
**Branch:** `feat/tec-206-trilha-de-auditoria`
**Origem:** RNF-18, RN-B07 (SRS v1.0); `EventoAuditoria` na §5.1; Emenda E-01 à RNF-12 (TEC-202).
**Destrava:** TEC-195 (destino dos eventos de acesso a dado pessoal), TEC-207, TEC-343 (a tela).

## Objetivo

Uma tabela única, só de acréscimo, que responde a uma fiscalização "quem acessou ou alterou o quê, quando e de onde" — com evidência, sem guardar o dado pessoal em claro, e que nenhum caminho da aplicação consegue editar nem apagar antes de 12 meses.

## O que esta card não entrega, dito antes

- **Três dos cinco eventos da card ficam só no vocabulário, sem chamador**, porque o caminho que os produziria ainda não existe:
  - **alteração de qualificação por pessoa:** a edição pelo dashboard é a TEC-194. Decidido em conversa em 25/09/2026 que só a alteração feita por pessoa é auditada — a do agente é reconstruível pela transcrição e multiplicaria o volume sem ganho de conformidade.
  - **publicação de prompt:** `ConfiguracaoAgente` não existe; é a TEC-198/199.
  - **acesso a telefone e e-mail do lead:** nenhuma rota os revela; é a TEC-195.

  A card entrega a ação no vocabulário e a função que a grava; quem construir o caminho chama.
- **A tela** é a TEC-343. Esta card entrega a API que ela consome.
- **Um papel de banco sem DDL.** A garantia desta card vale contra todo caminho da aplicação, não contra quem opera o banco como dono (D3).

## D1 — Escrita explícita, na mesma transação

`domain/auditoria/registro.py::registrar_evento(session, *, ator, acao, entidade, entidade_id, campo=None, lead=None, detalhes=None, origem=None)` acrescenta a linha à sessão de quem chama e **nunca faz commit** — o molde de `registrar_recalculo` para o score.

- Numa operação de escrita, o evento e a operação commitam juntos ou nenhum dos dois: não há handoff sem registro, nem registro de handoff desfeito.
- Nas duas leituras (acesso ao resumo e acesso negado), não há transação de negócio: o registro commita numa sessão curta própria **antes** da resposta sair. Se a escrita falhar, a resposta é erro — o resumo não sai sem o registro.

**Descartadas:** trigger nas tabelas de origem (o banco não conhece o usuário, o IP nem o `correlation_id`, e trigger não vê leitura — que é metade do que se audita) e escrita assíncrona por job (um evento pode se perder entre a operação e o job, e "provavelmente registramos" não é o que uma trilha pode afirmar).

**O custo:** todo caminho auditado precisa de uma linha de código, e um caminho novo que a esqueça não é auditado. A defesa é um teste por evento (seção Testes), não um mecanismo implícito.

## D2 — A tabela `eventos_auditoria`

O `EventoAuditoria` do SRS, com três diferenças deliberadas (marcadas com **novo**):

| coluna | tipo | conteúdo |
| --- | --- | --- |
| `id` | uuid | |
| `criado_em` | timestamptz | relógio do banco, forçado pelo trigger de inserção (D3) |
| `ator_tipo` | varchar | `USUARIO`, `AGENTE`, `SISTEMA` — o enum do SRS, com `CHECK` |
| `ator_id` | varchar, nulo | `usuario_id` quando é pessoa; `token-compartilhado` quando veio pelo `X-Admin-Token` (o `IdentidadeDaRequisicao.para_log`); nulo para agente e sistema |
| `acao` | varchar | vocabulário fechado, com `CHECK`: `DADO_PESSOAL_ACESSADO`, `QUALIFICACAO_ALTERADA`, `HANDOFF_CRIADO`, `OPTOUT_REGISTRADO`, `OPTOUT_REATIVADO`, `PROMPT_PUBLICADO`, `ACESSO_NEGADO` |
| `entidade` | varchar | `handoff`, `optout_event`, `rota`, … |
| `entidade_id` | varchar | o uuid da entidade, ou o template da rota |
| `campo` | varchar, nulo | **novo** — o campo acessado ou alterado (`resumo`, `telefone`, …): o "referencia o lead e o campo" da card |
| `lead_ref` | char(64), nulo | **novo** — HMAC-SHA256 de `(channel, conversation_key)` com chave própria (D4) |
| `detalhes` | jsonb, nulo | metadado que não é dado pessoal (D5) |
| `ip` | inet, nulo | origem da requisição |
| `correlation_id` | varchar, nulo | **novo** — o id da requisição (TEC-368), que liga o registro ao log de aplicação |

**Sem `dados_antes` nem `dados_depois`.** Para qualificação e dado pessoal, o antes e o depois **são** o dado pessoal que a card proíbe guardar em claro. O registro diz qual campo mudou, não para quê. Cifrá-los faria da trilha uma segunda cópia do dado, que a retenção e o direito de eliminação (RNF-21) teriam de perseguir.

**Sem chave estrangeira** para as entidades: um registro sobrevive à exclusão do que ele descreve, que é o motivo de ele existir — e FK com cascata faria a exclusão de um lead apagar a própria trilha.

**Índices:** `(criado_em desc, id desc)` para a paginação e a retenção — o `id` também descendente para que `ORDER BY criado_em DESC, id DESC` e o cursor usem uma varredura só; `(ator_id, criado_em desc)`, `(acao, criado_em desc)` e `(lead_ref, criado_em desc)` para os filtros da TEC-343.

**Agente e sistema não têm `ip` nem `correlation_id`**: vêm de job do ARQ, não de requisição HTTP. O opt-out chega pelo webhook, e o IP ali é o da Meta, não o do lead — gravá-lo seria afirmar uma origem falsa.

## D3 — A garantia: dois triggers

1. **`BEFORE INSERT`**: `criado_em := clock_timestamp()`, qualquer que seja o valor enviado. Sem isso a regra de 12 meses tem um furo: inserir uma linha datada de dois anos atrás e apagá-la em seguida. Também impede antedatar um registro para cobrir uma lacuna.
2. **`BEFORE UPDATE OR DELETE`**: `UPDATE` é sempre recusado; `DELETE` é recusado quando `criado_em >= clock_timestamp() - interval '12 months'`. A mensagem de erro nomeia a regra.

A regra mora no banco, então vale para o ORM, para SQL cru, para um script administrativo futuro e para uma migration errada — é isso que torna verdadeiro o "por qualquer caminho da aplicação" da card. Os triggers de `lead_score_audit` e `conversation_intent_audit` recusam só `UPDATE`; este vai além porque a exclusão legítima passou a ter regra (D6).

**Limites, declarados:**

- **`TRUNCATE` não é bloqueado.** A fixture `banco_limpo` trunca todas as tabelas antes de cada teste de integração; um trigger de `TRUNCATE` obrigaria a suíte a contornar a garantia com um recurso de superusuário.
- **O dono da tabela pode remover o trigger.** A aplicação conecta ao Postgres como o dono (`docker-compose.yml`), e dono tem DDL. A garantia é contra a aplicação, não contra o operador do banco. Separar um papel de aplicação sem DDL é decisão de implantação (TEC-219).

## D4 — `lead_ref`: achar os eventos de um lead sem gravar o telefone

No WhatsApp, `conversation_key` **é** o telefone do lead, e o lead não tem outro identificador (D2 da TEC-192). Gravar `conversation_key` na trilha seria gravar o dado pessoal que a card proíbe.

`lead_ref = HMAC-SHA256(chave, f"{channel}:{conversation_key}")`, em hex, com uma chave própria, `AUDITORIA_CHAVE_DO_LEAD` — não a de `crypto.py::marca_do_aad`: chaves com funções diferentes não se reaproveitam, e esta não pode rodar sem tornar a trilha inteira impesquisável. É estável (o mesmo lead dá sempre o mesmo valor), não é reversível sem a chave, e sobrevive à eliminação do lead (RNF-21) sem guardar nada que o identifique.

`registrar_evento` recebe `(channel, conversation_key)` e calcula o `lead_ref` — nenhum chamador lida com o HMAC.

**A chave segue o molde de `content_encryption_key` e `jwt_segredo`** em `app/config.py`: um default de desenvolvimento conhecido, e um `model_validator` que levanta `ConfiguracaoInsegura` quando `em_producao` e a chave ainda é o default. A razão é a mesma daquelas duas: uma chave conhecida não produz erro nenhum, ela só deixa de proteger — quem a tiver calcula o `lead_ref` de qualquer telefone e descobre se aquele número aparece na trilha. Estando no validator, a guarda vale para API, worker, alembic e qualquer script que construa `Settings`.

## D5 — `detalhes` nunca copia texto livre

`detalhes` leva só metadado fechado: a permissão negada, o motivo da negativa (`sem_permissao`, `sem_sessao`, `corretor_nao_e_o_dono`), o papel, o método HTTP, o gatilho do handoff. **Texto digitado por uma pessoa não entra** — o `motivo` da reativação de opt-out fica em `optout_events`, e o registro aponta para ele. Texto livre pode carregar dado pessoal, e nenhum teste garante que não carrega.

## D6 — Retenção: apagar depois de 12 meses

Decidido em conversa em 25/09/2026: a retenção de 12 meses da RNF-18 é **máximo**, como os prazos da RNF-22 (24 meses para lead, 12 para transcrição). Uma trilha que sobrevive à transcrição que ela referencia guarda referência a um dado que já não existe.

Job ARQ `sweep_retencao_auditoria`, cron diário às 04:00 (uma hora depois de `sweep_conversas_inativas`): apaga em lotes as linhas com mais de 12 meses e emite uma linha `auditoria.retencao_executada` com a contagem. **O job não decide o que pode ser apagado**: ele pede as linhas antigas, e o trigger confere linha por linha. Um erro no corte do job esbarra no trigger, em vez de apagar histórico recente. "12 meses" é `interval '12 months'` sobre o relógio do banco — uma definição só, para o trigger e para o job.

## D7 — Quem grava cada evento

| ação | onde | ator | entidade / campo |
| --- | --- | --- | --- |
| `HANDOFF_CRIADO` | dentro de `domain/handoff/repositorio.py::registrar_handoff`, na mesma sessão, **só quando `criado` é verdadeiro** — acumular gatilho num handoff aberto não é criação | parâmetro novo e obrigatório `ator`: `AGENTE` nos chamadores do turno, `SISTEMA` no de `process_message`; cada sítio de chamada declara o seu | `handoff` + id; `detalhes.gatilho` |
| `OPTOUT_REGISTRADO` | dentro de `domain/optout/repositorio.py::registrar_optout`, na sessão da linha de `optout_events` | `SISTEMA`: o lead pediu, o sistema registrou | `optout_event` + id |
| `OPTOUT_REATIVADO` | dentro de `domain/optout/repositorio.py::reativar`, na mesma sessão | `SISTEMA`: o operador da CLI é um `autor` em texto livre, não um `usuario_id` | `optout_event` + id |
| `DADO_PESSOAL_ACESSADO` | `api/routes/handoffs.py::regenerar` (`POST /api/v1/handoffs/{id}/resumo`), gravado e commitado **antes** de devolver o resumo | `USUARIO`, com `ip` e `correlation_id` | `handoff` + id, `campo = resumo` |
| `ACESSO_NEGADO` | `api/autorizacao.py::registrar_negativa`, em sessão curta própria, **só quando uma identidade foi resolvida** | `USUARIO` | `rota` + o template da rota; `detalhes` com permissão, motivo, papel e método |
| `QUALIFICACAO_ALTERADA`, `PROMPT_PUBLICADO` | sem chamador (ver "O que esta card não entrega") | — | — |

**A negativa sem credencial continua só em log.** O argumento da TEC-202 vale inteiro: um varredor de endpoints produz 403 em rajada sem credencial nenhuma, e cada um viraria uma escrita no Postgres. Com identidade resolvida, quem produz a negativa é alguém identificável, e é esse o registro que a TEC-343 pede ("Paulo tentou acessar…").

**`ip`** vem de `api/middleware.py::resolver_ip`, a mesma regra do rate limit (IP do socket, ou o último salto do `X-Forwarded-For` quando confiável). **`correlation_id`** vem do contextvar da TEC-368.

**Mudanças de assinatura:** `registrar_negativa` e `exigir_dono` passam a `async` (a escrita pede `await`) — quatro sítios em `autorizacao.py` mais todo chamador de `exigir_dono`. Isso inclui um intermediário síncrono: `api/routes/conversas.py::_exigir_que_seja_ele_mesmo` também vira `async`, e os seus dois chamadores (`assumir`, `devolver`) passam a `await` nela; `api/routes/handoffs.py::_exigir_dono_do` já era `async`. `registrar_handoff` ganha `ator`.

## D8 — A API: `GET /api/v1/auditoria`

Só leitura: a rota não tem outro método, então "não há opção de editar nem de excluir" vale também na API.

- **Permissão:** `Permissao.VER_AUDITORIA`, nova, só do `ADMIN` (TEC-343: "Somente leitura; somente `ADMIN`"). Entra na matriz de `domain/usuarios/permissoes.py`. `tests/unit/test_autorizacao_em_toda_rota.py::test_toda_rota_declara_autorizacao` cobre a rota nova sozinho; `::test_a_permissao_de_cada_rota` só a cobre porque ganhou a linha `("GET", "/api/v1/auditoria"): "VER_AUDITORIA"` no mapa `PERMISSAO_ESPERADA`, escrito à mão.
- **Filtros**, todos opcionais e combináveis: `ator` (um `usuario_id`), `acao` (um ou mais do vocabulário), `de`/`ate` (ISO-8601, intervalo semiaberto `[de, ate)`), e `channel` + `conversationKey` juntos — o servidor transforma o par em `lead_ref` e não guarda o telefone que recebeu. Filtro inválido é 422, na convenção `montar_filtro`/`FiltroInvalido` da TEC-192.
- **Paginação:** o cursor opaco da TEC-192 sobre `(criado_em desc, id)`; página padrão 25, máximo 100, sem `total`.
- **Cada item:** `id`, `criadoEm`, `atorTipo`, `atorId`, `acao`, `entidade`, `entidadeId`, `campo`, `detalhes`, `ip`, `correlationId`. **`leadRef` não sai**: é chave de busca, não informação para exibir.
- **A leitura da trilha não é auditada** nesta card — seria um registro por registro lido. Se precisar ser, é decisão da TEC-343.

## Testes

**Unitários:**

- O vocabulário de ator, ação e entidade bate com os `CHECK` da migration.
- `lead_ref`: estável, muda com o canal, não contém o telefone, e depende da chave.
- `detalhes` montado pelos sítios de chamada não carrega texto livre.
- A guarda de configuração recusa o default de desenvolvimento de `AUDITORIA_CHAVE_DO_LEAD` em produção.

**Integração — a garantia no banco:**

- `UPDATE` recusado; `DELETE` de linha recente recusado mesmo por SQL cru.
- `criado_em` antedatado na inserção é sobrescrito pelo relógio do banco.
- Retenção: uma linha de 11 meses fica, uma de 13 meses sai. O teste desliga só o trigger de inserção, dentro da própria transação, para antedatar as linhas; o de `UPDATE`/`DELETE` continua ligado, e é ele que o teste exercita.

**Integração — um teste por evento:**

- Handoff criado grava um registro; acumular gatilho num handoff aberto não grava nenhum.
- Opt-out e reativação gravam o seu.
- Acesso ao resumo grava com `campo = resumo`, e o texto do resumo não aparece em coluna nenhuma.
- Negativa com identidade grava; negativa sem credencial não grava.
- Transação: quando a transação do handoff é desfeita, o registro vai junto.

**API:**

- `ADMIN` lê; `GERENTE`, `CORRETOR` e `LEITURA` recebem 403 (que por sua vez vira um `ACESSO_NEGADO`).
- Cada filtro funciona; o cursor percorre sem repetir nem pular.

**Critérios de aceite da card:**

| cenário | como é exercitado |
| --- | --- |
| eventos que geram registro | handoff, opt-out, acesso a dado pessoal (o resumo) e acesso negado com teste; alteração de qualificação e publicação de prompt sem caminho — declarado |
| registro não pode ser alterado | `UPDATE` e `DELETE` recusados no banco |
| registro não guarda dado pessoal em claro | exercitado no resumo e no `lead_ref`; o telefone não tem rota que o revele até a TEC-195 |
| retenção de 12 meses | 11 meses fica (e 13 meses sai) |

## Migration 0048

`eventos_auditoria`, os dois triggers e os quatro índices, à mão. `downgrade` remove tudo.

## Emendas ao SRS

- **RNF-18** — os eventos auditados de fato e os que ficam sem chamador; os 12 meses são máximo; o limite da garantia (o papel dono).
- **§5.1 `EventoAuditoria`** — `campo`, `lead_ref` e `correlation_id` entram; `dados_antes` e `dados_depois` saem, com o porquê.
- **RNF-12, abaixo da Emenda E-01** — a negativa com identidade resolvida passa a ter destino persistente; a sem credencial continua em log.

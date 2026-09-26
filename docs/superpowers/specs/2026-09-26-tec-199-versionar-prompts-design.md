# TEC-199 — Versionar prompts com rollback

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-199](https://eduardodurieuxlopes.atlassian.net/browse/TEC-199) — épico TEC-189
**Branch:** `feat/tec-199-versionar-prompts`
**Origem:** RF-19, RN-19.4, CA-19.2 (SRS v1.0) · base na TEC-198 · telas TEC-338 e TEC-339

## O problema

Os prompts de sistema são constantes em `domain/agente/classificador.py`. Mudar um deles é deploy, e desfazer a mudança é outro deploy — minutos, contra os 30 segundos da CA-19.2.

A card fala em dois agentes, *"qualificador"* e *"consultor"*, que **não existem no código com esses nomes**. O que existe são sete `system` de LLM; dois deles conversam com o lead, e são esses que esta card versiona.

## D1 — Quais prompts: o do agente e o do investidor

Decisão do Eduardo, 26/09/2026. Um enum `AgenteDoPrompt` com dois valores:

| valor | constante de hoje | quem usa |
|---|---|---|
| `AGENTE` | `SISTEMA_DO_AGENTE` | `classificar`, todo turno |
| `INVESTIDOR` | `SISTEMA_DO_INVESTIDOR` | `classificar_investidor`, a trilha de investimento (TEC-153) |

São os dois que falam com o lead e os dois cujo texto muda o atendimento. Desambiguação, reação, follow-up, resumo e moderação ficam de fora: a moderação é defesa de segurança e não deveria ser editável pela tela, e os outros três são chamadas auxiliares que a card não pede. **O isolamento do terceiro cenário é entre `AGENTE` e `INVESTIDOR`.**

## D2 — O texto editável é um modelo com dois marcadores; a cláusula de segurança fica fora dele

Decisão do Eduardo, 26/09/2026.

- **`{assistente}` e `{tom}` são obrigatórios.** `{assistente}` vira *"o assistente virtual"* ou *"Ana, o assistente virtual"*; `{tom}` vira a frase de `FRASE_DO_TOM`. É assim que a configuração da TEC-198 continua valendo por cima de qualquer versão: o administrador edita o texto, e o nome e o tom continuam vindo da tela de configuração. Sem um dos dois, **422**.
- **Marcador desconhecido também é 422.** Quem escreve `{nome}` achando que é marcador mandaria a palavra literal para o modelo.
- **`CLAUSULA_DO_AGENTE` (TEC-204) é anexada pelo código e não faz parte do texto versionado.** A defesa contra injeção não pode sair do prompt por uma edição na tela.

O padrão de cada agente passa a ser escrito como modelo — `MODELO_DO_AGENTE`, `MODELO_DO_INVESTIDOR` —, e `renderizar(modelo, nome=, tom=)` produz o `system`. **Com o modelo padrão, nome nulo e `CORDIAL`, o texto é byte a byte o de hoje**, para os dois agentes.

**Consequência que muda a TEC-198:** o prompt do investidor passa a usar o nome e o tom configurados. A Emenda E-01 da RN-19.3 dizia que o do investidor *"não usa nome nem tom"*; com os marcadores obrigatórios nos dois agentes, deixar o investidor de fora faria o assistente perder o nome justamente quando o lead fala de investimento. Com o padrão nada muda.

A substituição é `str.replace`, e não `str.format`: um texto com chaves literais (JSON de exemplo, por exemplo) não pode derrubar o turno. `{tom}` é substituído antes de `{assistente}`, para que um nome com `{tom}` dentro não seja expandido.

## D3 — O orçamento: a versão não pode ser mais longa que o padrão

Decisão do Eduardo, 26/09/2026: recusar com 422.

O `system` do agente é parcela da subcontagem que `test_a_margem_do_orcamento_do_prompt_e_deliberada` trava contra um teto fixo. **A regra da publicação é: renderizado no pior caso da identidade (nome no teto de caracteres, tom de frase mais longa), o texto novo não pode ser mais longo que o modelo padrão renderizado no mesmo pior caso.** A conta do teste é `len/4`, linear em caracteres, então comparar caracteres é comparar a mesma coisa que o teste compara.

**Por que o padrão, e não o teto fixo do teste.** O teto vive uma única vez no corpo do teste, e a docstring dele diz que é o único número da conta escrito à mão; trazê-lo para `src/` criaria a segunda cópia que o CLAUDE.md proíbe. E a folga entre o padrão e o teto **é deliberadamente reservada para a próxima card de desenvolvimento** — gastá-la pela tela seria exatamente o *"gastar sem saber que estava gastando a reserva"* que o teste existe para impedir. O administrador pode reescrever; para crescer, o caminho continua sendo o ritual.

O mesmo vale para o investidor, que não está na subcontagem mas paga o mesmo `headroom`: a regra é uma só para os dois.

A recusa diz quantos caracteres passaram.

## D4 — Duas tabelas, as duas só de acréscimo

```
versoes_de_prompt (
  id            uuid PK,
  agente        varchar(16) NOT NULL CHECK (agente IN ('AGENTE', 'INVESTIDOR')),
  numero        integer NOT NULL CHECK (numero >= 1),
  texto         text NOT NULL,
  anterior      integer NOT NULL,     -- o numero que valia na publicacao; 0 = padrao
  diff          text NOT NULL,        -- unified diff contra `anterior`
  autor         varchar(120) NOT NULL,
  criado_em     timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (agente, numero)
)

ativacoes_de_prompt (
  id            uuid PK,
  agente        varchar(16) NOT NULL CHECK (...),
  numero        integer NOT NULL CHECK (numero >= 0),   -- 0 = padrao do codigo
  motivo        varchar(12) NOT NULL CHECK (motivo IN ('PUBLICACAO', 'ROLLBACK')),
  autor         varchar(120) NOT NULL,
  criado_em     timestamptz NOT NULL DEFAULT clock_timestamp()
)
```

**A versão vigente de um agente é o `numero` da ativação mais recente dele**; sem ativação, é o padrão. Publicar grava uma versão **e** uma ativação `PUBLICACAO`; reverter grava só uma ativação `ROLLBACK`, apontando para uma versão que já existe.

**Por que duas tabelas, e não a da TEC-198 com uma linha nova por rollback.** O cenário diz *"a versão anterior volta a valer"*: com o ponteiro, o que vale depois do rollback **é** a versão 3, e não uma versão 5 com o texto da 3. E o quarto cenário (*"constam o autor do rollback, o momento e a versão de destino"*) é literalmente uma linha de `ativacoes_de_prompt`.

**A versão 0 é o padrão do código, e não uma linha.** Rollback para 0 volta ao que está escrito em `classificador.py` no deploy corrente. Semear o padrão numa linha congelaria o texto de hoje, e a próxima mudança feita pelo ritual não valeria para quem nunca editou nada — o mesmo argumento da `0058`.

**O `diff` é gravado na publicação, e não calculado na leitura.** Ele compara com a versão que **valia** no momento — que depois de um rollback não é a de número imediatamente anterior —, e o texto do padrão pode mudar por deploy; calculado na leitura, o diff da versão 1 mentiria sobre o que o administrador editou. `difflib.unified_diff` por linha.

**Numeração** é `max(numero) + 1` por agente, na transação da publicação; o `UNIQUE (agente, numero)` recusa a corrida, que vira **409**.

## D5 — Sem cache: o rollback vale no turno seguinte

Mesmo argumento da D1 da TEC-198. `montar_contexto` lê a configuração **e** os dois modelos vigentes uma vez por turno, e o turno usa o mesmo retrato até o fim. Não há cache a invalidar, então o rollback vale para o próximo turno que começar — a CA-19.2 pede menos de 30 s, e o que se mede no teste é o turno seguinte ao rollback usar o texto revertido.

**Falha de leitura cai para o padrão**, com aviso no log, como `_configuracao_do_turno` já faz. O padrão é o prompt que o agente sempre teve.

Uma versão gravada no banco é revalidada ao ser lida? **Não.** Ela passou por `validar_modelo` ao ser publicada e a tabela é só de acréscimo; o que pode mudar é o padrão, por deploy, e isso não invalida uma versão. Se uma versão perder um marcador por SQL cru, `renderizar` simplesmente não o substitui.

## D6 — As rotas

```
GET  /api/v1/prompts                             → os dois agentes, cada um com a versão ativa
GET  /api/v1/prompts/{agente}                    → a ativa com texto, e os limites (marcadores, teto de caracteres)
GET  /api/v1/prompts/{agente}/versoes            → as versões, mais nova primeiro, com autor, instante, anterior e diff
GET  /api/v1/prompts/{agente}/versoes/{numero}   → uma versão com o texto; 0 é o padrão
POST /api/v1/prompts/{agente}/versoes            → publica { texto }; 201; 422; 409 na corrida
POST /api/v1/prompts/{agente}/rollback           → { versao }; 200; 404 versão inexistente; 409 já é a ativa
GET  /api/v1/prompts/{agente}/historico          → as ativações: publicação e rollback, autor, instante, versão
```

A versão ativa sai identificada com **quem a publicou e quando** (a versão) e **quem a ativou e quando** (a ativação) — depois de um rollback, os dois diferem, e a card pede os dois.

Publicar um texto idêntico ao vigente **não grava nada** e responde 200 com a vigente, como o `PATCH` da TEC-198.

Permissão: **`CONFIGURAR_AGENTE`**, a mesma da TEC-198 — só ADMIN, de escrita. Uma segunda permissão só teria sentido se algum papel pudesse mexer num e não no outro, e nenhum pode.

**O caminho diverge da seção 6 do SRS**, que desenhou `/api/v1/configuracoes/{chave}` e `/{chave}/rollback` para uma tabela chave-valor que a TEC-198 não construiu. Emenda E-01 à RN-19.4.

## D7 — A trilha

`PROMPT_PUBLICADO` estava no vocabulário sem chamador desde a TEC-206; ganha o chamador. **`PROMPT_REVERTIDO` é novo**, e a migration `0059` recria o CHECK de `acao` como a `0058` fez. `entidade=configuracao_agente` (já existe), `entidade_id` é o id da ativação — que existe também no rollback para o padrão, onde não há versão —, e `campo` é o agente. O texto não vai para a trilha.

## Arquivos

```
alembic/versions/0059_versoes_de_prompt.py
src/mobia/domain/prompts/{__init__,modelo,models,repositorio}.py
src/mobia/domain/agente/classificador.py   # MODELO_DO_*, renderizar, os dois system vindos do contexto
src/mobia/domain/context/montagem.py       # os modelos vigentes no retrato do turno
src/mobia/domain/auditoria/vocabulario.py  # PROMPT_REVERTIDO
src/mobia/api/routes/prompts.py
src/mobia/app/main.py
tests/conftest.py                          # as duas tabelas em TABELAS
```

## Testes

- **Unitários, sem banco** — `renderizar(MODELO_*, None, CORDIAL)` é byte a byte o `SISTEMA_*` de hoje, para os dois; cada regra de `validar_modelo` (marcador ausente, marcador desconhecido, vazio, longo demais no pior caso); a cláusula de segurança está no fim de qualquer renderização; nome com `{tom}` não é expandido; o diff.
- **Os quatro cenários, contra banco** — publicar sobre a versão 3 cria a 4 com autor, instante e diff contra a 3; depois do rollback, o turno seguinte manda o texto revertido no `system`; rollback do agente não mexe no investidor; o histórico traz autor, instante e versão de destino do rollback.
- **As bordas** — rollback para a versão 0 volta ao padrão; texto idêntico não grava; versão inexistente é 404; já ativa é 409; GERENTE leva 403.

## Emendas ao SRS

- **RN-19.4, Emenda E-01** — os dois agentes, o modelo com marcadores obrigatórios, a cláusula fora do alcance, o teto pelo padrão, as duas tabelas, a versão 0, as rotas.
- **RN-19.3, Emenda E-02** — o prompt do investidor passa a usar o nome e o tom configurados.
- **RNF-18, Emenda E-05** — `PROMPT_PUBLICADO` ganha chamador; `PROMPT_REVERTIDO` entra.

## Lacunas declaradas

- **L1 — uma versão ativa não recebe as mudanças que o desenvolvimento faz no padrão.** Se o ritual do orçamento acrescentar uma cláusula a `MODELO_DO_AGENTE`, quem tem a versão 4 ativa continua sem ela até republicar ou reverter para 0. O `GET` do agente devolve o padrão atual para a tela poder comparar; avisar é da TEC-338.
- **L2 — o gate de evals (E9, RNF-26) mede o padrão, não a versão ativa.** Uma versão publicada pela tela não passa por eval nenhum. É o fora-de-escopo que a card declara, e a consequência é esta: o rollback é a única rede.
- **L3 — o texto pode contradizer o schema.** O prompt lista as intenções que o schema estrito impõe; uma versão que as renomeie não quebra o parsing — o schema manda —, mas confunde o modelo. Não há validação semântica do texto.
- **L4 — o limite de caracteres não deixa crescer.** Reescrever mais curto ou do mesmo tamanho, sim; qualquer acréscimo líquido é pelo ritual (D3).
- **L5 — os evals e sondas em `evals/` continuam usando `SISTEMA_DO_AGENTE`**, o padrão. Medir uma versão publicada exige rodá-los com o texto dela à mão.

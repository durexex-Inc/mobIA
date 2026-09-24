# TEC-190 — Painel de funil com indicadores e filtros

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-190](https://eduardodurieuxlopes.atlassian.net/browse/TEC-190) — épico TEC-189
**Branch:** `feat/tec-190-painel-de-funil`
**Origem:** RF-17, RN-17.1, RN-17.2, RN-17.3 (SRS v1.0); RNF-04. Contrato em §6.6 do SRS.

## Objetivo

Dar à gerente comercial o funil do período sem planilha: seis etapas com valor absoluto e conversão entre elas, os indicadores da RN-17.1, e cinco filtros.

## O escopo tem duas metades, e a segunda não existe no repo

A card diz "exibir", e não há frontend nenhum aqui — nem `package.json`. O SRS decidiu **Next.js 15 + React 19** (§ de decisões de tecnologia, linha do Frontend) e nada foi construído. Decidido com o Eduardo em 24/09: a TEC-190 entrega **as duas metades**, o endpoint e o projeto Next.js em `frontend/`, sequenciadas — o backend primeiro, o front consumindo-o.

**Isto é grande para uma card só, e fica dito.** O plano de implementação separa as duas metades em fases com verificação própria; se a segunda precisar virar card, o corte natural é depois da fase do endpoint, que é entregável sozinho.

## O que a card pede e o banco não tem

O levantamento das 21 tabelas contra a RN-17.1 e a RN-17.2:

| a card pede | fonte |
| --- | --- |
| etapa Novo | primeira `messages.created_at` por `(channel, conversation_key)` |
| etapa Em conversa | `messages`: mais de uma fala de ENTRADA do lead (uma só é o primeiro contato, que já é `Novo`) |
| etapa Recomendado | `recomendacoes.apresentado_em` |
| etapa Handoff aceito, taxa no SLA | `handoffs.aceito_em`, `sla_limite_em` |
| leads novos, conversas ativas | `messages`, `conversas` |
| distribuição por temperatura | `lead_qualification.temperatura` |
| tempo médio de primeira resposta | `messages`, primeiro INBOUND do lead até primeiro OUTBOUND do agente |
| **etapa Qualificado, taxa de qualificação, tempo médio de qualificação** | **parcial** — ver D2 e D3 |
| **etapa Agendado; agendamentos criados, confirmados e realizados; taxa de no-show** | **nenhuma** — ver D1 |

**`conversas` não tem `criado_em`.** As colunas são `channel`, `conversation_key`, `status`, `motivo_do_encerramento` e `encerrada_em`. "Lead novo no período" não sai dela; sai da primeira mensagem da conversa em `messages`, que é a única tabela com o instante de nascimento do lead.

## D1 — `Agendado` devolve `null`, e nunca `0`

**Não existe tabela de agendamento neste repo.** As 21 tabelas foram conferidas uma a uma: "agendamento" aparece como `Gatilho.AGENDAMENTO_CONFIRMADO` em `handoff/vocabulario.py` e como `MOTIVO_VISITA` em `context/gatilhos.py`, e `handoff/agendador.py` é port de enfileiramento ARQ do job de resumo — nenhum dos três persiste uma visita. `tarefas_de_corretor`, apesar do nome, é follow-up que não pôde sair sozinho (TEC-186, RN-13.6).

Marcar visita é **RF-11** (consulta de disponibilidade e proposta de horários) e **RF-12** (confirmação, lembrete e cancelamento). Nenhum dos dois foi construído. A card da TEC-190 não os lista como dependência porque foi escrita supondo que existissem.

Então a etapa 5 do funil e quatro dos indicadores da RN-17.1 não têm de onde vir. Três saídas foram pesadas:

**Devolver `0` — recusada, e é a pior das três.** Zero é uma afirmação: diz que nenhuma visita foi marcada no período. A verdade é que ninguém registra visita em lugar nenhum. É a mesma classe de defeito que o `CLAUDE.md` chama de comentário que mente, aplicada ao produto em vez do código — e pior, porque quem lê é a gerente decidindo onde o funil vaza, e um zero na etapa 5 aponta o vazamento para o lugar errado.

**Omitir a etapa — recusada.** Cala sobre a lacuna em vez de declará-la, e muda o contrato quando a RF-12 chegar: hoje cinco etapas, amanhã seis, com o front tendo de mudar junto.

**Escolhida: as seis etapas saem sempre, e a que não tem fonte sai com `quantidade: null` e `disponivel: false`.** O mesmo par vale para os quatro indicadores órfãos. O contrato fica estável — quando a RF-12 chegar, muda a consulta, e nem o contrato nem o front mudam. E o front tem o que renderizar: a etapa aparece marcada como sem fonte de dados, não como barra vazia.

**Criar a tabela `agendamentos` nesta card foi recusado** pela razão que o `CLAUDE.md` registra sobre critério de aceite: inventar a entidade central de dois épicos sem as regras deles produz uma tabela que existe só para um teste se auto-satisfazer. A RF-11 tem `EXCLUDE USING gist` contra dois leads no mesmo slot (CA-11.2) e a RF-12 tem lembrete, remarcação e cancelamento — nada disso seria decidido aqui, e a tabela nasceria errada.

**Consequência para a CA-17.1.** O critério de aceite da card — *"dado um agendamento criado agora, quando o dashboard é recarregado após 60 segundos, então o contador de agendamentos reflete a mudança"* — **não é exercitável**, porque não há como criar um agendamento. Não é falha da implementação: é a lacuna acima. O que a card entrega no lugar é o teste de que o campo sai `disponivel: false`, e a CA-17.1 volta quando a RF-12 existir. Vai no comentário da card e como emenda ao SRS.

## D2 — `qualificado_em` precisa existir

Sem ele há dois defeitos, e o segundo é o que obriga.

O primeiro: "tempo médio de qualificação" (RN-17.1) não tem instante final. Não há coluna que diga quando o lead qualificou.

O segundo, mais grave: **`lead_qualification` não tem `created_at`, só `updated_at`, e `updated_at` é o último toque.** Um lead qualificado em julho que responde uma mensagem hoje tem `updated_at` de hoje — e cairia no funil de agosto, na etapa Qualificado, como se tivesse qualificado agora. O filtro por período da RN-17.3, que é o eixo do painel inteiro, produziria número errado na etapa central do funil.

Usar `updated_at` como aproximação foi recusado por isso: entrega número em todo campo e o número é falso. É a planilha da Anelise com outro nome.

**A transição já é detectada — falta gravá-la.** `turno.py` calcula `antes = esta_qualificado(contexto.estado, _recusados_de(contexto.estado))` **antes** de abrir `async with session_factory()`, e `depois_do_estado` sai de `gravar_estado` **dentro** do bloco; o `if not antes and esta_qualificado(depois_do_estado, ...)` que emite `log.info("lead.qualificado", ...)` roda **depois** do commit, fora da sessão.

A comparação já é conhecida, portanto, mas os dois valores só coexistem dentro do bloco — e é lá que a coluna se escreve, junto de `gravar_estado`, **não** no `if` do log. Ver a D3.

**Migration `0040`**, coluna anulável. Nula é o estado legítimo de quem nunca qualificou, e também de todo lead que qualificou antes desta card — não há backfill possível, porque o instante não foi registrado em lugar nenhum. O painel conta, na etapa Qualificado, só quem qualificou a partir da migration; **o número é baixo nas primeiras semanas e isso não é bug.** Fica na docstring da coluna.

## D3 — a coluna é o estado persistido que `turno.py` pediu, e o dono é esta card

`turno.py`, no comentário acima do `if not antes and ...`, declara uma lacuna e diz de quem é:

> TEC-148 quebrou a premissa que sustentava "uma vez qualificado, sempre qualificado" (...) uma recusa pode derrubar `esta_qualificado` (...) e uma resposta seguinte pode devolvê-lo (...) O evento reemite. Isto NÃO está corrigido aqui: tornar a emissão idempotente por lead exige estado persistido de "já emiti uma vez", que é decisão de quem é dono da métrica RN-17.1, não desta card — só fica declarado, para quem ler essa métrica saber que uma travessia de ida-e-volta agora conta duas vezes.

**A TEC-190 é a dona da RN-17.1**, então a decisão é aqui, e a coluna da D2 é exatamente o estado persistido que falta: `qualificado_em` grava **só na primeira travessia**, com guarda `qualificado_em IS NULL`. Um lead que qualifica, recusa um campo e requalifica conta **uma vez**, não duas. A lacuna declarada em `turno.py` fecha, e o comentário de lá passa a estar desatualizado — muda junto, na mesma branch, pela regra de que comentário não mente.

**A coluna se escreve DENTRO da transação, e o log continua depois do commit.** Não é inconsistência: são coisas diferentes. O log existe para quem lê o log, e `turno.py` documenta por que fica depois — *"logar uma transição que o rollback desfez é mentir para quem lê o log"*. A coluna é dado; se a transação volta atrás, a qualificação não aconteceu e a coluna tem de voltar atrás junto. Escrevê-la depois do commit criaria a divergência que a posição do log evita.

## D4 — a regra de qualificação não se reescreve em SQL

A tentação é o `WHERE lead_qualification.intencao IS NOT NULL AND ... IS NOT NULL` com os quatro `CAMPOS_OBRIGATORIOS`. **Recusado:** cria uma segunda fonte de verdade para a regra da RN-05.3, e a divergência já tem data marcada — `esta_qualificado` recebe `recusados` por parâmetro, e a docstring registra que quem grava recusa é a TEC-148; um campo recusado não conta mesmo com valor na coluna. O SQL ingênuo contaria.

Com a D2 o predicado vira `qualificado_em IS NOT NULL AND qualificado_em BETWEEN :de AND :ate`. A regra Python continua sendo a única regra; a coluna é só o registro de quando ela passou a valer. **É por isso que a D2 não é opcional** — sem ela, ou se duplica a regra ou não há etapa Qualificado.

## D5 — sem cache até a medição pedir

Duas exigências são confundidas com facilidade, e só uma pede cache.

**"Atraso máximo de 60 segundos" (RN-17.3) é teto de defasagem.** Consulta ao vivo tem defasagem zero e satisfaz o teto de graça. Cache não ajuda esse requisito — ele só o consome.

**Quem pode exigir cache é a RNF-04**, p95 ≤ 2s com 1.000 leads. E isso é número, não palpite: o teste `perf` se escreve primeiro, no molde da TEC-159 (`tests/perf/test_busca_latency.py`), com a evidência medida na docstring, e **o cache só entra se o p95 estourar.** Se entrar: Redis, chave derivada da tupla de filtros, TTL ≤ 60s para o teto da RN-17.3 continuar valendo, e fail-open no molde de `infra/rate_limit.py` — Redis fora do ar devolve dado vivo, nunca erro.

SSE (`GET /api/v1/eventos/stream`, §6.6 do SRS) fica **fora**: o Gherkin da card diz "o dashboard é recarregado", que é leitura, não empurrão. É card própria.

## D6 — o filtro por corretor é o funil *dos leads daquele corretor* (RECUSADO na borda desde a revisão)

> **Emenda (revisão, 24/09/2026): a borda recusa este filtro com 422, e a D6 abaixo descreve o que acontecerá quando a TEC-166 existir.**
> `handoffs.corretor_id` **nunca é escrito em produção** — a Emenda E-01 da RN-16.2 diz isso por extenso, e alocar corretor é a TEC-166. A coluna é nula em toda linha, então o filtro devolvia **200 com o funil inteiro zerado, para qualquer corretor**, e a gerente leria "este corretor não recebeu lead nenhum" sobre quem aceitou dezenas de handoffs. Zero universal com cara de medição é a mesma classe de defeito que a D1 recusou para `Agendado`, e a L2 abaixo — escrita antes da revisão — descrevia algo muito mais fraco que a verdade. A consulta continua escrita, testada e correta, esperando a TEC-166; o que se recusa é o **pedido**, não a forma do recorte.


`corretor_id` só existe em `handoffs`. **Não há corretor antes do repasse** — nas etapas Novo, Em conversa, Qualificado e Recomendado o lead não tem dono.

Filtrar por corretor restringe às conversas cujo handoff é dele, e conta essas mesmas conversas nos estágios anteriores. É o funil retroativo dos leads que acabaram com ele, e responde à pergunta real da gerente ("onde vaza o funil deste corretor"). Mas **a leitura ingênua — "leads novos do corretor" — não existe**, e um lead que ainda não foi repassado não aparece em filtro de corretor nenhum. Fica na docstring do repositório e no comentário da card.

## D7 — a taxa de handoff no SLA exclui `sla_limite_em IS NULL` do denominador

Não é decisão desta card: a Emenda E-01 da RN-16.3 (TEC-178) já a tomou e a escreveu para quem fosse calcular a RN-17.1. Um handoff escalado sem destinatário tem `sla_limite_em` nulo para sempre, e `dentroDoSla` sai `true` **por vacuidade, nunca por pontualidade** — incluí-lo infla a taxa.

O denominador é `sla_limite_em IS NOT NULL`, e a spec de origem é citada no comentário da consulta.

## D8 — o endpoint segue o padrão do repo, inclusive onde ele é incomum

- `src/mobia/api/routes/metricas.py`, `APIRouter(prefix="/api/v1/metricas", tags=["metricas"])`.
- Registrado em `main.py` **dentro do `if settings.catalogo_admin_token:`**, com import lazy, como os outros quatro routers. Fora dele a rota não é exposta — é a D1 da TEC-156: rota que não existe não pode ser exposta por erro de configuração.
- Guardado com `_: None = Depends(exigir_admin)`. **Não há papel `GERENTE` utilizável**: `corretores.gerente` é booleana de roteamento de escalada de SLA, não autorização HTTP, e JWT com papéis é a TEC-201. O SRS §6.6 prevê Bearer JWT — mesma divergência que a Emenda E-01 da RN-19.5 já declarou para o módulo administrativo, aqui estendida a esta rota.
- **Resposta é `dict[str, object]` montado à mão, em camelCase, sem `response_model`.** É o padrão dos cinco routers existentes; usar `response_model` aqui seria o arquivo destoante.
- Sessão por `async with get_sessionmaker()() as session:`. **Não existe dependency `get_session`** neste repo.
- As consultas agregadas moram num `src/mobia/domain/metricas/repositorio.py` novo: funções livres, `session` posicional, o resto keyword-only, sem commit — a convenção dos dez repositórios existentes.

## D9 — o front é `frontend/` no monorepo, com Route Handler como proxy

O token nunca chega ao navegador: vive em env do servidor Next.js, e o browser chama um Route Handler do próprio Next, que reencaminha ao FastAPI com o header `X-Admin-Token`. A alternativa — browser falando direto com o FastAPI — foi recusada por pôr um segredo compartilhado de admin total no cliente e exigir CORS.

**E o proxy resolve um problema que a alternativa criaria.** `RateLimitPorIP` são 100 requisições por minuto **por IP**, e `confiar_em_forwarded_for` é `False` por omissão, então o FastAPI vê o IP do servidor Next e não o de cada navegador: todos os painéis abertos somam no mesmo balde. Com `revalidate: 60` no Route Handler — que é o mesmo teto de defasagem da RN-17.3, e não coincidência —, N navegadores viram **uma** chamada por minuto ao FastAPI. Sem o proxy, cem gerentes com o painel aberto estourariam o limite e levariam 429.

O SSR do Next atende o LCP da RNF-04, que é como o SRS justificou a escolha por Next em vez de SPA.

**O CI ganha um job novo** para o lado JS. Os três gates estáticos de Python não olham para `frontend/`, e `ruff`/`mypy` não devem passar a olhar: o escopo deles é `src tests alembic evals scripts` e nenhum desses diretórios ganha arquivo nesta card.

## D10 — O funil é COORTE (emenda: decidida ao escrever o plano)

Não estava neste desenho e devia estar. Duas semânticas eram possíveis.

**Por atividade** — contar eventos de cada tipo ocorridos no período — a conversão entre etapas pode passar de 100%: um lead recomendado em agosto pode ter nascido em julho, e `Recomendado / Em conversa` daria mais que 1. A RN-17.2 pede "taxa de conversão", e uma taxa acima de 100% não é conversão, é erro de leitura.

**Por coorte** — os leads cujo primeiro contato caiu no período, contando quantos *desses* alcançaram cada etapa, inclusive depois do fim do período — essa fonte de conversão acima de 100% desaparece. É o que a gerente quer dizer com "onde estamos perdendo lead".

**Emenda (revisão, 24/09/2026): a coorte NÃO garante monotonia.** Esta seção afirmava "monotônica e ≤ 100% por construção", e era falso — a coorte dá o recorte comum, não a inclusão entre etapas, e as cinco contagens são consultas independentes. Dois caminhos conhecidos para passar de 100%: enquanto a **L1** durar, `Qualificado` conta só a partir da `0040` enquanto `Recomendado` conta tudo (40 recomendados e 1 qualificado dão 4000%); e o lead que qualifica no primeiro turno fica fora de `Em conversa`, que exige mais de uma fala. Nenhum dos dois é erro de consulta — são fatos sobre os dados, e estão na docstring de `metricas/repositorio.py` e na Emenda E-01 da RN-17.2.

**Escolhida: coorte, e todos os indicadores herdam o mesmo recorte.** `conversasAtivas` é quantas da coorte seguem `ATIVA`, `taxaQualificacao` é a fração dela que qualificou, e as duas médias de tempo são sobre ela. Um recorte só em todo o payload; misturar coorte e atividade no mesmo cartão é o defeito que esta decisão evita.

## Emenda à D9 — Server Component no lugar do Route Handler

A D9 acima especifica um Route Handler como proxy. O plano do frontend usa, em vez dele, um **Server Component que busca o FastAPI direto no servidor**. A propriedade aprovada é idêntica — o token vive em env do servidor e nunca chega ao navegador — e o argumento do rate limit também continua valendo, porque `fetch(..., { next: { revalidate: 60 } })` põe a resposta no Data Cache do Next e N navegadores viram uma chamada por minuto ao FastAPI. O que some é um hop e um arquivo.

## Emenda à D5 — o cache foi recusado, e a recusa é medida

A D5 condicionou o cache à medição. Ela foi feita em 24/09/2026 (`tests/perf/test_funil_latency.py`): **p95 de 0,068 s sem filtro e 0,065 s por corretor, com 1.000 leads, contra o teto de 2 s da RNF-04** — cerca de 29× de margem. Não há cache nesta card. A docstring do teste registra quando reabrir a conta: base dez vezes maior, ou p95 passando de ~1 s.

## Contrato

`GET /api/v1/metricas/funil`, query `de`, `ate`, `canal`, `intencao`, `temperatura`, `corretorId`.

```json
{
  "etapas": [
    { "nome": "Novo", "quantidade": 320, "disponivel": true, "conversaoDaAnterior": null },
    { "nome": "Em conversa", "quantidade": 268, "disponivel": true, "conversaoDaAnterior": 0.8375 },
    { "nome": "Qualificado", "quantidade": 141, "disponivel": true, "conversaoDaAnterior": 0.5261 },
    { "nome": "Recomendado", "quantidade": 118, "disponivel": true, "conversaoDaAnterior": 0.8369 },
    { "nome": "Agendado", "quantidade": null, "disponivel": false, "conversaoDaAnterior": null },
    { "nome": "Handoff aceito", "quantidade": 39, "disponivel": true, "conversaoDaAnterior": null }
  ],
  "indicadores": {
    "leadsNovos": 320,
    "conversasAtivas": 87,
    "taxaQualificacao": 0.44,
    "distribuicaoPorTemperatura": { "QUENTE": 41, "MORNO": 63, "FRIO": 37 },
    "tempoMedioPrimeiraRespostaSeg": 4.2,
    "tempoMedioQualificacaoSeg": 512.0,
    "slaHandoffCumpridoPct": 0.87,
    "agendamentosCriados": null,
    "agendamentosConfirmados": null,
    "agendamentosRealizados": null,
    "taxaNoShow": null
  },
  "indisponiveis": ["agendamentosCriados", "agendamentosConfirmados", "agendamentosRealizados", "taxaNoShow"]
}
```

**`conversaoDaAnterior` é nula em duas situações diferentes, e elas não se confundem**: na primeira etapa, porque não há anterior; depois de `Agendado`, porque a anterior não tem número. É por isso que `Handoff aceito` sai com conversão nula apesar de ter quantidade — a conversão de `Agendado` para ele não é calculável. Uma conversão que pulasse `Agendado` e dividisse `Handoff aceito` por `Recomendado` seria um número plausível e errado.

**O contrato diverge do §6.6 do SRS**, que é mais pobre que a própria RN-17.1: lá não há `indicadores` além de quatro campos soltos, não há conversão entre etapas (que a RN-17.2 exige), não há `temperatura` na query (que a RN-17.3 exige) e não há distribuição por temperatura. Emenda ao SRS, não reescrita.

## Testes

- **`tests/unit/`** — a aritmética de conversão entre etapas, incluindo as duas origens de `null`; a montagem da resposta com etapa indisponível. Sem banco, é o loop rápido.
- **`tests/integration/`** — um arquivo por grupo de consulta, mais `test_rota_de_metricas.py` no molde de `test_rota_de_corretores.py` (fixture `app_com_token`, que põe `CATALOGO_ADMIN_TOKEN` no ambiente **antes** do `create_app`, porque o router não é registrado sem ele). Cobre 403 sem token, os cinco filtros, e a etapa indisponível.
- **`tests/features/`** — os três cenários exercitáveis do Gherkin da card. O quarto, a CA-17.1 do agendamento, não é: ver a D1.
- **`tests/perf/`** — `test_funil_latency.py`, marcado `perf`, com 1.000 leads e a evidência medida na docstring. Fora do run padrão pela mesma razão da TEC-159: medir p95 em runner compartilhado seria flake.
- **Front** — o job novo de CI roda os testes do `frontend/`.

O filtro por canal exercita **os dois canais que existem**. Até 24/09/2026 esta seção dizia que só `whatsapp` era produzido pelo ingresso real e que o canal web "não existe" — a **TEC-124 mergeou na `main` naquele mesmo dia** e trouxe o widget, que grava `channel=CANAL_WEB` pelo mesmo `IngestionService` do webhook. É a classe de defeito que a TEC-296 nomeou: prosa escrita no presente que o merge de outra card tornou falsa. Os literais de canal passam a sair de `messages/canais.py`.

## Emendas ao SRS

- **RN-17.1** — os quatro indicadores de agendamento saem `null` com `disponivel: false` enquanto RF-11 e RF-12 não existirem (D1).
- **RN-17.2** — a etapa `Agendado` idem, e a conversão para `Handoff aceito` é nula por consequência (D1).
- **§6.6** — o corpo de `GET /api/v1/metricas/funil` passa ao contrato acima, que cobre a RN-17.1 e a RN-17.2 inteiras; a query ganha `temperatura`; a autenticação é `X-Admin-Token` via `exigir_admin`, e não Bearer JWT, até a TEC-201 (D8).
- **CA-17.1** — não exercitável nesta card (D1).

## Lacunas declaradas

- **L1 — não há backfill de `qualificado_em`.** O instante nunca foi gravado. A etapa Qualificado conta só a partir da migration `0040`, e o número é baixo nas primeiras semanas.
- **L2 — o filtro por corretor não funciona de todo, e é recusado com 422.** Não é só que lead sem handoff some: `handoffs.corretor_id` nunca é escrito, então *nenhum* lead aparece. Ver a emenda na D6. Volta com a TEC-166.
- **L3 — a taxa de no-show não volta com a RF-12 sozinha:** exige que alguém marque a visita como realizada ou não, que é regra de produto ainda não escrita em lugar nenhum.

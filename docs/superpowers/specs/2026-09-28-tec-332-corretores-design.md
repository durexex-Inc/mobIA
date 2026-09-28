# TEC-332 — Cadastrar, editar e desativar corretores

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-332](https://eduardodurieuxlopes.atlassian.net/browse/TEC-332) — História, Should (MoSCoW), prioridade High. Origem: RF-FE-11, RN-FE-11.1 a 11.3 (SRS mobIA Frontend v1.0) · TEC-196.

**A história:** *"Como Rafael, administrador da imobiliária, quero manter os corretores pela interface, para que a alocação use especialidade, região e capacidade atualizadas sem depender de script."*

**Só frontend.** O CRUD do backend (TEC-196) já está entregue e guardado por `GERIR_CORRETORES` (TEC-202) — `POST`, `GET`, `GET /{id}` e `PATCH /api/v1/corretores` (`src/mobia/api/routes/corretores.py`). Não há rota `DELETE` de propósito (D6 do desenho da TEC-196): desativar é `ativo = false`.

**Desbloqueada.** A card cita bloqueio pela visibilidade por papel (TEC-312), que está **Feito**. `PERMISSOES_DE_ADMIN` (`lib/navegacao.ts`) já inclui `GERIR_CORRETORES`, e a página `/admin` já lista "Corretores" com a card TEC-332 e sem `href` — esta é a card que preenche esse `href`.

## O que a card pede e o que a API de hoje entrega

Duas frases da card não batem com o contrato real da TEC-196, e é preciso decidir contra qual das duas construir.

### D1 — Horário é uma janela só, não "por dia da semana"

A card lista *"horário por dia da semana"* entre os campos do formulário. A API não tem isso: `Corretor` guarda `horario_inicio`/`horario_fim`, uma janela única (`horarioInicio`/`horarioFim` no corpo). A própria TEC-196 já declarou essa divergência (D2 do desenho dela, emenda ao modelo da seção 5) e a justificou: é a forma que `app/config.py` já usa para janela de atendimento.

Construir "por dia da semana" exigiria mudar o modelo do backend — fora do escopo de uma card rotulada `frontend`. **Decisão: o formulário tem dois campos, início e fim, em hora inteira (0–23, início < fim)**, exatamente o que a API aceita e valida. Sábado meio período continua não representável, como a TEC-196 já registrou.

### D2 — Regiões são texto livre, não um "vocabulário do backend"

A card diz *"regiões (vocabulário do backend)"*. Não existe vocabulário nenhum: `regioes_atuacao` é `ARRAY(String(120))` sem enum, sem `CHECK` de conteúdo (só de cardinalidade > 0), e a L4 do desenho da TEC-196 já registrou que "zona sul" não é bairro do catálogo e que não há endpoint de bairros distintos para oferecer como lista. `dobrar()` normaliza na escrita (case/acento), não restringe o vocabulário.

**Decisão: campo de texto livre, com uma região por linha/chip**, adicionada uma de cada vez pelo administrador — sem `<select>` porque não há de onde popular as opções. Fica declarado como divergência da card no comentário do PR.

### D3 — O teto de 20 na capacidade diária só existe nesta tela

O Gherkin da própria card exige capacidade de 1 a 20, com 21 recusado. A API só garante `>= 1` (`CAPACIDADE_MINIMA`, `Field(ge=CAPACIDADE_MINIMA)`, `CHECK capacidade_diaria >= 1`) — **não há teto de 20 em lugar nenhum do backend**, nem no Pydantic nem no `CHECK`.

Mudar o backend está fora do escopo desta card (é rota e schema da TEC-196, não desta). **Decisão: o formulário valida `1–20` no cliente** (`min`/`max` do `<input type="number">` e checagem antes do `fetch`), com o Gherkin exercitado até onde esta tela alcança. Fica declarado como lacuna no comentário do PR: quem chamar a API diretamente ainda pode gravar capacidade > 20.

### D4 — `gerente` fica fora do formulário

O corpo do `POST`/`PATCH` aceita `gerente` (RN-16.3, TEC-178 — quem recebe a escalada de SLA vencido), mas a card não o lista entre os campos e o Gherkin não o exercita. Não é campo desta história: entra como `false` (o default do backend) em todo cadastro feito por esta tela, e não aparece na edição. Ampliar o formulário para cobri-lo seria construir para um pedido que a card não fez.

### D5 — Reativar não é desta card

A card nomeia três verbos: *"Cadastrar, editar e desativar"*. Não há "reativar". O `PATCH` aceita `ativo: true`, então o backend permite — mas esta tela não oferece o controle. Fica fora de escopo, sem imaginar um botão que ninguém pediu.

## Decisões de interface

### D6 — Lista mostra ativos e inativos juntos, com o inativo marcado

A card manda: *"A lista indica visualmente (com texto) corretores inativos e o generalista de plantão."* Isso exige buscar os dois estados juntos — `GET /api/v1/corretores` sem `?ativos=true` (o parâmetro `ativos` do backend, apesar do nome, significa "somente ativos"; omitido ou `false`, devolve todos). A cada corretor inativo, um rótulo de texto "Inativo"; a cada plantonista, "Generalista de plantão" — nunca só cor, para não depender de percepção de cor (mesmo padrão de `Vazio`/`ErroDeCarga`, que já são texto).

### D7 — Criar e editar são o mesmo formulário, com desativar fora dele

Um formulário modal/inline no molde de `EdicaoDaQualificacao.tsx` (`components/`): estado local, `sujo`/`registrarAlteracaoNaoSalva` para o aviso de inatividade (TEC-311), `PATCH` parcial na edição via `model_fields_set`-like dict (só o que mudou), `POST` completo na criação. Desativar é uma ação separada, com `window.confirm`-like modal de confirmação que **cita o texto exigido pela card**: "o histórico e os leads atribuídos são mantidos".

### D8 — As mutações passam pelo `/bff/*`, com quatro entradas novas na allowlist

Hoje `ROTAS_PERMITIDAS` (`lib/servidor/bff.ts`) não tem nenhuma entrada de `corretores`. Entram quatro:

| método | padrão |
|---|---|
| `GET` | `api/v1/corretores` |
| `POST` | `api/v1/corretores` |
| `GET` | `api/v1/corretores/*` |
| `PATCH` | `api/v1/corretores/*` |

A listagem inicial (o `GET` da carga da página) usa `chamarApi` direto do Server Component, como a fila do titular — não precisa do proxy. O que precisa do `/bff/*` é o que o `'use client'` do formulário dispara depois de montado: criar, editar e desativar (que é um `PATCH` com `{ ativo: false }`).

Não entra `GET /api/v1/corretores/{id}` isolado na allowlist do cliente: a tela não tem uma rota de detalhe própria, edição parte do que a listagem já carregou (mesmo padrão da D4 do desenho da TEC-341, que resolve o "detalhe" varrendo a lista já buscada, por não haver `GET` por id "isolado" que valha a pena expor a mais).

### D9 — 409 de e-mail duplicado vira erro de campo

A API responde `409` com `detail: "e-mail ja cadastrado"` quando o e-mail colide (`EmailJaCadastrado`). A tela mostra isso como erro do campo e-mail, não como erro geral — mesmo padrão de `recusaDe` em `lib/qualificacao.ts`, adaptado para `corretores`.

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Cadastrar corretor válido | exercitado |
| Faixa de capacidade diária (0/1/20/21) | exercitado **na validação do cliente** — ver D3 |
| Desativar mantendo o histórico | exercitado; o texto de confirmação é literal |

## Fora de escopo

Horário por dia da semana (D1 — é mudança de backend, TEC-196). Vocabulário controlado de região (D2 — não existe endpoint). Teto de 20 aplicado no backend (D3). Campo `gerente` (D4). Reativar (D5). Tela de detalhe de um corretor isolado (D8).

# TEC-333 — Cadastrar e editar imóveis, com aviso de reindexação

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-333](https://eduardodurieuxlopes.atlassian.net/browse/TEC-333) — História, Should (MoSCoW), prioridade High. Origem: RN-FE-12.1 a 12.3 (SRS mobIA Frontend v1.0) · TEC-197.

**A história:** *"Como Rafael, administrador da imobiliária, quero corrigir preço, status e ficha dos imóveis pela interface, para que o agente não recomende imóvel com dado errado."*

**Só frontend.** O CRUD do backend (TEC-197) já está entregue: `GET`/`POST`/`PATCH /{id}`/`DELETE /{id}` em `/api/v1/imoveis`, todas guardadas por `GERIR_CATALOGO` (`src/mobia/api/routes/imoveis.py`). `PERMISSOES_DE_ADMIN` (`lib/navegacao.ts`) já inclui `GERIR_CATALOGO`, e `/admin` já lista "Imóveis" com a card TEC-333 e sem `href`.

**Desbloqueada.** As duas dependências da card — TEC-197 (API) e TEC-312 (visibilidade por papel) — estão **Feito**.

## D1 — O formulário tem mais campos do que a card lista, porque o backend exige

A card lista *"título, bairro, preço, quartos, vagas, área útil, condomínio, diferencial, status"*. Mas a validação do `POST`/`PATCH` é **a mesma da importação em lote** (`parser._converter`, reusada por `cadastro._gravar` — D2 do desenho da TEC-197), e ela também exige, como obrigatórios: `codigo`, `descricao`, `tipo`, `operacao`, `cidade`, `uf`, `suites`, `banheiros` — nenhum deles citado pela card. Sem eles, todo `POST` volta `422` com "campo ausente".

**Decisão: o formulário inclui os oito campos que faltam**, além dos que a card lista. Não dá para construir só o que a card nomeia — o resultado nem salvaria. Ficam de fora, por serem opcionais no backend e não exercitados pelo Gherkin: `zona`, `latitude`, `longitude`, `fotos` (a própria card já declara fotos fora de escopo) e `iptuMensal`.

### O preço depende da operação

*"Preço"* no singular da card não existe como coluna única: há `precoVenda` e `precoAluguel`, e a regra é "ao menos um dos dois". O formulário tem um campo **Operação** (Venda/Aluguel/Ambos — mesmo vocabulário de `Operacao`), que decide quais dos dois campos de preço aparecem: Venda mostra só `precoVenda`, Aluguel só `precoAluguel`, Ambos os dois.

### "Diferencial" é `caracteristicas`

Não existe coluna `diferencial`. O Gherkin diz *"Rafael altera o diferencial para 'Vista para o mar'"*, e a única coluna que alimenta o documento de indexação além de título/descrição/tipo/bairro (D-do-desenho-da-TEC-197, linha sobre `documento_de`) e que é uma lista de texto livre é `caracteristicas`. **Decisão: "diferencial" na tela é o campo `caracteristicas`**, uma lista de texto (uma por linha/chip, no mesmo padrão de `regioesAtuacao` da TEC-332) — não um campo de texto único.

## D2 — Não há validação client-side de faixa; o erro do backend é mostrado como veio

Ao contrário da TEC-332 (onde o backend não tinha teto de capacidade e a tela precisou inventar um), aqui **o backend já valida tudo com mensagem legível**: `titulo ausente`, `area_util_m2 fora da faixa: '5000000' -- esperado entre -2147483648 e 2147483647`, `preco_venda implausivel: ... -- esperado entre 1000 e 500000000 reais`, etc. (`parser._converter`). A resposta de erro (`cadastro.CadastroRecusado.detalhe`) é **uma string única**, com os motivos concatenados por `; ` — não uma lista estruturada por campo como o `422` do Pydantic que a TEC-332 tratava.

**Decisão: o formulário só valida "campo vazio" no cliente** (para os obrigatórios, evitando um `fetch` óbvio de irá falhar) e mostra a `string` de erro do backend **inteira, num aviso geral do formulário** — não por campo, porque não dá para separar "titulo ausente; bairro ausente" em dois campos sem reimplementar o parser do lado de cá, e reimplementá-lo é exatamente o "segundo validador" que a D2 do desenho da TEC-197 recusou para o próprio backend.

## D3 — "Aviso de reindexação" é o campo `reindexa` da resposta, sem lógica própria

A card pede que a tela informe se a alteração *"vai reindexar... com a mesma regra do backend"*. Essa regra já está calculada: o `PATCH` devolve `reindexa: true|false` (D3 do desenho da TEC-197 — comparação do documento antes/depois, a mesma função da varredura). **A tela não recalcula nada**: lê o campo da resposta e mostra uma de duas frases fixas.

Isso só existe na edição. O `POST` de criação não devolve `reindexa` (é sempre um imóvel novo — a varredura o pega no próximo ciclo, o que não é uma "alteração" a avisar), e o Gherkin só exercita o aviso nos dois cenários de edição.

## D4 — "Retirar das buscas" é o `DELETE`, com confirmação simples

A card nomeia o botão: *"Retirar das buscas"*. É o `DELETE /api/v1/imoveis/{id}` (204, sem corpo), que é exclusão lógica — `status = INATIVO` (D4 do desenho da TEC-197). Ao contrário do e-mail digitado da TEC-342 (dado pessoal, ação mais grave), aqui basta uma confirmação de duas etapas no molde de `DesativarCorretor.tsx` (TEC-332): um `<dialog>` que explica a consequência, sem exigir digitar o código do imóvel — a própria card não pede confirmação forte, e não há dado pessoal em jogo.

Texto da confirmação (não é citação literal da card — ela não dá um texto pronto, ao contrário do "histórico e leads mantidos" da TEC-332 — mas cobre o que o Gherkin afirma como consequência): *"O imóvel deixa de ser recomendado pelo agente. Continua visível aqui, marcado como retirado."*

**Não há botão de reativar.** Reativar é editar o campo Status de volta para "Disponível" no mesmo formulário de edição — o Status já é um dos campos que a card pede, então não é uma tela nova: é o mesmo `PATCH` que qualquer outra edição usa. Reimportar o código também reativa (L1 do desenho da TEC-197) — comportamento do backend, não desta tela.

## D5 — Código não se edita

`codigo` é a chave do upsert da importação (D2 do desenho da TEC-197); um `PATCH` que o mude volta `422 codigo_imutavel`. **O campo aparece desabilitado na edição**, e só é editável na criação.

## D6 — A lista mostra todos os status, sem filtro por padrão

O terceiro cenário do Gherkin exige que o imóvel retirado *"continue visível na administração como retirado"*. `GET /api/v1/imoveis` sem `?status=` devolve todos (D5 do desenho da TEC-197 — o filtro só entra quando pedido). **Decisão: a carga inicial da página não manda `status`**, e cada linha mostra o status por texto (nunca só cor) — mesmo padrão do rótulo "Inativo" da TEC-332.

Sem paginação nesta primeira versão: a lista usa `limite` padrão do backend (50) sem consumir `proximoCursor` — a card não pede busca nem paginação, e a TEC-197 já declara que a listagem "da administração" é separada da vitrine. Fica registrado como lacuna: catálogos com mais de 50 imóveis não mostram os demais nesta tela ainda.

## D7 — As mutações passam pelo `/bff/*`; a carga inicial não

Mesma arquitetura da TEC-332 (D8 de lá): a listagem inicial usa `chamarApi` direto do Server Component; criar, editar e retirar (client-side, depois de montado) passam pelo proxy. Quatro entradas novas em `ROTAS_PERMITIDAS` (`lib/servidor/bff.ts`):

| método | padrão |
|---|---|
| `GET` | `api/v1/imoveis` |
| `POST` | `api/v1/imoveis` |
| `PATCH` | `api/v1/imoveis/*` |
| `DELETE` | `api/v1/imoveis/*` |

Não entra `GET /api/v1/imoveis/{id}` isolado (mesma razão da D8 da TEC-332: a edição parte do que a listagem já carregou) nem `GET /api/v1/imoveis/importacoes` (o relatório de importação é decisão de produto que esta card não toma — não está no Gherkin nem nas regras de negócio dela).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Alterar só o preço não reindexa | exercitado — lê `reindexa: false` da resposta |
| Alterar o diferencial reindexa | exercitado — "diferencial" é `caracteristicas` (D1), lê `reindexa: true` |
| Retirar das buscas | exercitado — `DELETE`, confirmação, status vira "Retirado" na lista |

## Fora de escopo

Fotos e importação em lote (a própria card exclui). Zona, latitude/longitude, IPTU (D1 — opcionais, não exercitados). Relatório da última importação (D7 — não é desta card). Paginação e busca na listagem (D6 — lacuna declarada). Reativar por botão dedicado (D4 — é editar o Status).

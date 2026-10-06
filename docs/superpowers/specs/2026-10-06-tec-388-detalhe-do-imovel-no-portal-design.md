# TEC-388 — Ver detalhes e fotos de um imóvel no portal do cliente

**Status:** em desenho (06/10/2026)
**Card:** [TEC-388](https://eduardodurieuxlopes.atlassian.net/browse/TEC-388)
**Branch:** `feat/tec-388-detalhe-do-imovel-no-portal`
**Depende de:** TEC-387 (portal público de busca, já mergeado)

## Pergunta não bloqueante da card, resolvida antes do desenho

"Quais campos do imóvel (condomínio, IPTU, características) ficam públicos no detalhe?" — a própria descrição da card já responde isso no **Escopo**: "tela de detalhe com fotos, descrição, características, área, condomínio/IPTU quando existirem" está **IN scope**. A decisão de produto já estava na card; o que faltava era a lista explícita dos campos do modelo que NÃO viram público (ver D2).

## O que existe quando a card começa

- **A busca pública (TEC-387) só devolve resumo.** `GET /portal/imoveis` (`src/mobia/api/routes/portal.py`) devolve `id, codigo, titulo, bairro, preco, quartos, vagas, areaUtilM2, scoreMatch` — nada de descrição, características, fotos ou os dois preços (venda/aluguel).
- **O detalhe administrativo existe, mas é `GERIR_CATALOGO`.** `GET /api/v1/imoveis/{imovel_id}` devolve `cadastro.como_api(imovel)`, que expõe TODOS os campos públicos do modelo via o dict `CAMPOS` (`domain/catalogo/cadastro.py`) — inclusive `codigo` e `status`, que são administrativos. Não filtra por status: um GET direto no id de um imóvel `VENDIDO`/`INATIVO` funciona normalmente para quem tem a permissão.
- **A leitura de foto também é `GERIR_CATALOGO`**, e também não olha para o status do imóvel — `GET /api/v1/imoveis/{imovel_id}/fotos/{foto_id}` serve bytes para quem tiver a permissão, imóvel disponível ou não.
- **O identificador de foto é um UUID gerado no upload**, sem índice/ordem guardados à parte; a extensão (jpg/png/webp) também não é guardada — a leitura tenta as três em sequência até achar (`domain/catalogo/fotos.py`).
- **`CardDeImovel` já tem o mecanismo de link** (`imovel.url`), mas hoje é sempre nulo (L1 da TEC-364: "o catálogo não guarda a página do imóvel") e o comportamento é de link **externo**: `target="_blank"`, `rel="noopener noreferrer"`, texto oculto "(abre o site em nova aba)". Usar esse campo para uma rota interna (`/busca/{id}`) sem ajuste abriria a página de detalhe numa aba nova, com um texto que mentiria sobre o destino.

## D1 — Dois endpoints públicos novos, fora de `/api/v1`, no mesmo módulo `portal.py`

- `GET /portal/imoveis/{imovel_id}` — detalhe público.
- `GET /portal/imoveis/{imovel_id}/fotos/{foto_id}` — bytes da foto, público.

Mesmo motivo da TEC-387: ficam fora de `/api/v1` para não tocar `test_as_rotas_de_auth_sao_as_unicas_publicas_da_api_v1`, que tranca esse prefixo só para `auth`. As duas entram em `ROTAS_PUBLICAS` com a razão escrita.

**Por que não reguardar as rotas administrativas existentes:** `GET /api/v1/imoveis/{id}` e a leitura de foto não filtram por `status` — são a visão de quem administra o catálogo, que precisa ver e servir foto de qualquer imóvel, inclusive vendido ou inativo. Tirar a guarda delas abriria exatamente isso ao público. As rotas novas são o lugar certo para a regra "só `DISPONIVEL`" morar, sem arriscar o caminho administrativo.

## D2 — Lista explícita dos campos públicos, sem reaproveitar `cadastro.como_api`

A resposta do detalhe público é uma função nova (`payload_do_detalhe`, em `portal.py`), com uma lista de campos escrita à mão — **não** reaproveita o dict `CAMPOS` de `cadastro.py`, que é a fonte do endpoint administrativo. Motivo: `CAMPOS` é mantido pensando em quem administra o catálogo, e um campo novo acrescentado ali amanhã (ex.: uma anotação interna) vazaria ao público sem ninguém decidir isso — a lista explícita exige que alguém escreva a linha nova aqui também.

**Entram:** `titulo, descricao, tipo, operacao, precoVenda, precoAluguel, condominio, iptuMensal, bairro, cidade, uf, areaUtilM2, quartos, suites, banheiros, vagas, caracteristicas, fotos` (as duas últimas, arrays completos — não o resumo de 2 itens que `diferencialDe` faz para o card da busca).

**Ficam de fora, e por quê:**
- `codigo` — referência interna do catálogo (chave do upsert), sem valor para o cliente.
- `status` — a RN já garante que só `DISPONIVEL` é servido; expor o valor cru não ajuda e, se algum dia um status novo existir, vazaria vocabulário interno.
- `zona` — taxonomia usada para casar busca por região (TEC-158); o cliente já tem `bairro`/`cidade`.
- `latitude`/`longitude` — a card não pede mapa; lacuna declarada (L1) para um card futuro, se quiserem.
- `created_at`/`updated_at`, `embedding*`, `documento_hash`, `bairro_busca` — inteiramente internos.

## D3 — Um 404 só, para "não existe" e para "existe mas indisponível"

```python
if imovel is None or imovel.status != StatusImovel.DISPONIVEL.value:
    raise HTTPException(status_code=404, detail="imovel nao disponivel")
```

A CA-03 pede "informa que o imóvel não está mais disponível, sem expor dado administrativo". Separar "não existe" (404) de "existe mas foi vendido" (outro código, ou o status no corpo) deixaria quem tem um UUID qualquer descobrir, por tentativa, quais existem no catálogo — e nunca é 403, que sugeriria um problema de permissão que não existe aqui (a rota é pública). O mesmo raciocínio vale para a rota de foto.

**Qualquer status diferente de `DISPONIVEL`** conta como indisponível — não só `VENDIDO`/`INATIVO`: `RESERVADO` e `ALUGADO` também saem do ar para o cliente, pelo mesmo critério que a busca da TEC-387 já usa (`busca.py:224`).

Um `imovel_id` que não é UUID válido (ex.: link truncado) já recebe 422 do próprio FastAPI, antes de qualquer lógica — o frontend trata 404 e 422 como o mesmo caso, no molde de `leads/[leadId]/page.tsx`.

## D4 — Fotos: reaproveita o armazém, reescreve só a URL

`ler_bytes` (novo, extraído de `imoveis.py::ler_foto` para `domain/catalogo/fotos.py`) tenta as três extensões e devolve `(bytes, mime)` — usado pelas duas rotas (admin e pública), sem duplicar o loop. A rota pública faz a mesma checagem de disponibilidade do D3 antes de servir.

**A lista `fotos` do imóvel guarda URLs administrativas** (`/api/v1/imoveis/{id}/fotos/{fotoId}`), que exigem sessão. `payload_do_detalhe` reescreve cada uma para a rota pública nova, extraindo o UUID do final do caminho e montando `/portal/imoveis/{id}/fotos/{fotoId}` — o cliente nunca vê nem usa a URL administrativa.

## D5 — Frontend: rota `/busca/[id]`, e `CardDeImovel` aprende a diferença entre link interno e externo

`frontend/src/app/busca/[id]/page.tsx` — Server Component pública, no molde de `leads/[leadId]/page.tsx` para o tratamento de erro (404/422 → tela "Imóvel não encontrado", com link de volta para `/busca`; outro erro → tela de erro de carga com "tentar de novo").

**Tipo e parser novos**, não uma extensão de `ImovelCard`: `imovelDe`/`ImovelCard` são para o resumo da busca, com uma validação estrita pensada para aquele formato. O detalhe tem campos a mais (descrição, características completas, lista de fotos, os dois preços) — um tipo `ImovelDetalhe` e um parser `imovelDetalheDe` próprios, em `frontend/src/lib/imovelDetalhe.ts`.

**`CardDeImovel` ganha uma distinção que falta hoje**: `imovel.url` sempre foi pensado como link **externo** (`target="_blank"`, texto "abre o site em nova aba") porque, até aqui, era sempre nulo (L1 da TEC-364) — nenhum consumidor real passava por aquele ramo. A listagem pública da TEC-387 passa a preencher `url` com `/busca/{id}` (rota interna), então o componente passa a distinguir: `url` começando com `/` vira link interno (`next/link`, sem `target="_blank"`, sem o texto de nova aba); qualquer outro valor mantém o comportamento de hoje. Como nenhum chamador real usa o ramo de URL preenchida ainda, a mudança não altera nada do caminho em produção (chat/preview continuam com `url` nulo) — só fica pronta para a TEC-387 passar a usá-la.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| CA-01 — detalhe com fotos e descrição | integração: `GET /portal/imoveis/{id}` com imóvel `DISPONIVEL`, fotos e descrição semeadas; componente: `busca/[id]/page.test.tsx` |
| CA-02 — sem fotos, estado vazio | componente: `fotos: []` na resposta renderiza o estado vazio, não erro |
| CA-03 — imóvel indisponível por link direto | integração: status diferente de `DISPONIVEL` e UUID inexistente devolvem o mesmo 404 sem detalhe administrativo; componente: tela "Imóvel não encontrado" |

## Lacunas declaradas

- **L1 — Sem latitude/longitude/mapa.** A card não pede, e o modelo tem os dois campos prontos para um card futuro.
- **L2 — Sem link "voltar aos resultados" preservando os filtros aplicados.** O link de volta em `/busca/{id}` vai para `/busca` sem filtro nenhum; preservar a busca anterior (ex.: via `Referer` ou um parâmetro de retorno) é refinamento de UX fora do que esta card pede.

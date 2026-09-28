# TEC-335 — Enviar e reordenar as fotos do imóvel

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-335](https://eduardodurieuxlopes.atlassian.net/browse/TEC-335) — História, Could (MoSCoW), prioridade Medium. Origem: RN-FE-12.5, RNF-FE-17 (SRS mobIA Frontend v1.0) · TEC-197.

**A história:** *"Como Rafael, administrador da imobiliária, quero enviar e ordenar as fotos de cada imóvel, para que o card no chat mostre a melhor foto primeiro."*

**Full-stack, ao contrário das TEC-332/333/334.** As três cards anteriores construíram sobre uma API já entregue por uma card-irmã (TEC-196, TEC-197). Esta não tem irmã: a própria TEC-197 declarou, na L2 do desenho dela, que *"fotos são URLs, como na importação. Upload de arquivo de foto é a TEC-335"* — ou seja, esta card é quem deve trazer o upload de verdade. Decisão tomada com o Eduardo em 2026-09-28: construir o backend que falta na mesma card, em vez de abrir uma card-irmã separada (a prioridade Could da TEC-335 já é a mais baixa das quatro, e adiar não reduz o trabalho).

## O que já existe

`Imovel.fotos` é `ARRAY(Text)`, uma lista ordenada de URLs (`domain/catalogo/models.py`). O `PATCH /api/v1/imoveis/{id}` (TEC-197) já aceita `fotos: list[str]` como substituição completa da lista, validada por `parser._converter` como qualquer outro campo. **Isso já é reordenação inteira, de graça**: mandar a mesma lista de URLs em outra ordem já reordena. Não existe, hoje: uma forma de enviar o ARQUIVO de uma foto (o admin só pode digitar uma URL que já exista em algum lugar), um lugar para guardar esse arquivo, e uma rota pública para servi-lo de volta.

`domain/midia/armazem.py` (TEC-132) já tem a abstração de armazenamento (`ArmazemDeMidia`: `guardar`/`ler`/`apagar`, com `ArmazemLocal` e `ArmazemS3`) — mas é para anexo de WhatsApp **cifrado por mensagem** (`aad_de(message_id, "midia")`). Uma foto de imóvel não pertence a mensagem nenhuma e precisa ser **legível por qualquer navegador**, inclusive o do lead, que nunca teria a chave de conteúdo. Reusar aquele armazenamento cifrado aqui seria forçar duas semânticas incompatíveis na mesma porta.

## D1 — Um armazém novo, sem cifra, reusando as duas implementações da TEC-132

`ArmazemDeMidia.guardar`/`ler`/`apagar` não cifram nada — a cifra é do CHAMADOR, antes de chamar `guardar` (a docstring do módulo é explícita: *"o que chega aqui já vem cifrado"*). Isso quer dizer que `ArmazemLocal`/`ArmazemS3` servem tal como estão para bytes em claro; só o namespace de chaves muda.

**Decisão: `armazem_da_config` (mesma função) grava a foto em claro**, sob o prefixo `fotos-de-imoveis/{imovel_id}/{foto_id}.{ext}` — separado do prefixo que a mídia de WhatsApp usa, para as duas nunca colidirem no mesmo diretório/bucket. Nenhuma classe nova de armazenamento; só uma chave diferente.

## D2 — A rota de leitura é guardada como o resto do catálogo, não pública

`Ficha.foto` (`domain/agente/apresentacao.py`) já alimenta `card_de`, o payload do `ImovelCard` do chat web (TEC-349/TEC-364) — mas **o widget ainda não desenha esse card**: não há componente em `frontend/src/widget` que leia `precoCentavos`/`diferencial`/`foto` do payload. É schema pronto para um consumidor que ainda não existe, o mesmo padrão que a D9 da TEC-196 e o D8 da TEC-333 já descreveram noutras cards. **Não é desta card inventar exposição pública para esse consumidor futuro** — quando o widget realmente desenhar o card com foto, aquela card decide como servir a imagem a um navegador de terceiro (site do tenant), com a topologia de produção (domínio público real, FastAPI atrás de proxy ou não) que só ela vai precisar resolver.

O único consumidor de verdade, hoje, é a própria tela de administração — quem precisa ver a miniatura para reordenar. **Decisão: `GET /api/v1/imoveis/{imovel_id}/fotos/{foto_id}` leva a mesma guarda `GERIR_CATALOGO`** do resto das rotas de imóveis, e é servida ao navegador do admin pelo `/bff/*` (D7) como qualquer outra leitura autenticada do painel — nenhuma rota nova sem guarda, nenhuma decisão de exposição pública tomada cedo demais.

**`Content-Type` da resposta é o que a validação do upload (D3) detectou por assinatura de bytes, nunca o que o navegador declarou no upload.** Servir de volta o `Content-Type` que o cliente mandou seria reabrir, do outro lado, a mesma classe de furo que a checagem de assinatura (D3) fecha na entrada.

## D3 — Upload valida por assinatura de bytes, não por extensão nem `Content-Type` declarado

A regra de negócio pede JPEG, PNG e WebP, até 5 MB, recusando GIF. **Confiar no `Content-Type` que o navegador manda no upload, ou na extensão do nome do arquivo, aceitaria um GIF renomeado para `.jpg` ou um HTML disfarçado de imagem** — e como a D2 serve esse mesmo arquivo de volta com o `Content-Type` que a validação decidiu, um arquivo mal identificado na entrada sairia mal identificado na saída, na cara do navegador de um lead.

**Decisão: os quatro primeiros bytes (ou mais, para WebP) são conferidos contra a assinatura real de cada formato** — sem trazer uma dependência nova (`Pillow`, `python-magic`): as três assinaturas são curtas e a checagem é código puro, no espírito de `parser.py` (que já valida à mão em vez de trazer uma lib de CSV).

```
JPEG: FF D8 FF
PNG:  89 50 4E 47 0D 0A 1A 0A
WebP: 52 49 46 46 (=="RIFF") .... 57 45 42 50 (=="WEBP", nos bytes 8-11)
```

`POST /api/v1/imoveis/{imovel_id}/fotos`, multipart, guardado por `GERIR_CATALOGO` (é o admin que sobe a foto, nunca o lead). Recusa com `422` quando: a assinatura não bate com nenhum dos três formatos; o arquivo passa de 5 MB (`FOTO_TETO_DE_BYTES = 5 * 1024 * 1024` — constante própria, não o `midia_teto_bytes` de 25 MB da mídia de WhatsApp, que é outro limite para outro domínio); o imóvel já tem 15 fotos (`FOTO_LIMITE_POR_IMOVEL = 15`). A imagem aceita é gravada com um `foto_id` novo (`uuid4`), acrescentada ao FIM de `imovel.fotos` (a mais nova entra por último; reordenar para o topo é ação explícita do administrador, D5), e a rota devolve o imóvel completo (`cadastro.como_api`, mesmo formato do `POST`/`PATCH` da TEC-197) — sem `reindexa`: fotos não fazem parte de `documento_de` (`domain/catalogo/documento.py`), então a varredura de indexação nunca olha para essa mudança.

## D4 — Remover uma foto é o `PATCH` que já existe; não há rota de exclusão nova

A lista completa de fotos já é regravável pelo `PATCH /api/v1/imoveis/{id}` existente (`fotos: list[str]`). **Reordenar e remover são a mesma operação do ponto de vista do backend**: mandar a lista de URLs numa ordem diferente, ou mais curta. Nenhuma rota nova para isso.

**Lacuna declarada: remover uma foto da lista não apaga o arquivo do armazém.** O `PATCH` genérico não sabe que um item que saiu de `fotos` era uma chave de armazenamento — ele só grava a lista de strings que chegou. Implementar a limpeza exigiria a rota de edição genérica saber decodificar URL de foto própria versus URL externa colada (a importação também aceita `fotos` como URLs arbitrárias, TEC-197), o que acopla o `cadastro.editar()` genérico a uma regra que só faz sentido para fotos enviadas por esta card. Fica como lixo aceito — mesmo argumento que justificou não implementar `excluir_em` separado na D4 do desenho da TEC-197 (L1 de lá): decisão de produto que esta card não toma sozinha.

## D5 — Reordenação na tela: arrastar e por botões, ambos escrevendo a mesma lista

A tela (extensão de `/admin/imoveis`, TEC-333) ganha uma seção de fotos por imóvel: miniaturas em ordem, cada uma com botões "mover para cima"/"mover para baixo" (o Gherkin exige *"usando apenas o teclado"* — os botões são focáveis e acionáveis por Enter/Espaço, sem depender de arrastar) e, adicionalmente, arraste do mouse via `draggable`/eventos nativos (sem biblioteca nova de drag-and-drop — a lista tem no máximo 15 itens, e a reordenação por HTML5 drag events nativos já é suficiente).

**Um único `PATCH` por reordenação, com a lista inteira já na nova ordem** — não um `PATCH` por posição movida. Mover a foto 3 para o topo é: montar a nova lista localmente, mandar `fotos: [novaOrdem]` uma vez, aguardar a resposta antes de deixar mover de novo (evita duas reordenações em voo pisando uma na outra).

## D6 — O envio na tela valida ANTES do upload, mas o backend continua sendo a verdade

Mesmo padrão da D2 da TEC-334 (checar 10 MB na seleção do CSV): o tamanho (5 MB) e a extensão aparente são checados no cliente antes do `POST`, para a resposta ser instantânea — mas **a checagem real é a assinatura de bytes do backend (D3)**. Um arquivo `.jpg` que na verdade é outra coisa passa pela checagem de extensão do cliente e é recusado pelo servidor; a mensagem de erro do `422` é mostrada como veio, no molde do aviso geral da TEC-333 (D2 de lá) — não há por que reimplementar a checagem de assinatura em JavaScript só para dar a mesma mensagem mais cedo.

## D7 — Upload e leitura passam pelo `/bff/*`, com o mesmo `<img>` autenticado do resto do painel

Como a leitura (D2) agora exige `GERIR_CATALOGO`, ela também precisa do proxy: `<img src="/bff/api/v1/imoveis/{id}/fotos/{fotoId}">` funciona porque o navegador manda o cookie de sessão em toda requisição de mesma origem, `<img>` inclusive — não é preciso nenhum tratamento especial, e é o mesmo motivo por que o resto do painel nunca aponta direto para o host do FastAPI. Duas entradas novas em `ROTAS_PERMITIDAS` (`lib/servidor/bff.ts`):

| método | padrão |
|---|---|
| `POST` | `api/v1/imoveis/*/fotos` |
| `GET` | `api/v1/imoveis/*/fotos/*` |

(A reordenação já usa o `PATCH api/v1/imoveis/*` que a TEC-333 abriu — nenhuma entrada nova para ela.)

## Migration

Nova: `alembic/versions/0069_fotos_do_imovel_com_teto.py` (o próximo número livre). Acrescenta `CheckConstraint("cardinality(fotos) <= 15", name="ck_imoveis_fotos_teto")` — o teto de 15 vira invariante de banco, não só validação de rota, pela mesma razão que `ck_corretores_capacidade` e as outras checagens de cardinalidade deste repo existem: a rota de upload é hoje o único escritor que soma fotos, mas o `PATCH` genérico da TEC-197 também escreve `fotos` livremente, e sem o `CHECK` ele poderia gravar 20 de uma vez só colando URLs.

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Validar o arquivo de foto (JPEG 4MB aceito, WebP 5MB aceito, PNG 6MB recusado, GIF 1MB recusado) | exercitado — assinatura de bytes (D3) e teto de 5 MB, e não a extensão nem o `Content-Type` declarado |
| Limite de 15 fotos | exercitado — `422` no backend (D3) e `CHECK` no banco (Migration) |
| Reordenar só com o teclado | exercitado — botões focáveis "mover para cima"/"mover para baixo" (D5), sem depender do arraste |

## Fora de escopo

Reencodar/otimizar a imagem (redimensionar, comprimir) — a card pede aceitar o arquivo como veio, não processá-lo. Apagar o arquivo do armazém quando a foto sai da lista (D4, lacuna declarada). Bucket público de produção ou CDN para as fotos. **Servir a foto ao navegador do lead no card do chat web** (`Ficha.foto`/`card_de`, TEC-349/TEC-364) — esse card ainda não é desenhado pelo widget (`frontend/src/widget` não lê `foto` do payload hoje), então expor a imagem a um navegador de terceiro, sem sessão do painel, é decisão de quem construir aquele consumidor, não desta card (D2).

# TEC-400 — edição de imóvel numa página própria

Card: TEC-400. Épico: TEC-308. Continua a TEC-398. Referência: imagem da edição de imóvel enviada por Eduardo em 08/10/2026.

## O que muda

A edição sai do modal da TEC-398 e vai para `/admin/imoveis/[id]`. Regras de edição continuam as da TEC-333 — `PATCH` só do que mudou, `codigo` imutável, aviso de reindexação lido do `reindexa` da resposta, erro do backend mostrado inteiro — e as de foto, as da TEC-335.

## Decisões

**D1 — Página, não modal.** "Editar" na lista é um link para `/admin/imoveis/[id]`, que busca `GET /api/v1/imoveis/{id}` no servidor (`buscarImovel`). 404 e 422 (id que não é UUID) viram `notFound()`, o mesmo par que o portal trata junto (D3 da TEC-388). `FormularioDeImovel` fica só com o cadastro; a edição é `EdicaoDeImovel`. Os campos dos dois moram em `components/imoveis/CamposDoImovel.tsx`.

**D2 — Depois de salvar, a página fica.** A linha de base vira o que acabou de ser salvo e o aviso de reindexação aparece no topo, perto do "Salvar alterações". A página não usa `key={atualizadoEm}`: remontar depois do `router.refresh()` apagaria o aviso.

**D3 — "Finalidade" são duas alternâncias (Aluguel, Venda)** que viram a `operacao`: as duas ligadas são `AMBOS`, nenhuma é vazio e a validação recusa ("Escolha a operação.").

**D4 — IPTU mensal entra no formulário.** O `CorpoDoImovel` do backend já aceitava `iptuMensal`; faltava o campo. Entra também no cadastro (`pedidoDeCadastro`), `null` quando vazio, como o condomínio.

**D5 — O "Custo mensal estimado" é calculado na tela** (`totalMensalEstimado`): aluguel + condomínio + IPTU, só quando há preço de aluguel. Não vai no `PATCH`, e a tela diz que é soma da tela.

**D6 — "Ver no portal" só com o imóvel *salvo* disponível.** O portal (`/busca/[id]`) devolve 404 para outro status, e o status que vale é o gravado, não o do formulário.

**D7 — A galeria fica fora do `<form>`**: as fotos gravam na hora, com `PATCH` próprio (TEC-335), e não esperam "Salvar alterações". A área de soltar é o próprio `<input type="file">` esticado sobre a caixa tracejada — o navegador já aceita arquivo solto sobre ele, sem lógica de arraste nova. O texto de ajuda lê `FOTO_TETO_DE_BYTES`.

**D8 — A descrição mostra só a contagem de caracteres**, sem "/ 2.000": a coluna é `Text`, sem limite.

## Fora (não existe no sistema)

Mapa (não há provedor de mapa nem edição de latitude/longitude), "Duplicar" (não há rota), "Reordenar automaticamente por IA", "Valores conferidos pela inteligência de conciliação", "Etapa 01". A ajuda das fotos da referência ("JPG, WEBP de até 20 MB, resolução mínima 1920×1080") também não vale: o limite real é JPG/PNG/WEBP de até 5 MB, sem resolução mínima.

## Lacunas

- **L1** — A trilha da referência tem "Catálogo"; não existe essa página. A trilha é "Administração / Imóveis / Editar imóvel".
- **L2** — A galeria nunca teve CSS (desde a TEC-335); ganhou agora.

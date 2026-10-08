# TEC-398 — a tela de imóveis no visual do painel

Card: TEC-398. Épico: TEC-308. Mesmo molde da TEC-397 (corretores), de quem herda `.dialogo`, `.chips`, `.rotulo--obrigatorio`, `.estado-vazio-do-painel` e o padrão "cadastro sempre aberto, edição em modal". Referência: imagem de `/admin/imoveis` enviada por Eduardo em 08/10/2026.

## O que muda

A aparência de `/admin/imoveis` e dois comportamentos de abertura (D1, D2). Validação (TEC-333), aviso de reindexação, fotos (TEC-335), pré-visualização do card (TEC-336), importação (TEC-334) e a retirada com confirmação continuam como estão.

## Decisões

**D1 — O cadastro fica sempre aberto, no cartão "Cadastrar novo imóvel".** Some o botão "Cadastrar imóvel". Depois de cadastrar, o formulário volta vazio; "Cancelar" limpa o que foi digitado. Mesmo D1 da TEC-397.

**D2 — A edição abre num `<dialog>` modal, "Editar imóvel"**, com fotos, aviso de reindexação e "Pré-visualizar card" dentro dele. A pré-visualização já é um `<dialog>`: abre por cima do modal de edição.

**D3 — O cabeçalho do CSV mostrado é o que o importador exige**, e não o da referência: ela lista `valor` e `area`, que não existem, e omite `descricao`, `quartos`, `suites`, `banheiros` e `vagas`. A lista sai de `domain/catalogo/parser.py::_OBRIGATORIAS`, copiada em `COLUNAS_OBRIGATORIAS_DO_CSV` (`lib/importacaoDeImoveis.ts`) com o comentário apontando a origem — o frontend não tem como ler a do backend.

**D4 — Preços aparecem conforme a operação**, como hoje: a referência mostra só "Condomínio", mas Venda pede preço de venda e Aluguel pede preço de aluguel. Os campos de preço levam o prefixo "R$".

**D5 — "Cadastrar primeiro imóvel", no estado vazio, leva o foco ao campo "Código"** do cadastro, que já está aberto na mesma tela.

**D6 — O selo do cartão de importação diz "CSV, até 10 MB"**, e não "Formato CSV padrão UTF-8": o importador aceita BOM do Excel e `;` como separador, e o teto de 10 MB é o que recusa um arquivo na seleção.

## Lacunas

- **L1** — A trilha da referência é "Administração / Catálogo / Imóveis". Não existe página "Catálogo"; a trilha é "Administração / Imóveis".

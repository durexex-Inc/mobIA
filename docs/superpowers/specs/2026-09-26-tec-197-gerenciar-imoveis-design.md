# TEC-197 — Gerenciar imóveis pela interface administrativa

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-197](https://eduardodurieuxlopes.atlassian.net/browse/TEC-197) — épico TEC-189
**Branch:** `feat/tec-197-gerenciar-imoveis`
**Origem:** RF-19, RN-19.1, RN-08.3 (SRS v1.0); seção 6.3 · TEC-156, TEC-157 · telas TEC-333, TEC-334

## O problema

O catálogo só se mexe hoje por importação em lote (`POST /imoveis/importar`, TEC-156). Corrigir o preço de um imóvel exige montar um CSV de uma linha. A card pede o CRUD, a troca de status, a exclusão lógica e o relatório da última importação.

## O que já existe, e que esta card não reescreve

- **A reindexação é derivada do estado, e não avisada** (D2 da TEC-157). Toda escrita em `imoveis` carimba `updated_at` com `clock_timestamp()`; a varredura `indexar_catalogo`, a cada 30 s, pega os candidatos e **só chama o provedor quando o hash do documento mudou** (`catalogo/documento.py`). O documento é título, descrição, tipo, bairro, cidade e características — preço e status ficam fora. Os dois primeiros cenários do Gherkin saem disso sem código novo: mudar o preço não gera embedding, mudar a descrição gera.
- **A validação de um imóvel mora em `parser._converter`**, que acumula todos os motivos antes de recusar, lê o teto de cada texto da declaração da coluna e guarda a plausibilidade de preço (RN-08.5).
- **O upsert por código mora em `repositorio.sincronizar`**, com o diff campo a campo e o carimbo de `updated_at` do qual a varredura depende.
- **O relatório de uma importação** sai por `GET /imoveis/importacoes/{id}`, com as linhas rejeitadas e o motivo de cada uma.

## D1 — As rotas, todas com `GERIR_CATALOGO`

```
GET    /api/v1/imoveis                       ?status=&tipo=&busca=&limite=&cursor=
GET    /api/v1/imoveis/{id}
POST   /api/v1/imoveis                       → 201 | 409 (código duplicado)
PATCH  /api/v1/imoveis/{id}                  → 200 { …, "reindexa": true|false }
DELETE /api/v1/imoveis/{id}                  → 204 (status=INATIVO)
GET    /api/v1/imoveis/importacoes           ?limite=  (as mais recentes)
```

`GERIR_CATALOGO` é só do ADMIN, que é o que a card e a RN-19.5 pedem. **A listagem também fica com ela**, embora a seção 6.3 escreva `GET /imoveis` só com "Bearer JWT": a lista desta card é a da tela de administração, com imóveis inativos e todos os campos, e não a vitrine. Uma vitrine para outros papéis é outra rota, e ninguém a pediu.

## D2 — Um caminho de validação, e um de escrita

**A criação e a edição passam pelo mesmo `_converter` da importação**, e não por um modelo Pydantic paralelo. Um segundo validador divergiria na primeira regra nova — o teto de um texto, a plausibilidade de um preço — e o imóvel recusado no CSV passaria pela tela, ou o contrário. O corpo JSON (camelCase, preços em centavos, listas como listas) é convertido para o formato cru que o parser lê; o motivo da recusa volta em `422` com os mesmos textos do relatório de importação.

**A escrita passa por `sincronizar`.** É ele que carimba `updated_at` pelo relógio do banco, e é desse carimbo que a varredura depende; um `UPDATE` escrito na rota seria o segundo escritor de uma coluna com invariante.

**O `PATCH` é parcial sobre o registro inteiro**: lê o imóvel, sobrepõe os campos enviados e valida o resultado completo. Validar só o que veio deixaria passar, por exemplo, `operacao=ALUGUEL` sobre um imóvel sem `precoAluguel`. **O código não se edita**: é a chave do upsert da importação, e trocá-lo faria o próximo CSV criar um segundo imóvel.

## D3 — `reindexa` é informativo

A TEC-333 pede "aviso de reindexação" na tela. O `PATCH` responde `reindexa: true` quando o documento do imóvel (`documento_de`) mudou — calculado antes e depois, pela mesma função que a varredura usa. **Ele não dispara nada**: quem reindexa é a varredura, em até 30 s, e o campo só antecipa à tela o que ela vai fazer. Enfileirar um job aqui seria o "avisado por quem escreve" que a D2 da TEC-157 recusou.

## D4 — Excluir é `status=INATIVO`

A seção 6.3 já decide: *"DELETE é lógico (`status=INATIVO`), nunca físico"*. A busca e o follow-up só olham `DISPONIVEL`, então o imóvel sai deles sem mudança nenhuma lá; `recomendacoes.imovel_id` continua apontando para a linha, e o histórico fica íntegro.

**Consequência declarada:** excluir e mudar o status para `INATIVO` são a mesma operação, e **reimportar o código num CSV com status `DISPONIVEL` o reativa**. É o comportamento do upsert por código, e uma coluna `excluido_em` separada pediria decidir o que a importação faz com um código excluído — decisão de produto que a card não toma. Lacuna L1.

## D5 — A listagem

Ordem por `codigo`, paginada por keyset (`codigo > cursor`). É estável — o código não muda (D2) — e é o que o administrador procura. `busca` casa `codigo` e `titulo` sem caixa; `bairro` casa pela coluna dobrada, `bairro_busca`, como a busca do agente. Sem `total`, pelo argumento da lista de leads.

## D6 — A última importação

`GET /imoveis/importacoes?limite=5` devolve as mais recentes, com o mesmo formato do `GET` por id. É o que a tela precisa para abrir mostrando a última, sem guardar o id em lugar nenhum.

## Arquivos

```
src/mobia/domain/catalogo/cadastro.py     # converter, criar, editar, excluir, listar (D2-D5)
src/mobia/domain/catalogo/parser.py       # `_converter` ganha nome publico
src/mobia/api/routes/imoveis.py           # as seis rotas
```

Sem migration.

## Testes

- **Os quatro cenários do Gherkin, contra banco.** Preço de R$ 620.000 para R$ 590.000 vale na busca e a varredura, rodada com embedador falso, não o chama. Mudar a descrição faz a varredura chamá-lo. O imóvel excluído some da busca e a recomendação antiga continua lá. O CSV com 3 linhas inválidas aparece em `GET /importacoes` com as três e os motivos.
- **A validação é a da importação** — o mesmo motivo de recusa para o mesmo erro pelos dois caminhos.
- **`PATCH` valida o registro inteiro** — trocar a operação sem o preço correspondente é 422.
- **Código duplicado é 409; código não se edita.**
- **`reindexa`** é verdadeiro para descrição e falso para preço e status.
- **Paginação** sem repetir nem perder imóvel.
- **Só ADMIN**: GERENTE e CORRETOR levam 403.

## Emendas ao SRS

- **RN-19.1, Emenda E-01** — as rotas, a validação única, `reindexa`, e a reativação pela importação.
- **Seção 6.3, `GET /api/v1/imoveis`, Emenda E-01** — a lista é da administração, com `GERIR_CATALOGO`; filtros e ordem.

## Lacunas declaradas

- **L1 — excluir e inativar são a mesma coisa, e a importação reativa** (D4).
- **L2 — fotos são URLs**, como na importação. Upload de arquivo de foto é a TEC-335.
- **L3 — não há trilha de auditoria da edição de imóvel.** A RNF-18 não a pede; `updated_at` diz quando, e não quem.

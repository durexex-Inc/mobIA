# TEC-334 — Importar imóveis em lote por CSV e ver as linhas rejeitadas

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-334](https://eduardodurieuxlopes.atlassian.net/browse/TEC-334) — História, Should (MoSCoW), prioridade High. Origem: RN-FE-12.4 (SRS mobIA Frontend v1.0) · TEC-156, TEC-261.

**A história:** *"Como Rafael, administrador da imobiliária, quero subir o catálogo inteiro por planilha e saber quais linhas falharam, para atualizar o estoque sem digitar imóvel por imóvel."*

**Só frontend.** A importação assíncrona (TEC-156, com a geração de embedding da TEC-157) já está entregue: `POST /api/v1/imoveis/importar` (multipart, `202`, enfileira), `GET /api/v1/imoveis/importacoes/{id}` (o relatório) e `GET /api/v1/imoveis/importacoes?limite=` (as mais recentes — D6 do desenho da TEC-197). Todas guardadas por `GERIR_CATALOGO`. Esta card é a tela de `/admin/imoveis` que já existe (TEC-333) ganhando um fluxo de importação.

**Desbloqueada.** A única dependência declarada, TEC-333, está **Feito**.

## D1 — A pré-visualização é só do cliente, sem round-trip

*"Vê as 10 primeiras linhas antes de confirmar"* acontece **antes** do `POST` — o backend não tem endpoint de pré-visualização, e inventar um só para 10 linhas seria round-trip para o que o próprio navegador já tem em mãos (`File`, lido com `FileReader`).

**Decisão: um parser de CSV pequeno e só do cliente**, escrito para esta tela — não uma dependência nova. Ele espelha as duas escolhas do parser real (`domain/catalogo/parser.py::_parsear_csv`/`_delimitador`): delimitador `;` ou `,`, escolhido por qual aparece mais vezes no cabeçalho, e UTF-8 com BOM opcional. **Não** replica o `csv.DictReader` inteiro — campo entre aspas com quebra de linha dentro (registro que ocupa mais de uma linha física) não é tratado; a pré-visualização mostraria esse caso errado. É uma degradação aceitável e declarada: a pré-visualização é conveniência, não validação — quem valida de verdade é o backend, depois do envio, e é o relatório de rejeições (não a prévia) que é a fonte de verdade.

A prévia mostra as colunas do próprio arquivo, como vieram — sem remapear para os nomes do formulário da TEC-333: é uma prévia do arquivo, não do que vai ser gravado.

## D2 — O limite de 10 MB é checado na seleção, replicado do lado do cliente

O Gherkin é explícito: *"Quando Rafael seleciona o arquivo / Então a importação é recusada"* — antes de qualquer envio, não como erro de `POST`. `File.size` é comparado a `10 * 1024 * 1024`, o mesmo valor de `TETO_DE_UPLOAD_EM_BYTES` (`api/routes/imoveis.py`). **É uma duplicação deliberada de uma constante entre Python e TypeScript** — não há como uma rota HTTP compartilhar uma constante de módulo com o cliente sem inventar um endpoint só para isso. O teto do backend continua sendo a garantia real (`413`); o do cliente é só o "recusado com a indicação do limite" na hora certa que o Gherkin pede, e a mensagem do `413` (`f"arquivo acima de {TETO_DE_UPLOAD_EM_BYTES} bytes..."`) é a rede de segurança se os dois algum dia divergirem.

## D3 — O acompanhamento é polling do cliente na importação específica, não `router.refresh()`

O padrão de atualização automática que já existe (`AtualizacaoAutomatica.tsx`, TEC-317) resolve "manter uma listagem fresca" reexecutando o Server Component inteiro. Aqui o que precisa ficar fresco é **um relatório específico**, com o id que acabou de ser criado (pelo `POST`) ou que a página abriu mostrando (a mais recente, D6 da TEC-197) — um alvo estreito demais para justificar re-renderizar a página inteira a cada tique.

**Decisão: um componente de cliente que faz `GET /bff/api/v1/imoveis/importacoes/{id}` a cada 3 segundos enquanto `status === 'PROCESSANDO'`**, e para sozinho ao primeiro `CONCLUIDO`/`FALHOU`. Sem o cuidado de pausar com a aba oculta que a TEC-317 tem — aqui a importação está rodando no worker de qualquer jeito, então poupar uma chamada a cada 3s não poupa trabalho do backend, só atraso na tela de quem está olhando. Ficar simples é a escolha certa quando a otimização da TEC-317 não se aplica.

## D4 — A tela abre mostrando a importação mais recente, se houver uma

A carga inicial da página busca `GET /api/v1/imoveis/importacoes?limite=1` do servidor (mesmo padrão de `buscarImoveis`/`buscarCorretores` — D7 abaixo). Havendo uma, ela aparece já no primeiro render — e se estiver `PROCESSANDO`, o componente de polling (D3) assume dali. É o que cobre o cenário 4 do Gherkin sem exigir que o `POST` e a visualização aconteçam na mesma sessão de navegador.

## D5 — As linhas rejeitadas viram CSV com um Blob, sem round-trip

O relatório já chega com `erros: [{ linha: number, motivo: string }]` — os mesmos dados que a tela lista. *"Baixar essas linhas em CSV"* não precisa de rota nova: um Blob de `text/csv` montado a partir do array já carregado, baixado por um `<a download>` sintético. Cabeçalho `linha,motivo`, com `motivo` escapado entre aspas quando contiver vírgula ou aspas (RFC 4180 mínimo, à mão — a mesma razão de não trazer uma dependência de CSV para a D1).

## D6 — O upload passa pelo `/bff/*`, com dois caminhos novos na allowlist

Mesma arquitetura das duas cards anteriores (D8 da TEC-332, D7 da TEC-333): a carga inicial (a importação mais recente) é `chamarApi` direto do Server Component; o envio do arquivo e o polling, disparados depois de montado, passam pelo proxy.

| método | padrão |
|---|---|
| `POST` | `api/v1/imoveis/importar` |
| `GET` | `api/v1/imoveis/importacoes/*` |

`importar` é segmento literal, não `*` — só essa rota, e não qualquer coisa sob `imoveis/*` que o `PATCH`/`DELETE` da TEC-333 já abrem para o `{id}`. O `POST` do `FormData` (o `<input type="file">`) atravessa o proxy sem tratamento especial: `repassar` (`app/bff/[...rota]/route.ts`) já lê o corpo como `ArrayBuffer` e repassa o `Content-Type` (com o `boundary` do multipart) para qualquer método, sem examinar o conteúdo.

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Pré-visualizar antes de enviar | exercitado (D1) |
| Recusar arquivo acima do limite | exercitado na seleção (D2) |
| Ver as linhas rejeitadas, com download em CSV | exercitado (D5) |
| Acompanhar importação em andamento | exercitado por polling (D3), inclusive ao abrir a página (D4) |

## Fora de escopo

Editar ou re-enviar uma linha rejeitada pela própria tela — a correção continua sendo "ajuste o CSV e reimporte", como já era antes desta card. Histórico de importações além da mais recente (a rota `GET /importacoes?limite=` aceita mais de uma, mas o Gherkin só pede a atual — mostrar uma lista de importações passadas é extensão não pedida). Formato `.json` de importação (o parser aceita, a card fala só em CSV).

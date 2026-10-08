# TEC-394 — a lista de leads no visual do painel

Card: TEC-394. Épico: TEC-308. Continua a TEC-393 (`2026-10-08-tec-393-funil-no-visual-da-referencia-design.md`), de quem herda tokens de tema, `Cartao` e `Botao`.

## O que muda

Só a aparência de `/leads`: busca, filtros, tabela (e os cartões dela no celular), paginação, a faixa "Etapa do funil" e os estados vazio/erro/carregando. Busca com debounce, filtros que aplicam ao mudar, ordenação por link, cursor e "Revelar" continuam iguais. O detalhe do lead (`/leads/[leadId]`) fica de fora, exceto o botão "Revelar", que é a mesma peça nas duas telas.

## Decisões

**D1 — `CampoDeSelecao` em `components/ui/`.** O `Selecao` dos filtros do funil e o `Lista` dos filtros da lista repetiam a mesma marcação desde a TEC-393 (`<span class="campo-selecao"><select>`). Os dois passam a usar a peça, que é o "Select" do shadcn, só que nativo, pela CSP (D1 da TEC-393).

**D2 — `.campo` é a classe dos campos de texto, data e busca.** Antes o estilo morava em `.filtros input`, preso ao formulário do funil; a busca da lista precisava do mesmo.

**D3 — A tabela dentro de um `Cartao`, que some abaixo de 768 px.** Lá cada linha já vira cartão (D4 da TEC-322); manter o de fora daria cartão dentro de cartão. O `overflow-x` foi da tabela para o cartão, para a borda arredondada não cortar a rolagem.

**D4 — As linhas da tabela não ganham classe.** O teste da lista afirma `className` de cada `<tr>` igual a `leads-pagina-anterior` ou vazio (D3 da TEC-322): o visual de linha sai de seletores sobre `tbody tr`.

**D5 — "Carregar mais" usa as classes do `Botao`, não o componente.** É um `<Link>` do Next, não um botão: as classes `botao botao--contorno` dão a aparência sem trocar o elemento.

## Lacunas

- **L1** — A referência mostra a lista vazia. Tabela, paginação, faixa do funil, erro e carregando seguiram a linguagem do funil, sem desenho próprio.
- **L2** — O botão "Revelar" também muda de aparência no detalhe do lead.

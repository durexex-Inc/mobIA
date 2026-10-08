# TEC-393 — o funil de leads no visual da referência

Card: TEC-393. Épico: TEC-308. Referência: imagem enviada por Eduardo em 08/10/2026 (tela principal em tema escuro, estilo shadcn/ui).

## O que muda

Só a aparência da tela principal (`app/(painel)/page.tsx`) e do que ela compõe: menu do topo, filtros, indicador de atualização, funil e indicadores. Nenhum contrato de API, regra de negócio ou comportamento muda: filtros continuam sendo estado de URL, o polling continua o mesmo, as etapas continuam levando à lista de leads, e "Ainda não medido" × "sem dados no período" continuam distintos.

## Decisões

**D1 — O visual do shadcn sem instalá-lo.** Componentes próprios em `components/ui/` e tokens em CSS no `globals.css`; sem Tailwind e sem Radix. Duas razões: a CSP de produção só aceita estilo por nonce, e os componentes Radix com posicionamento escrevem `style` inline; e o reset do Tailwind (Preflight) mudaria botões, campos e títulos de todas as outras telas do painel, que dependem do estilo padrão do navegador.

**D2 — Tema do sistema, com botão para escolher.** Sem escolha, vale `prefers-color-scheme`. O botão no menu grava `mobia_tema=claro|escuro` num cookie, e o layout raiz o lê no servidor e o põe em `data-tema` no `<html>`. Cookie, e não `localStorage`: com o valor no servidor a página já chega no tema certo, sem piscar e sem script inline — que a CSP recusaria sem nonce. Não há volta para "sistema" pelo botão: apagar o cookie volta. O escuro é o da referência; o claro é o par dele.

**D3 — A barra de proporção do funil sai.** A referência não a tem. A largura vinha de `style={{ width }}`, atributo que a `style-src` de produção bloqueia quando chega no HTML; a barra provavelmente já não desenhava como pretendido em produção (não verificado). A quantidade segue escrita em cada linha.

**D4 — A cor de cada etapa é classe, nunca `style`.** Seis tokens (`--etapa-*`) e uma classe por etapa, escolhida pelo nome. Etapa desconhecida cai num marcador neutro, em vez de não renderizar.

**D5 — O link da etapa é a própria linha.** Antes era `display: contents` para não quebrar o grid do `<li>`, e elemento com `display: contents` não desenha anel de foco. Agora o `<a>` é o grid, e o foco por teclado aparece.

**D6 — Geist só no painel.** A fonte já era carregada e nenhuma tela a usava. Vai em `.menu` e `.painel`, e não no `body`: o chat embutido roda no site da imobiliária e não deve mudar de fonte por causa desta card.

**D7 — Os tokens novos substituem `--background`/`--foreground` na origem.** As outras telas do painel não são redesenhadas, mas usam esses dois tokens; passam a acompanhar o tema, inclusive o escolhido no botão. Ficam com aparência de "meio migradas" até as cards delas.

## Lacunas

- **L1** — A referência não mostra estados de erro, carregamento, coorte incompleta nem a nota dos indicadores sem fonte. Eles ganham o visual novo por coerência, sem desenho de referência.
- **L2** — As 16 páginas que usam `.painel` herdam contêiner e título novos.

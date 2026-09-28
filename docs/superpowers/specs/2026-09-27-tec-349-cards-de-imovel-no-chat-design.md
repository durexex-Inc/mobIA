# TEC-349 — Exibir até 3 cards de imóvel na conversa do chat web

**Status:** implementado nesta branch
**Card:** [TEC-349](https://eduardodurieuxlopes.atlassian.net/browse/TEC-349) — épico TEC-307
**Origem:** RN-FE-18.1 a 18.4 (SRS de frontend, que não está no repo — L3 da TEC-364). O contrato do frame é o da TEC-364.

## O que o repo tem, medido sobre `10d6e8c`

- **O servidor já manda o frame `imovel`** (TEC-364, D2). O card vem estruturado em `imovel` (`agente/apresentacao.py::card_de`). A prosa do agente vem em `texto`, só no primeiro frame do turno, e o `kind` é `ficha_1` a `ficha_3`.
- **`url` é sempre nulo** (L1 da TEC-364). O catálogo não guarda a página do imóvel.
- **O `historico` da reconexão traz a ficha como legenda** (L2 da TEC-364), não como card.
- **O redutor da TEC-346 só usava o `texto`** do frame `imovel`, e descartava o imóvel.

## D1 — A fileira de cards é uma mensagem

`Mensagem` ganha o caso `{ autor: 'imoveis'; chave; imoveis }`.

- `kind: 'ficha_1'` abre uma fileira nova. Os frames seguintes entram na última, se ela for a mensagem mais nova da lista e ainda tiver menos de 3 cards (`MAXIMO_DE_CARDS`).
- Sem o `kind`, dois turnos seguidos, o segundo sem prosa, juntariam os seus cards numa fileira só.
- A prosa vira balão do agente **antes** do card.

**O `historico` descarta a fileira.** Ela não casa com nenhuma fala do histórico, e os balões com a legenda entram no lugar dela. É a L2 da TEC-364 vista da tela.

## D2 — `imovelDe`: o card inteiro, ou nada

`lib/imovel.ts` valida o frame que vem da rede.

- Os campos obrigatórios são sete: `id`, `titulo`, `bairro`, `precoCentavos`, `quartos`, `vagas` e `areaUtilM2`.
- Se um deles faltar ou vier com o tipo errado, o card é descartado. A prosa continua valendo.
- Os opcionais são quatro: `condominioCentavos`, `diferencial`, `foto` e `url`.

**`foto` e `url` só aceitam `http:` e `https:`.** A foto vira `src` e a página vira `href`, e um `javascript:` num `href` rodaria na página do chat.

**O preço trunca os centavos**, como `reais_de` no servidor: `R$ 516.464`.

## D3 — `CardDeImovel`

- **Reutilizável.** O componente só recebe o imóvel, para a pré-visualização da TEC-336 desenhar o mesmo card.
- **O card inteiro é clicável, e o controle é um só: o do título.** Um `<button>` não pode conter título, lista e parágrafos, só conteúdo de frase. Por isso o botão, ou o link, fica no `<h3>`, e um `::after` estica a área de clique sobre o card. O leitor de tela encontra um controle com o nome do imóvel.
- **Com `url`:** um link com `target="_blank"` e `rel="noopener noreferrer"`, e o aviso "(abre o site em nova aba)" visível só para leitor de tela.
- **Sem `url`:** um botão com `aria-expanded`. **"Expandir a ficha no chat"** foi lido como tirar o corte de duas linhas do diferencial e dar ao card a largura toda da fileira. Os dados são os mesmos, porque o card fechado já mostra todos, como pede o cenário 1.
- **Foto.** `loading="lazy"`, `width` e `height` no elemento, e `aspect-ratio: 4 / 3` no CSS, que reservam a caixa antes de a imagem chegar. O texto alternativo é "Foto de {título} em {bairro}".
- **`<img>` e não `next/image`.** A foto vem de host qualquer do catálogo de cada imobiliária, e `next/image` exige declarar os hosts remotos.
- **Sem foto:** um placeholder neutro com o bairro, com `aria-hidden`, porque o bairro já está no texto do card.
- **Condomínio e diferencial nulos** omitem a linha, como a legenda do servidor faz.

## D4 — A fileira na tela

- Uma `<ul aria-label="Imóveis sugeridos">` dentro do `<li>` da conversa. O leitor de tela anuncia "lista, 3 itens".
- Rolagem horizontal com encaixe (`scroll-snap`), com cards de 220 px. O painel do chat é estreito, e três cards empilhados empurrariam a conversa.

## Testes

- **`lib/imovel.test.ts`:**
  - o formato completo;
  - os opcionais ausentes;
  - cada obrigatório ausente;
  - os tipos errados;
  - `urlSegura`;
  - o truncamento do preço;
  - o texto alternativo.
- **`lib/conversa.test.ts`:**
  - a fileira de três frames, com a prosa antes;
  - `ficha_1` abrindo fileira nova;
  - o teto de 3;
  - as chaves;
  - um balão no meio da fileira;
  - o `historico` trocando a fileira pelos balões.
- **`components/CardDeImovel.test.tsx`:** os quatro cenários da card, a foto com `lazy` e dimensões, o expandir, e os campos opcionais ausentes.
- **`components/Conversa.test.tsx`:** três frames pelo socket viram a prosa e uma fileira de três cards.

## O que esta card não entrega

- **O cenário 3 só é exercitado no componente.** Ninguém abre a página do imóvel em nova aba na prática, porque o servidor nunca manda `url` (L1 da TEC-364).
- **Ao recarregar a página, os cards voltam como texto** (L2 da TEC-364).
- **O frame `imagem` continua ignorado.** A TEC-346 o atribuía a esta card, mas nenhum cenário da TEC-349 fala dele, e o servidor não o emite para ficha.
- **Não houve verificação visual no navegador.** O CSS foi verificado pelo build; os testes com jsdom não calculam layout.

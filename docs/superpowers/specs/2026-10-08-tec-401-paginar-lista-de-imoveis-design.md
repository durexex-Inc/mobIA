# TEC-401 — paginar a lista de imóveis da administração

Card: TEC-401. Épico: TEC-308. Fecha a lacuna da D6 da TEC-333 ("sem paginação na primeira versão"). Empilhada sobre a TEC-400, que mexe na mesma lista.

## O que muda

`/admin/imoveis` deixa de parar nos 50 primeiros. "Carregar mais" soma a página seguinte, e a URL guarda quantas páginas estão abertas. A API não muda: `GET /api/v1/imoveis` já pagina por keyset em `codigo`, sem total.

## Decisões

**D1 — A URL guarda quantas páginas, não os cursores (`?paginas=3`).** É a diferença deliberada em relação à trilha de auditoria (TEC-343), que guarda os cursores vistos e refaz cada página em paralelo. Lá isso é seguro porque a trilha é imutável e cresce só no topo. O catálogo não: imóvel entra e sai em qualquer ponto da ordem por código. Refazer páginas a partir de cursores guardados, depois de um cadastro, **pula** o imóvel que escorrega para a fronteira de duas páginas; depois de uma retirada, **repete** um. O critério de aceite "sem repetir nem pular" cairia justamente no caso do último critério (cadastrar e a lista se atualizar).

**D2 — O servidor percorre as páginas em sequência**, cada uma pelo `proximoCursor` da anterior (`buscarImoveis(acesso, paginas)`). É uma consulta encadeada por página aberta, em vez de uma em paralelo — o preço da consistência da D1. Com o tamanho padrão de 50 e o catálogo do seed (520), são no máximo 11 chamadas, no próprio servidor do Next.

**D3 — `paginas` vai de 1 a 20 (`MAXIMO_DE_PAGINAS`).** Valor ausente, não numérico ou menor que 1 vira 1; maior que 20 vira 20. O teto existe para um endereço editado à mão não disparar centenas de consultas; 20 × 50 = 1000 imóveis, quase o dobro do catálogo de hoje.

**D4 — A tela diz quanto está carregado**, não um total: "N imóveis carregados", com "Carregar mais" enquanto a API devolver `proximoCursor`. O link usa `scroll={false}`, para quem clicou continuar onde estava.

## Fora

Total e paginação numerada (a API não devolve total), filtros (a API filtra por `status`, `tipo`, `bairro` e `busca`, mas a card os deixou de fora de propósito).

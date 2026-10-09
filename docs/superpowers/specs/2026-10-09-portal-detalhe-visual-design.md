# Detalhe do imóvel no portal: visual de vitrine

**Card:** ainda não existe — pedido direto do Eduardo em 09/10/2026, com uma imagem de referência (tela mobile "Detalhes do imóvel"). Quando a card for criada, este desenho passa a citá-la.

## Problema

`/busca/[id]` (TEC-388) é o destino do botão "Ver no portal" da administração (TEC-400), e hoje é HTML cru: nenhuma regra de `globals.css` alcança as classes `busca-publica*`. A referência pede uma página de vitrine — galeria com miniaturas, preços em destaque, grade de características, comodidades, formulário de interesse em cartão e mapa.

## Escopo (decidido pelo Eduardo)

Visual completo com os dados que já existem, **mais** dois campos que o banco tem e o portal escondia: `codigo` e a localização (`latitude`/`longitude`).

**Fora**, porque não há dado em lugar nenhum: selo de exclusividade, tour 360°, "Pronto para morar", cartão do corretor (nome, CRECI, avaliação, WhatsApp, ligação), pontos do entorno com tempo de deslocamento, aviso de financiamento/FGTS, checkbox "agendar visita", favoritar e compartilhar. Cada um exige modelagem própria; na referência, a barra fixa tem três botões, aqui fica só o "Tenho interesse".

## Decisões

- **D1 — `codigo` passa a ser público.** Reverte a parte da D2 da TEC-388 que o tratava como "referência interna": a referência o mostra ("Cód. IT-9821"), e é o que o lead cita ao falar com o corretor.
- **D2 — A localização sai arredondada a 3 casas decimais (~110 m).** O portal é público e sem login; um pino no prédio exato entrega o endereço de quem anuncia a qualquer visitante. Três casas mostram a quadra, que é o que a seção "Localização" precisa. Sem coordenada, a seção não aparece.
- **D3 — Mapa por `<iframe>` do OpenStreetMap**, sem chave e sem biblioteca. A CSP ganha `frame-src https://www.openstreetmap.org` **só nas rotas do portal** (`rotaDoPortal`); o painel e o embed continuam sem `frame-src`, herdando `default-src 'self'`.
- **D4 — Nenhum `style=` inline.** Em produção `style-src` é só nonce, e atributo `style` não carrega nonce: todo o visual vive em classes `portal-*` no `globals.css`, com tokens próprios e variante escura no mesmo molde do tema (TEC-393).
- **D5 — Galeria é o único Client Component novo.** Foto grande, miniaturas e contador "1 / N fotos"; o resto da página continua Server Component.

# TEC-350 — Plano: reagir a um imóvel com "Gostei" ou "Não é pra mim"

Desenho: `docs/superpowers/specs/2026-09-28-tec-350-reagir-ao-imovel-design.md`. Só frontend: a reação é registrada pelo servidor a partir do texto (TEC-163).

## Passos

- [x] **`lib/imovel.ts`**: o tipo `Reacao` e `textoDaReacao`, com título e bairro (D1). Teste dos dois textos.
- [x] **`CardDeImovel`**: `aoReagir`, `reacao` e `bloqueado` opcionais; o rodapé com os dois botões, `aria-pressed` e desabilitados depois do toque (D2, D3). Testes: sem `aoReagir` não há botão; cada botão chama com a sua reação e não expande a ficha; a escolhida desabilita e marca; `bloqueado` desabilita sem marcar.
- [x] **`Conversa`**: `enviarTexto` como caminho único do campo e do toque; o estado das reações por `id`, limpo no encerramento; os botões bloqueados na espera de `muitas_tentativas`. Testes: os dois cenários do Gherkin, um toque por card, a fila da reconexão, a espera.
- [x] **CSS** do rodapé, acima do `::after` do título.
- [x] **Gates do frontend**: `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: Edge headless por CDP, cards publicados no Redis, cliques por coordenada.
- [x] **Prosa**: o parágrafo do README do frontend.

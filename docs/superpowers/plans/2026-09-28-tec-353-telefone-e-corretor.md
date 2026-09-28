# TEC-353 — Plano: telefone com máscara e pedido de corretor pelo chat

Desenho: `docs/superpowers/specs/2026-09-28-tec-353-telefone-e-corretor-design.md`.

## Passos

- [x] **`lib/telefone.ts`**: `digitosDe`, `mascarar`, `telefoneParaEnvio`, com a lista de DDDs copiada do servidor. Testes da máscara, dos válidos e dos inválidos.
- [x] **Contrato no backend** (`tests/unit/test_contrato_do_chat_web.py`): `pediu_humano` da frase do menu e `extrair_telefone` das duas formas do campo.
- [x] **Menu**: três itens a partir de uma lista, foco no primeiro, setas com volta nas pontas.
- [x] **`Conversa`**: "Falar com um corretor" manda a frase; "Informar meu telefone" troca o campo de texto pelo campo com máscara, que recusa o inválido com o formato esperado e manda o válido como mensagem; "Cancelar" volta; o encerramento fecha o campo.
- [x] **Testes do componente**: os quatro cenários, as setas, o "Cancelar".
- [x] **CSS** do campo de telefone.
- [x] **Gates**: os três do Python, `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**, com o worker: o vínculo, a resposta do pedido de humano e a do opt-out.
- [x] **Prosa**: o parágrafo do README do frontend.

# TEC-380 — plano de implementação

Desenho: `docs/superpowers/specs/2026-09-27-tec-380-redigir-dado-sensivel-design.md`.

## Task 1 — A regra
- `domain/privacidade/redacao.py`: `redigir`, `redigir_payload`, `Redacao`, os dois marcadores.
- `tests/unit/test_redacao.py`.

## Task 2 — Os dois pontos de gravação
- `IngestionService._persist`: `text_body` e `raw_payload` redigidos, com o log.
- `transcrever_audio`: redigir antes de `gravar_transcricao`.
- Integração: ingestão pelo WhatsApp e pelo widget, e a transcrição.

## Task 3 — Features, SRS, gates
- `tests/features/test_redacao_de_dado_sensivel.py`, os dois cenários.
- Emenda RNF-20 E-01.
- Gates, suíte, `comentarios_tocados.py --checar`.

# TEC-381 — plano de implementação

Desenho: `docs/superpowers/specs/2026-09-27-tec-381-pseudonimizar-antes-do-llm-design.md`.

## Task 1 — A regra
- `identidade/telefone.py::trechos_de_telefone`.
- `domain/privacidade/pseudonimo.py`: `pseudonimizar`, `sem_marcadores`.
- `tests/unit/test_pseudonimo.py`.

## Task 2 — Os pontos de saída
- `context/montagem.py::_texto_da`, só para a fala do LEAD.
- `messages/bloqueio.py::moderar_entrada_e_marcar`.
- `agente/classificador.py`: `sem_marcadores` na resposta, no investidor e na desambiguação.

## Task 3 — Features, SRS, gates
- `tests/features/test_pseudonimizacao.py`, os dois cenários.
- Emenda E-01 à RNF-23.
- Gates, suíte, `comentarios_tocados.py --checar`.

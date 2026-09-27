# TEC-131 — plano de implementação

Desenho: `docs/superpowers/specs/2026-09-27-tec-131-transcrever-audio-design.md`.

## Task 1 — Domínio do áudio (puro)
- `domain/midia/audio.py`: `duracao_do_ogg_opus(dados) -> float | None`, `dentro_do_limite(duracao, limite) -> bool`, `extensao_para_transcricao(mime) -> str | None`, `PRAZO_DA_TRANSCRICAO`.
- `politica.py`: tipos de áudio na allowlist.
- Unitários: `tests/unit/test_audio.py`.

## Task 2 — Schema
- `StatusDaTranscricao`, `MotivoDaTranscricao` e as quatro colunas em `MidiaRecebida`.
- Migration `0067_transcricao_de_audio`.
- `linha_pendente` aceita AUDIO.

## Task 3 — Porta e adaptador da transcrição
- `domain/midia/transcricao.py`: `TranscritorPort`, `Transcricao(texto, duracao)`, `TranscricaoIndisponivel`.
- `infra/transcricao.py`: `TranscritorWhisper` sobre o `AsyncOpenAI`, 30s e zero retentativas.
- Config: `transcricao_modelo`, `transcricao_duracao_maxima_segundos`.

## Task 4 — Job `transcrever_audio`
- Extrair de `baixar_midia` o download compartilhado.
- `workers/jobs/transcrever_audio.py`, registro em `workers/main.py`, `ctx["transcritor"]`.
- `infra/queue.py`: `enqueue_transcrever_audio`, `enqueue_turno_apos_transcricao`.
- Ingestão: AUDIO enfileira `transcrever_audio` no lugar de `baixar_midia`.
- Integração: `tests/integration/test_transcrever_audio.py`.

## Task 5 — Espera no `process_message`
- `domain/midia/espera.py::ha_audio_sem_transcricao`, chamada antes do claim.
- Integração da espera.

## Task 6 — Turno e montagem
- Aviso fixo de áudio em `domain/midia/confirmacao.py` e ramo em `turno.py`.
- Marcador `(audio transcrito)` em `montagem.py`.

## Task 7 — Features, SRS, docs
- `tests/features/test_transcricao_de_audio.py`, os quatro cenários.
- Emenda RN-01.3 E-01, `.env.example`.
- Gates, suíte por blocos, `comentarios_tocados.py --checar`.

# mobIA

Agente de IA para qualificação de leads imobiliários.

## Ambiente local

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
cp .env.example .env
docker compose up -d
```

## Comandos

| O quê | Comando |
|---|---|
| Testes | `python -m pytest` |
| Teste de latência | `python -m pytest -m perf` |
| Lint | `python -m ruff check src tests` |
| Formatação | `python -m ruff format src tests` |
| Migrations | `python -m alembic upgrade head` |
| API | `python -m uvicorn mobia.app.main:app --reload` |
| Worker | `python -m arq mobia.workers.main.WorkerSettings` |

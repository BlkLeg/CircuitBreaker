# Backend

FastAPI backend for Circuit Breaker.

## Dev Quickstart

```bash
cd apps/backend
python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
PYTHONPATH=src uvicorn app.main:app --reload
```

The server starts at **http://localhost:8000**. The package is built from `src/`, so `PYTHONPATH=src`
is required unless the package is installed non-editable. A running PostgreSQL is required — there is
no SQLite fallback.

From the repo root, `make dev` is the supported entry point: it brings up Postgres/Redis/NATS, the
backend, the monitor workers, and the frontend with the environment already wired up.

## API Docs

- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc
- OpenAPI schema: http://localhost:8000/api/openapi.json

## Environment Variables

| Variable        | Default                          | Description                   |
|-----------------|----------------------------------|-------------------------------|
| `CB_DB_URL`     | _(required)_                     | PostgreSQL URL; must start with `postgresql://` (falls back to `DATABASE_URL`) |
| `DEBUG`         | `false`                          | Enable debug mode             |
| `CORS_ORIGINS`  | `["http://localhost:3000", ...]` | Allowed CORS origins (JSON)   |
| `API_PREFIX`    | `/api/v1`                        | API route prefix              |

Copy `.env.example` to `.env` to override defaults:

```bash
cp .env.example .env
```

## Running Tests

```bash
PYTHONPATH=src pytest ../../tests/integration
```

Or `make test` from the repo root. Tests spin up a disposable PostgreSQL/TimescaleDB container via
testcontainers (see `tests/conftest.py`), so Docker must be running.

# Backend

FastAPI backend for service-layout-mapper.

## Dev Quickstart

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

The server starts at **http://localhost:8000**. SQLite DB is created at `data/app.db` on first run.

## API Docs

- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

## Environment Variables

| Variable        | Default                          | Description                   |
|-----------------|----------------------------------|-------------------------------|
| `DATABASE_URL`  | `sqlite:///./data/app.db`        | SQLAlchemy database URL       |
| `DEBUG`         | `false`                          | Enable debug mode             |
| `CORS_ORIGINS`  | `["http://localhost:3000", ...]` | Allowed CORS origins (JSON)   |
| `API_PREFIX`    | `/api/v1`                        | API route prefix              |

Copy `.env.example` to `.env` to override defaults:

```bash
cp .env.example .env
```

## Running Tests

```bash
pytest
```

Tests use an in-memory SQLite database and do not touch `data/app.db`.

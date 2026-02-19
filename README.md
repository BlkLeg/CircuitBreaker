# Circuit Breaker

The **Circuit Breaker** (formerly Service Layout Mapper) is a tool to document and visualize your homelab or small business network topology. It provides:

## Quick Start

### Single Image (Recommended)

```bash
# Build
docker build -t circuit-breaker .

# Run
docker run --rm -p 8080:8080 -v $(pwd)/data:/data circuit-breaker
```

The app will be at http://localhost:8080.

### Docker Compose (Dev)

```bash
docker compose -f docker/docker-compose.yml up
```

Then open:

- **App**: http://localhost:3000
- **API docs (Swagger)**: http://localhost:8000/api/v1/docs

## Tech Stack

| Layer    | Technology                           |
| -------- | ------------------------------------ |
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2.x |
| Database | SQLite (v1), PostgreSQL-ready (v2)   |
| Frontend | React 18, React Router v6, ReactFlow |
| Deploy   | Docker Compose                       |

## Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm start
```

## Docs

- [Architecture Overview](docs/OVERVIEW.md)
- [API & Entity Schema](docs/API-ENTITY-SCHEMA.md)
- [Roadmap](docs/ROADMAP.md)

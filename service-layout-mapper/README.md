# service-layout-mapper

A homelab topology documentation tool. Map your hardware nodes, VMs and containers, running services, storage volumes, and networks into a browseable inventory and an interactive graph view.

## Quick Start

```bash
docker compose -f docker/docker-compose.yml up
```

Then open:
- **App**: http://localhost:3000
- **API docs (Swagger)**: http://localhost:8000/api/v1/docs

## Tech Stack

| Layer    | Technology                                |
|----------|-------------------------------------------|
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2.x      |
| Database | SQLite (v1), PostgreSQL-ready (v2)        |
| Frontend | React 18, React Router v6, ReactFlow      |
| Deploy   | Docker Compose                            |

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

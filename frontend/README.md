# Frontend

React SPA for service-layout-mapper.

## Dev Quickstart

```bash
cd frontend
npm install
npm start
```

Opens **http://localhost:3000**. API calls proxy to `http://localhost:8000` (set in `package.json`).

## Routes

| Path            | Page             |
|-----------------|------------------|
| `/hardware`     | Hardware table   |
| `/compute-units`| Compute Units    |
| `/services`     | Services         |
| `/storage`      | Storage          |
| `/networks`     | Networks         |
| `/misc`         | Misc Items       |
| `/docs`         | Docs viewer      |
| `/map`          | Topology graph   |

## Production Build

```bash
npm run build
```

Output goes to `build/`. Serve it with the nginx config in `docker/nginx.conf`.

## Notes

- The `"proxy"` field in `package.json` forwards all `/api/v1` requests to the backend during development — no CORS configuration needed in dev.
- The Map page uses [ReactFlow](https://reactflow.dev/). Node positions are computed with a simple grid layout; drag nodes to rearrange them (ReactFlow supports drag by default).

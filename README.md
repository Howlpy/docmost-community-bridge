# Docmost Community Bridge

AGPL-3.0 bridge that exposes a small REST API and an MCP Streamable HTTP
endpoint over the routes already present in Docmost Community.

It does not include or depend on Docmost Enterprise API/MCP code.

## Endpoints

- `POST /mcp` — MCP Streamable HTTP
- `GET /bridge/v1/spaces`
- `GET|POST /bridge/v1/pages`
- `GET|PATCH /bridge/v1/pages/{page_id}`
- `GET /bridge/v1/search?q=...`
- `GET /health` — public container health check

All endpoints except `/health` require `Authorization: Bearer <token>`.

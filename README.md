# Docmost Community Bridge

An independent, AGPL-3.0 bridge that adds a small REST API and an MCP
Streamable HTTP server to a self-hosted Docmost Community installation.

The bridge uses the authenticated routes already available in the AGPL
Docmost Community server. It does not contain, copy, or depend on Docmost
Enterprise API or MCP code.

## Features

- List and create accessible spaces, and list pages.
- Read page content as Markdown, HTML, or JSON.
- Search accessible pages.
- Create pages from Markdown.
- Rename pages or append, prepend, and replace Markdown content.
- Use the same operations through REST or MCP.
- Protect every data endpoint with a static Bearer token.
- Run as a non-root user in Docker.

The bridge intentionally does not expose permanent deletion operations.

## Requirements

- A reachable Docmost Community instance.
- A dedicated Docmost user account, preferably restricted to the spaces the
  automation is allowed to access.
- Docker, or Python 3.12 if running without Docker.

## Configuration

| Variable | Description |
| --- | --- |
| `DOCMOST_URL` | Internal Docmost URL, such as `http://docmost:3000`. |
| `DOCMOST_EMAIL` | Email of the Docmost automation account. |
| `DOCMOST_PASSWORD` | Password of the Docmost automation account. |
| `BRIDGE_TOKEN` | Long random Bearer token required by REST and MCP clients. |
| `BRIDGE_PUBLIC_URL` | Public HTTPS URL used to allow the reverse-proxy host, such as `https://docs.example.com`. |

Never commit these values. Store them in a local `.env` file or a secrets
manager.

## Docker Compose example

```yaml
services:
  docmost-bridge:
    build: .
    restart: unless-stopped
    environment:
      DOCMOST_URL: http://docmost:3000
      DOCMOST_EMAIL: ${DOCMOST_EMAIL}
      DOCMOST_PASSWORD: ${DOCMOST_PASSWORD}
      BRIDGE_TOKEN: ${BRIDGE_TOKEN}
      BRIDGE_PUBLIC_URL: https://docs.example.com
    ports:
      - "127.0.0.1:8000:8000"
```

Place the bridge on a Docker network shared with Docmost. Keep the published
port bound to localhost and expose it through a TLS reverse proxy.

## Endpoints

- `POST /mcp` - MCP Streamable HTTP endpoint.
- `GET /bridge/v1/spaces` - list accessible spaces.
- `POST /bridge/v1/spaces` - create a space from `name` and optional `description` or `slug`.
- `GET|POST /bridge/v1/pages` - list or create pages.
- `GET|PATCH /bridge/v1/pages/{page_id}` - read or update a page.
- `POST /bridge/v1/pages/{page_id}/move` - move a page to another space.
- `GET /bridge/v1/search?q=...` - search pages.
- `GET /health` - public container health check.

All endpoints except `/health` require this header:

```http
Authorization: Bearer YOUR_BRIDGE_TOKEN
```

## REST examples

```bash
curl -H "Authorization: Bearer $BRIDGE_TOKEN" \
  https://docs.example.com/bridge/v1/spaces

curl -X POST \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"space_id":"SPACE_UUID","title":"Meeting notes","content":"# Notes"}' \
  https://docs.example.com/bridge/v1/pages
```

## MCP client configuration

Configure an MCP client with:

- Transport: Streamable HTTP
- URL: `https://docs.example.com/mcp`
- Header: `Authorization: Bearer YOUR_BRIDGE_TOKEN`

Available MCP tools:

- `docmost_health`
- `list_spaces`
- `create_space`
- `list_pages`
- `get_page`
- `search_pages`
- `create_page`
- `update_page`
- `move_page_to_space`

## Security notes

- The bridge acts with the permissions of `DOCMOST_EMAIL`.
- Use a dedicated Docmost account instead of a workspace owner in production.
- Use a long random Bearer token and rotate it if it is disclosed.
- Do not expose port `8000` directly to the Internet.
- Terminate HTTPS at a trusted reverse proxy.

## License

This project is licensed under the GNU Affero General Public License v3.0.
See [LICENSE](LICENSE).

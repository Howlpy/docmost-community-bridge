import asyncio
import hmac
import os
import re
import unicodedata
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse


DOCMOST_URL = os.environ.get("DOCMOST_URL", "http://docmost:3000").rstrip("/")
DOCMOST_EMAIL = os.environ["DOCMOST_EMAIL"]
DOCMOST_PASSWORD = os.environ["DOCMOST_PASSWORD"]
BRIDGE_TOKEN = os.environ["BRIDGE_TOKEN"]
BRIDGE_PUBLIC_URL = os.environ.get("BRIDGE_PUBLIC_URL", "").rstrip("/")


def space_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", normalized).strip("-_").lower()
    slug = re.sub(r"[-_]{2,}", "-", slug)[:100].rstrip("-_")
    return slug if len(slug) >= 2 else "space"


def transport_security() -> TransportSecuritySettings:
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "docmost-bridge:*", "bridge:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*"]
    if BRIDGE_PUBLIC_URL:
        parsed = urlparse(BRIDGE_PUBLIC_URL)
        if not parsed.hostname or parsed.scheme not in {"http", "https"}:
            raise ValueError("BRIDGE_PUBLIC_URL must be an absolute HTTP(S) URL")
        allowed_hosts.extend([parsed.hostname, parsed.netloc])
        allowed_origins.append(BRIDGE_PUBLIC_URL)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
        allowed_origins=list(dict.fromkeys(allowed_origins)),
    )


class DocmostClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)
        self._auth_token: str | None = None
        self._login_lock = asyncio.Lock()

    async def login(self, force: bool = False) -> None:
        async with self._login_lock:
            if self._auth_token and not force:
                return
            response = await self._client.post(
                f"{DOCMOST_URL}/api/auth/login",
                json={"email": DOCMOST_EMAIL, "password": DOCMOST_PASSWORD},
            )
            response.raise_for_status()
            token = response.cookies.get("authToken")
            if not token:
                raise RuntimeError("Docmost login did not return authToken")
            self._auth_token = token

    async def post(self, path: str, payload: dict[str, Any]) -> Any:
        await self.login()
        response = await self._request(path, payload)
        if response.status_code == 401:
            await self.login(force=True)
            response = await self._request(path, payload)
        if response.is_error:
            raise RuntimeError(
                f"Docmost {path} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        if isinstance(body, dict) and body.get("success") is False:
            raise RuntimeError(str(body))
        return body.get("data", body) if isinstance(body, dict) else body

    async def _request(
        self, path: str, payload: dict[str, Any]
    ) -> httpx.Response:
        return await self._client.post(
            f"{DOCMOST_URL}/api/{path.lstrip('/')}",
            json=payload,
            headers={"Cookie": f"authToken={self._auth_token}"},
        )

    async def health(self) -> dict[str, Any]:
        response = await self._client.get(f"{DOCMOST_URL}/api/health")
        response.raise_for_status()
        return response.json()

    async def list_spaces(self, limit: int = 100) -> Any:
        return await self.post("spaces/", {"limit": min(max(limit, 1), 100)})

    async def create_space(
        self, name: str, description: str | None = None, slug: str | None = None
    ) -> Any:
        if not isinstance(name, str):
            raise ValueError("Space name is required")
        if description is not None and not isinstance(description, str):
            raise ValueError("Space description must be a string")
        if slug is not None and not isinstance(slug, str):
            raise ValueError("Space slug must be a string")
        clean_name = name.strip()
        if not 2 <= len(clean_name) <= 100 or any(
            character in clean_name for character in "\0\r\n"
        ):
            raise ValueError("Space name must contain 2 to 100 characters on one line")
        clean_slug = (slug or space_slug(clean_name)).strip().lower()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,99}", clean_slug):
            raise ValueError("Space slug is invalid")
        payload: dict[str, Any] = {"name": clean_name, "slug": clean_slug}
        if description:
            payload["description"] = description.strip()
        return await self.post("spaces/create", payload)

    async def list_pages(
        self, space_id: str, parent_page_id: str | None = None, limit: int = 100
    ) -> Any:
        payload: dict[str, Any] = {"spaceId": space_id, "limit": min(max(limit, 1), 100)}
        if parent_page_id:
            payload = {"pageId": parent_page_id, "limit": min(max(limit, 1), 100)}
        return await self.post("pages/sidebar-pages", payload)

    async def get_page(
        self, page_id: str, output_format: Literal["markdown", "html", "json"] = "markdown"
    ) -> Any:
        return await self.post(
            "pages/info",
            {"pageId": page_id, "includeContent": True, "format": output_format},
        )

    async def search_pages(
        self, query: str, space_id: str | None = None, limit: int = 25
    ) -> Any:
        payload: dict[str, Any] = {
            "query": query,
            "limit": min(max(limit, 1), 100),
            "offset": 0,
        }
        if space_id:
            payload["spaceId"] = space_id
        return await self.post("search/", payload)

    async def create_page(
        self,
        space_id: str,
        title: str,
        content: str = "",
        parent_page_id: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "spaceId": space_id,
            "title": title,
            "content": content,
            "format": "markdown",
        }
        if parent_page_id:
            payload["parentPageId"] = parent_page_id
        return await self.post("pages/create", payload)

    async def update_page(
        self,
        page_id: str,
        title: str | None = None,
        content: str | None = None,
        operation: Literal["append", "prepend", "replace"] = "append",
    ) -> Any:
        payload: dict[str, Any] = {"pageId": page_id}
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload.update(
                {"content": content, "format": "markdown", "operation": operation}
            )
        if len(payload) == 1:
            raise ValueError("Provide title and/or content")
        return await self.post("pages/update", payload)

    async def move_page_to_space(self, page_id: str, space_id: str) -> Any:
        if not page_id or not space_id:
            raise ValueError("page_id and space_id are required")
        await self.post("pages/move-to-space", {"pageId": page_id, "spaceId": space_id})
        return {"pageId": page_id, "spaceId": space_id}


docmost = DocmostClient()
mcp = FastMCP(
    "Docmost Community Bridge",
    instructions=(
        "List and create spaces, and read, search, create and update pages in "
        "the self-hosted Docmost Community workspace. Use list_spaces before "
        "page operations."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    transport_security=transport_security(),
)


@mcp.tool()
async def docmost_health() -> dict[str, Any]:
    """Check the self-hosted Docmost database and Redis health."""
    return await docmost.health()


@mcp.tool()
async def list_spaces(limit: int = 100) -> Any:
    """List spaces available to the automation account."""
    return await docmost.list_spaces(limit)


@mcp.tool()
async def create_space(
    name: str, description: str | None = None, slug: str | None = None
) -> Any:
    """Create a Docmost space. Requires workspace permission to manage spaces."""
    return await docmost.create_space(name, description, slug)


@mcp.tool()
async def list_pages(
    space_id: str, parent_page_id: str | None = None, limit: int = 100
) -> Any:
    """List root pages in a space, or children below a parent page."""
    return await docmost.list_pages(space_id, parent_page_id, limit)


@mcp.tool()
async def get_page(
    page_id: str,
    output_format: Literal["markdown", "html", "json"] = "markdown",
) -> Any:
    """Get a page including its content."""
    return await docmost.get_page(page_id, output_format)


@mcp.tool()
async def search_pages(
    query: str, space_id: str | None = None, limit: int = 25
) -> Any:
    """Full-text search across accessible Docmost pages."""
    return await docmost.search_pages(query, space_id, limit)


@mcp.tool()
async def create_page(
    space_id: str,
    title: str,
    content: str = "",
    parent_page_id: str | None = None,
) -> Any:
    """Create a Docmost page from Markdown."""
    return await docmost.create_page(space_id, title, content, parent_page_id)


@mcp.tool()
async def update_page(
    page_id: str,
    title: str | None = None,
    content: str | None = None,
    operation: Literal["append", "prepend", "replace"] = "append",
) -> Any:
    """Rename a page or append, prepend, or replace its Markdown content."""
    return await docmost.update_page(page_id, title, content, operation)


@mcp.tool()
async def move_page_to_space(page_id: str, space_id: str) -> Any:
    """Move a page and its accessible descendants to another Docmost space."""
    return await docmost.move_page_to_space(page_id, space_id)


def ok(data: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


async def safe(call: Any) -> JSONResponse:
    try:
        return ok(await call)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@mcp.custom_route("/health", methods=["GET"])
async def health_route(_: Request) -> JSONResponse:
    return await safe(docmost.health())


@mcp.custom_route("/bridge/v1/spaces", methods=["GET", "POST"])
async def spaces_route(request: Request) -> JSONResponse:
    if request.method == "GET":
        return await safe(docmost.list_spaces(int(request.query_params.get("limit", "100"))))
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("name"), str):
        return JSONResponse({"ok": False, "error": "name is required"}, status_code=422)
    return await safe(
        docmost.create_space(body["name"], body.get("description"), body.get("slug"))
    )


@mcp.custom_route("/bridge/v1/pages", methods=["GET", "POST"])
async def pages_route(request: Request) -> JSONResponse:
    if request.method == "GET":
        space_id = request.query_params.get("space_id")
        if not space_id:
            return JSONResponse({"ok": False, "error": "space_id is required"}, status_code=422)
        return await safe(
            docmost.list_pages(
                space_id,
                request.query_params.get("parent_page_id"),
                int(request.query_params.get("limit", "100")),
            )
        )
    body = await request.json()
    return await safe(
        docmost.create_page(
            body["space_id"],
            body["title"],
            body.get("content", ""),
            body.get("parent_page_id"),
        )
    )


@mcp.custom_route("/bridge/v1/pages/{page_id}", methods=["GET", "PATCH"])
async def page_route(request: Request) -> JSONResponse:
    page_id = request.path_params["page_id"]
    if request.method == "GET":
        output_format = request.query_params.get("format", "markdown")
        if output_format not in {"markdown", "html", "json"}:
            return JSONResponse({"ok": False, "error": "invalid format"}, status_code=422)
        return await safe(docmost.get_page(page_id, output_format))
    body = await request.json()
    return await safe(
        docmost.update_page(
            page_id,
            body.get("title"),
            body.get("content"),
            body.get("operation", "append"),
        )
    )


@mcp.custom_route("/bridge/v1/pages/{page_id}/move", methods=["POST"])
async def move_page_route(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("space_id"), str):
        return JSONResponse({"ok": False, "error": "space_id is required"}, status_code=422)
    return await safe(
        docmost.move_page_to_space(request.path_params["page_id"], body["space_id"])
    )


@mcp.custom_route("/bridge/v1/search", methods=["GET"])
async def search_route(request: Request) -> JSONResponse:
    query = request.query_params.get("q")
    if not query:
        return JSONResponse({"ok": False, "error": "q is required"}, status_code=422)
    return await safe(
        docmost.search_pages(
            query,
            request.query_params.get("space_id"),
            int(request.query_params.get("limit", "25")),
        )
    )


class BearerAuthMiddleware:
    def __init__(self, wrapped_app: Any, token: str) -> None:
        self.wrapped_app = wrapped_app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") != "/health":
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                response = JSONResponse(
                    {"ok": False, "error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.wrapped_app(scope, receive, send)


app = BearerAuthMiddleware(mcp.streamable_http_app(), BRIDGE_TOKEN)

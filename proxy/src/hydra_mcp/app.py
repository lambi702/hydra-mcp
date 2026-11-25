"""ASGI application: wires the store, vault, router mode, broker mode, admin API and admin page."""

from __future__ import annotations

import contextlib
import html
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from hydra_mcp import __version__
from hydra_mcp.admin.api import build_admin_routes
from hydra_mcp.broker.aggregator import Aggregator
from hydra_mcp.broker.endpoint import BrokerEndpoint
from hydra_mcp.broker.identity import IdentityProbe
from hydra_mcp.broker.oauth import OAuthBroker, OAuthError
from hydra_mcp.broker.upstream import UpstreamClient
from hydra_mcp.clientauth import ClientAuth, Origins
from hydra_mcp.router import Router
from hydra_mcp.settings import Settings
from hydra_mcp.store import Store
from hydra_mcp.vault import Vault

log = logging.getLogger(__name__)


@dataclass
class Services:
    store: Store
    router: Router
    oauth: OAuthBroker
    aggregator: Aggregator
    external_url: str = ""


def create_app(
    settings: Settings | None = None,
    *,
    store: Store | None = None,
    http: httpx.AsyncClient | None = None,
    vault: Vault | None = None,
) -> Starlette:
    settings = settings or Settings()
    store = store or Store(settings.db_path)
    http = http or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.upstream_timeout_s, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": f"hydra-mcp/{__version__}"},
    )
    vault = vault or Vault.from_dir(settings.data_dir)
    router = Router(store, http, settings.base_url)
    upstream_client = UpstreamClient(http)
    oauth = OAuthBroker(
        store, vault, http, router.prm, settings.base_url, IdentityProbe(upstream_client)
    )
    aggregator = Aggregator(store, oauth, upstream_client)
    admin_token = settings.resolved_admin_token
    client_auth = ClientAuth(
        store, Origins(settings.base_url, settings.external_base_url), admin_token
    )
    services = Services(
        store=store,
        router=router,
        oauth=oauth,
        aggregator=aggregator,
        external_url=settings.external_base_url,
    )
    broker = BrokerEndpoint(store, aggregator, client_auth)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await store.open()
        log.info("hydra-mcp %s listening for %s", __version__, settings.base_url)
        try:
            yield
        finally:
            await http.aclose()
            await store.close()

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True, "version": __version__})

    async def oauth_callback(request: Request) -> Response:
        """Browser lands here after logging in at the upstream AS (broker mode)."""
        q = request.query_params
        if "error" in q:
            return _page(
                "Connection cancelled",
                f"The provider answered: {q.get('error')} {q.get('error_description', '')}",
                ok=False,
            )
        if not q.get("state") or not q.get("code"):
            return _page("Invalid callback", "Missing code or state.", ok=False, status=400)
        try:
            result = await oauth.finish_link(q["state"], q["code"])
        except (OAuthError, LookupError) as exc:
            return _page("Connection failed", str(exc), ok=False, status=400)
        aggregator.invalidate(result.account.id)
        # Back to the admin page, which asks for a friendly name when the account is new.
        query = urlencode({"connected": result.account.id, "new": int(result.created)})
        return RedirectResponse(f"/admin/?{query}", status_code=303)

    routes: list[Route | Mount] = [
        Route("/healthz", health, methods=["GET"]),
        # broker mode
        Route("/mcp", broker.handle, methods=["GET", "POST", "DELETE"]),
        Route("/oauth/callback", oauth_callback, methods=["GET"]),
        # router mode
        Route("/a/{account_id}/mcp", router.handle_mcp, methods=["GET", "POST", "DELETE"]),
        Route(
            "/.well-known/oauth-protected-resource/a/{account_id}/mcp",
            router.handle_prm,
            methods=["GET"],
        ),
        *client_auth.routes(),
        *build_admin_routes(services, admin_token),
    ]
    if settings.admin_dist and settings.admin_dist.is_dir():
        routes.append(Route("/", lambda r: RedirectResponse("/admin/"), methods=["GET"]))
        routes.append(Mount("/admin", StaticFiles(directory=settings.admin_dist, html=True)))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.services = services
    app.state.client_auth = client_auth
    return ExposureGuard(app, settings.external_base_url)  # type: ignore[return-value]


# Paths an app on the internet may reach through the external URL. Everything else (admin page
# and API, upstream OAuth callbacks, router mode) answers 404 there.
PUBLIC_PATHS = (
    "/mcp",
    "/oauth/authorize",
    "/oauth/token",
    "/oauth/register",
    "/oauth/revoke",
    "/healthz",
)
PUBLIC_PREFIXES = ("/.well-known/oauth-", "/.well-known/openid-configuration")
FORWARD_HEADERS = (
    b"x-forwarded-for",
    b"x-forwarded-host",
    b"forwarded",
    b"cf-connecting-ip",
    b"x-real-ip",
    b"tailscale-funnel-request",
)


class ExposureGuard:
    """Keep local-only routes local when the proxy is also reachable through a tunnel.

    A tunnel client (cloudflared, ngrok, Tailscale Funnel) runs on this machine, so to the proxy
    every tunneled request comes from 127.0.0.1. What gives it away is the Host header (the
    public name) and the forwarding headers tunnels add. Either one marks the request as
    external, and external requests only reach PUBLIC_PATHS.
    """

    def __init__(self, app: Starlette, external_url: str):
        self.app = app
        self.state = app.state
        self.router = app.router
        ext = urlsplit(external_url) if external_url else None
        self.external_host = (ext.hostname or "").lower() if ext else ""

    def is_external(self, scope) -> bool:
        headers = dict(scope.get("headers") or [])
        if any(h in headers for h in FORWARD_HEADERS):
            return True
        host = headers.get(b"host", b"").decode("latin-1").lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0][1:]
        return bool(self.external_host) and name == self.external_host

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.is_external(scope):
            path = scope.get("path", "")
            if path not in PUBLIC_PATHS and not path.startswith(PUBLIC_PREFIXES):
                response = JSONResponse({"error": "not found"}, 404)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _page(title: str, text: str, *, ok: bool = True, status: int = 200) -> HTMLResponse:
    color = "#15803d" if ok else "#b91c1c"
    body = f"""<!doctype html><meta charset="utf-8"><title>hydra-mcp: {html.escape(title)}</title>
<body style="font-family:system-ui;max-width:560px;margin:64px auto;padding:0 16px">
<h1 style="color:{color};font-size:22px">{html.escape(title)}</h1>
<p>{html.escape(text)}</p><p><a href="/admin/">Back to the admin page</a></p>
</body>"""
    return HTMLResponse(body, status_code=status)

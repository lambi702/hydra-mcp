"""ASGI application: wires the store, vault, router mode, broker mode, admin API and admin page."""

from __future__ import annotations

import contextlib
import html
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlencode

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
from hydra_mcp.broker.stdio import StdioPool
from hydra_mcp.broker.upstream import UpstreamClient
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
    stdio: StdioPool | None = None


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
    stdio = (
        StdioPool(
            settings.data_dir, timeout_s=settings.upstream_timeout_s, idle_s=settings.stdio_idle_s
        )
        if settings.stdio_enabled
        else None
    )
    aggregator = Aggregator(store, oauth, upstream_client, stdio)
    services = Services(store=store, router=router, oauth=oauth, aggregator=aggregator, stdio=stdio)
    broker = BrokerEndpoint(store, aggregator)
    admin_token = settings.resolved_admin_token

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await store.open()
        log.info("hydra-mcp %s listening for %s", __version__, settings.base_url)
        try:
            yield
        finally:
            if stdio is not None:
                await stdio.close()
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
        await aggregator.invalidate(result.account.id)
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
        *build_admin_routes(services, admin_token),
    ]
    if settings.admin_dist and settings.admin_dist.is_dir():
        routes.append(Route("/", lambda r: RedirectResponse("/admin/"), methods=["GET"]))
        routes.append(Mount("/admin", StaticFiles(directory=settings.admin_dist, html=True)))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.services = services
    return app


def _page(title: str, text: str, *, ok: bool = True, status: int = 200) -> HTMLResponse:
    color = "#15803d" if ok else "#b91c1c"
    body = f"""<!doctype html><meta charset="utf-8"><title>hydra-mcp: {html.escape(title)}</title>
<body style="font-family:system-ui;max-width:560px;margin:64px auto;padding:0 16px">
<h1 style="color:{color};font-size:22px">{html.escape(title)}</h1>
<p>{html.escape(text)}</p><p><a href="/admin/">Back to the admin page</a></p>
</body>"""
    return HTMLResponse(body, status_code=status)

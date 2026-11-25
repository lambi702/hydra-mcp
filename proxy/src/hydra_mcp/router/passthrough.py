"""Router mode: one URL per account, the client holds the upstream token (phase 0).

    client --(Bearer token for gmail-work)--> /a/gmail-work/mcp --(same token)--> upstream

The proxy never reads, stores or changes the Authorization header. It streams bodies in both
directions (SSE included), so Mcp-Session-Id, server-to-client requests and notifications work
unchanged: in router mode the proxy is 1:1 with one upstream session.
"""

from __future__ import annotations

import logging

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from hydra_mcp.router.discovery import (
    DiscoveryError,
    PrmCache,
    proxy_prm_url,
    rewrite_www_authenticate,
)
from hydra_mcp.store import NotFound, Store

log = logging.getLogger(__name__)

# RFC 9110 section 7.6.1 hop-by-hop headers, plus ones we must recompute.
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
# Set again by our own server (uvicorn); forwarding the upstream's would duplicate them.
RESPONSE_DROP = HOP_BY_HOP | {"date", "server"}


def account_resource(base_url: str, account_id: str) -> str:
    return f"{base_url}/a/{account_id}/mcp"


class Router:
    def __init__(self, store: Store, http: httpx.AsyncClient, base_url: str):
        self.store = store
        self.http = http
        self.base_url = base_url
        self.prm = PrmCache(http)

    async def _resolve(self, account_id: str):
        try:
            account, upstream = await self.store.get_account(account_id)
        except NotFound:
            return None, None
        if not account.enabled or upstream.is_stdio:
            # Router mode forwards HTTP as is; a local process has no URL to forward to.
            return None, None
        return account, upstream

    async def handle_mcp(self, request: Request) -> Response:
        account_id = request.path_params["account_id"]
        account, upstream = await self._resolve(account_id)
        if account is None:
            return JSONResponse(
                {"error": f"unknown, disabled or local (stdio) account '{account_id}'"}, 404
            )

        upstream_url = str(upstream.url)
        headers = [(k, v) for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP]
        upstream_req = self.http.build_request(
            request.method,
            upstream_url,
            params=request.query_params,
            headers=headers,
            content=request.stream(),
        )
        try:
            upstream_resp = await self.http.send(upstream_req, stream=True)
        except httpx.HTTPError as exc:
            log.warning("upstream %s unreachable: %s", upstream_url, exc)
            return JSONResponse({"error": f"upstream unreachable: {exc.__class__.__name__}"}, 502)

        out_headers = {
            k: v for k, v in upstream_resp.headers.items() if k.lower() not in RESPONSE_DROP
        }
        www = upstream_resp.headers.get("www-authenticate")
        if www and upstream_resp.status_code in (401, 403):
            self.prm.remember_hint(upstream_url, www)
            resource = account_resource(self.base_url, account.id)
            out_headers["www-authenticate"] = rewrite_www_authenticate(www, proxy_prm_url(resource))

        return StreamingResponse(
            upstream_resp.aiter_raw(),
            status_code=upstream_resp.status_code,
            headers=out_headers,
            background=BackgroundTask(upstream_resp.aclose),
        )

    async def handle_prm(self, request: Request) -> Response:
        """GET /.well-known/oauth-protected-resource/a/{account_id}/mcp"""
        account_id = request.path_params["account_id"]
        account, upstream = await self._resolve(account_id)
        if account is None:
            return JSONResponse({"error": f"unknown or disabled account '{account_id}'"}, 404)
        try:
            doc = await self.prm.account_prm(
                str(upstream.url), account_resource(self.base_url, account.id)
            )
        except DiscoveryError as exc:
            return JSONResponse({"error": str(exc)}, 502)
        return JSONResponse(doc, headers={"Cache-Control": "max-age=300"})

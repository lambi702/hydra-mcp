"""Admin API under /admin/api, protected by a bearer admin token.

Only meant to be reachable from your machine (the proxy binds 127.0.0.1 by default).
"""

from __future__ import annotations

import hmac
import re
import secrets
import sqlite3
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hydra_mcp import __version__
from hydra_mcp.broker.endpoint import KEY_PREFIX, hash_key
from hydra_mcp.broker.identity import IdentityProbe
from hydra_mcp.broker.oauth import NeedsManualClient, OAuthError
from hydra_mcp.broker.setup import setup_guide
from hydra_mcp.broker.upstream import UpstreamAuthError, UpstreamError
from hydra_mcp.catalog import load_catalog
from hydra_mcp.models import Account, Client, Upstream
from hydra_mcp.router import Router, account_resource
from hydra_mcp.router.discovery import DiscoveryError, fetch_as_metadata
from hydra_mcp.store import NotFound

if TYPE_CHECKING:
    from hydra_mcp.app import Services

Handler = Callable[[Request], Awaitable[Response]]


def _json(model: BaseModel | list[BaseModel], status: int = 200) -> JSONResponse:
    if isinstance(model, list):
        return JSONResponse([m.model_dump(mode="json") for m in model], status)
    return JSONResponse(model.model_dump(mode="json"), status)


def build_admin_routes(services: Services, admin_token: str) -> list[Route]:
    store, router, oauth, aggregator = (
        services.store,
        services.router,
        services.oauth,
        services.aggregator,
    )

    def guarded(fn: Handler) -> Handler:
        async def wrapper(request: Request) -> Response:
            auth = request.headers.get("authorization", "")
            given = auth.removeprefix("Bearer ").strip()
            if not given or not hmac.compare_digest(given, admin_token):
                return JSONResponse({"error": "admin token required"}, 401)
            try:
                return await fn(request)
            except ValidationError as exc:
                detail = exc.errors(include_url=False, include_context=False, include_input=False)
                return JSONResponse({"error": "invalid body", "detail": detail}, 422)
            except NotFound as exc:
                return JSONResponse({"error": f"not found: {exc}"}, 404)
            except sqlite3.IntegrityError as exc:
                return JSONResponse({"error": f"conflict: {exc}"}, 409)

        return wrapper

    async def status(request: Request) -> Response:
        accounts = await store.list_accounts()
        return JSONResponse(
            {
                "version": __version__,
                "modes": ["router", "broker"],
                "public_url": router.base_url,
                "broker_endpoint": f"{router.base_url}/mcp",
                "endpoints": {
                    a.id: account_resource(router.base_url, a.id) for a in accounts if a.enabled
                },
            }
        )

    # upstreams
    async def list_upstreams(request: Request) -> Response:
        return _json(await store.list_upstreams())

    async def put_upstream(request: Request) -> Response:
        u = Upstream.model_validate(await request.json())
        return _json(await store.put_upstream(u))

    async def delete_upstream(request: Request) -> Response:
        await store.delete_upstream(request.path_params["id"])
        return Response(status_code=204)

    async def probe_upstream(request: Request) -> Response:
        """Fetch the upstream's PRM and AS metadata, to see where users will log in."""
        upstreams = {u.id: u for u in await store.list_upstreams()}
        u = upstreams.get(request.path_params["id"])
        if u is None:
            raise NotFound(request.path_params["id"])
        router.prm.docs.pop(str(u.url), None)
        try:
            prm = await router.prm.upstream_prm(str(u.url))
        except DiscoveryError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        issuers = []
        for issuer in prm.get("authorization_servers", []):
            issuers.append(await _as_metadata(router, issuer))
        return JSONResponse(
            {"ok": True, "protected_resource": prm, "authorization_servers": issuers}
        )

    # accounts
    async def list_accounts(request: Request) -> Response:
        return _json(await store.list_accounts())

    async def put_account(request: Request) -> Response:
        a = Account.model_validate(await request.json())
        return _json(await store.put_account(a))

    async def delete_account(request: Request) -> Response:
        await store.delete_account(request.path_params["id"])  # its token goes with it
        aggregator.invalidate(request.path_params["id"])
        return Response(status_code=204)

    async def accounts_status(request: Request) -> Response:
        """Broker mode: which accounts are connected, as whom, and until when."""
        return JSONResponse(await store.token_status())

    async def refresh_identity(request: Request) -> Response:
        """Ask the upstream who this account is (for accounts connected before probes existed)."""
        account, upstream = await store.get_account(request.path_params["id"])
        probe = oauth.identity_probe
        if probe is None or not getattr(probe, "supports", lambda u: True)(upstream):
            return JSONResponse({"identity": account.identity, "changed": False})
        try:
            token = await oauth.access_token(account, upstream)
        except OAuthError as exc:
            return JSONResponse({"error": str(exc)}, 409)
        identity = await probe(upstream, token)
        changed = bool(identity) and identity != account.identity
        if changed:
            await store.put_account(account.model_copy(update={"identity": identity}))
        return JSONResponse({"identity": identity or account.identity, "changed": changed})

    async def link_account(request: Request) -> Response:
        account, upstream = await store.get_account(request.path_params["id"])
        try:
            url = await oauth.start_link(account, upstream)
        except NeedsManualClient as exc:
            return _needs_client(exc, upstream)
        except OAuthError as exc:
            return JSONResponse({"error": str(exc)}, 502)
        return JSONResponse({"authorize_url": url})

    def _needs_client(exc: NeedsManualClient, upstream: Upstream) -> JSONResponse:
        return JSONResponse(
            {
                "error": str(exc),
                "needs_manual_client": True,
                "upstream_id": upstream.id,
                "guide": setup_guide(upstream, oauth.redirect_uri_for(upstream)),
            },
            409,
        )

    async def _resolve_upstream(body: dict) -> Upstream | JSONResponse:
        """{"upstream_id"} | {"connector_id"} | {"name", "url"} -> the upstream, found or created
        (by URL, so the same server is never added twice, unless {"new_upstream": true} asks
        for a second row with its own OAuth client)."""
        if body.get("upstream_id"):
            return await store.get_upstream(body["upstream_id"])
        upstreams = await store.list_upstreams()
        if body.get("connector_id"):
            c = load_catalog().get(body["connector_id"])
            if c is None:
                raise NotFound(body["connector_id"])
            name, url, base = c.name, str(c.url), c.id
        else:
            name, url = (body.get("name") or "").strip(), (body.get("url") or "").strip()
            if not name or not url:
                return JSONResponse({"error": "name and url are required"}, 422)
            base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "server"
        same_url = [u for u in upstreams if str(u.url).rstrip("/") == url.rstrip("/")]
        if body.get("new_upstream"):
            # e.g. another Slack workspace, with its own OAuth client. A row of this URL that
            # has no account yet is a previous attempt (login cancelled): reuse it.
            used = {a.upstream_id for a in await store.list_accounts()}
            same = next((u for u in same_url if u.id not in used), None)
        else:
            same = same_url[0] if same_url else None
        if same is None:
            taken = {u.id for u in upstreams}
            uid, i = base, 2
            while uid in taken:
                uid, i = f"{base}-{i}", i + 1
            same = await store.put_upstream(Upstream(id=uid, name=name, url=url))
        return same

    async def connect(request: Request) -> Response:
        """Start connecting a new account. Body: {"connector_id"} (library), {"upstream_id"}
        (another account on a known server) or {"name", "url"} (any MCP server).

        The upstream row is found or created here (it also holds the proxy's OAuth client
        registration, reused by the next account); the account itself is created by the
        OAuth callback, only once the login succeeded.
        """
        upstream = await _resolve_upstream(await request.json())
        if isinstance(upstream, JSONResponse):
            return upstream
        try:
            url = await oauth.start_link(None, upstream)
        except NeedsManualClient as exc:
            return _needs_client(exc, upstream)
        except OAuthError as exc:
            return JSONResponse({"error": str(exc), "upstream_id": upstream.id}, 502)
        return JSONResponse({"authorize_url": url, "upstream_id": upstream.id})

    async def connect_token(request: Request) -> Response:
        """Connect with a pasted token (PAT, API key) instead of an OAuth login.

        Body: the same upstream selector as /connect, plus {"token"} and optionally
        {"account_id"} to replace the token of an existing account. The token is tried against
        the upstream first, so a typo never becomes a "connected" account.
        """
        body = await request.json()
        token = (body.get("token") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            return JSONResponse({"error": "token is required"}, 422)
        account_id = body.get("account_id") or None
        if account_id:
            _, upstream = await store.get_account(account_id)
        else:
            upstream = await _resolve_upstream(body)
            if isinstance(upstream, JSONResponse):
                return upstream
        try:
            identity = await IdentityProbe(aggregator.upstream).verify(upstream, token)
        except UpstreamAuthError:
            return JSONResponse(
                {
                    "error": f"{upstream.name} refused this token. Check that it was copied "
                    "whole, has not expired, and has the permissions the guide lists."
                },
                400,
            )
        except UpstreamError as exc:
            return JSONResponse({"error": f"{upstream.name}: {exc}"}, 502)
        except httpx.HTTPError as exc:
            return JSONResponse(
                {"error": f"Could not reach {upstream.name} ({type(exc).__name__}): {exc}"}, 502
            )
        result = await oauth.link_token(upstream, token, identity, account_id)
        aggregator.invalidate(result.account.id)
        return JSONResponse(
            {
                "account": result.account.model_dump(mode="json"),
                "created": result.created,
                "upstream_id": upstream.id,
            }
        )

    async def unlink_account(request: Request) -> Response:
        await oauth.unlink(request.path_params["id"])
        aggregator.invalidate(request.path_params["id"])
        return Response(status_code=204)

    async def upstream_oauth(request: Request) -> Response:
        """GET: how the proxy is registered at this upstream. PUT: set a manual OAuth client."""
        upstream_id = request.path_params["id"]
        upstream = {u.id: u for u in await store.list_upstreams()}.get(upstream_id)
        if upstream is None:
            raise NotFound(upstream_id)
        if request.method == "PUT":
            body = await request.json()
            client_id = (body.get("client_id") or "").strip()
            if not client_id:
                return JSONResponse({"error": "client_id is required"}, 422)
            try:
                await oauth.set_manual_client(
                    upstream, client_id, body.get("client_secret") or None
                )
            except OAuthError as exc:
                return JSONResponse({"error": str(exc)}, 502)
        elif request.method == "DELETE":
            await store.delete_upstream_oauth(upstream_id)
            return Response(status_code=204)
        row = await store.get_upstream_oauth(upstream_id)
        guide = setup_guide(upstream, oauth.redirect_uri_for(upstream))
        if row is None:
            return JSONResponse(
                {
                    "registered": False,
                    "redirect_uri": oauth.redirect_uri_for(upstream),
                    "guide": guide,
                }
            )
        return JSONResponse(
            {
                "registered": True,
                "registration": row["registration"],
                "issuer": row["issuer"],
                "client_id": row["client_id"],
                "has_secret": row["secret_enc"] is not None,
                "redirect_uri": oauth.redirect_uri_for(upstream),
                "guide": guide,
            }
        )

    async def client_key(request: Request) -> Response:
        """POST: create (or rotate) the client's key; it is shown once. DELETE: revoke it."""
        client_id = request.path_params["id"]
        if request.method == "DELETE":
            await store.set_client_key_hash(client_id, None)
            return Response(status_code=204)
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        await store.set_client_key_hash(client_id, hash_key(key))
        return JSONResponse({"key": key, "endpoint": f"{router.base_url}/mcp"}, 201)

    async def clients_with_key(request: Request) -> Response:
        return JSONResponse(sorted(await store.clients_with_key()))

    # connector library
    async def catalog(request: Request) -> Response:
        cat = load_catalog()
        installed = {str(u.url): u.id for u in await store.list_upstreams()}
        return JSONResponse(
            {
                "checked_at": cat.checked_at,
                "connectors": [
                    {**c.model_dump(mode="json"), "installed_as": installed.get(str(c.url))}
                    for c in cat.connectors
                ],
            }
        )

    async def install_connector(request: Request) -> Response:
        """Create an upstream from a library entry. Body (optional): {"id": "<upstream id>"}."""
        c = load_catalog().get(request.path_params["id"])
        if c is None:
            raise NotFound(request.path_params["id"])
        body = await request.json() if await request.body() else {}
        u = Upstream(id=body.get("id") or c.id, name=c.name, url=c.url)
        return _json(await store.put_upstream(u), 201)

    # clients
    async def list_clients(request: Request) -> Response:
        return _json(await store.list_clients())

    async def put_client(request: Request) -> Response:
        c = Client.model_validate(await request.json())
        return _json(await store.put_client(c))

    async def delete_client(request: Request) -> Response:
        await store.delete_client(request.path_params["id"])
        return Response(status_code=204)

    p = "/admin/api"
    return [
        Route(f"{p}/status", guarded(status), methods=["GET"]),
        Route(f"{p}/catalog", guarded(catalog), methods=["GET"]),
        Route(f"{p}/catalog/{{id}}/install", guarded(install_connector), methods=["POST"]),
        Route(f"{p}/upstreams", guarded(list_upstreams), methods=["GET"]),
        Route(f"{p}/upstreams", guarded(put_upstream), methods=["POST", "PUT"]),
        Route(f"{p}/upstreams/{{id}}", guarded(delete_upstream), methods=["DELETE"]),
        Route(f"{p}/upstreams/{{id}}/probe", guarded(probe_upstream), methods=["POST"]),
        Route(f"{p}/accounts", guarded(list_accounts), methods=["GET"]),
        Route(f"{p}/accounts", guarded(put_account), methods=["POST", "PUT"]),
        Route(f"{p}/accounts/{{id}}", guarded(delete_account), methods=["DELETE"]),
        Route(f"{p}/accounts-status", guarded(accounts_status), methods=["GET"]),
        Route(f"{p}/connect", guarded(connect), methods=["POST"]),
        Route(f"{p}/connect-token", guarded(connect_token), methods=["POST"]),
        Route(f"{p}/accounts/{{id}}/identity", guarded(refresh_identity), methods=["POST"]),
        Route(f"{p}/accounts/{{id}}/link", guarded(link_account), methods=["POST"]),
        Route(f"{p}/accounts/{{id}}/link", guarded(unlink_account), methods=["DELETE"]),
        Route(
            f"{p}/upstreams/{{id}}/oauth",
            guarded(upstream_oauth),
            methods=["GET", "PUT", "DELETE"],
        ),
        Route(f"{p}/clients/{{id}}/key", guarded(client_key), methods=["POST", "DELETE"]),
        Route(f"{p}/clients-with-key", guarded(clients_with_key), methods=["GET"]),
        Route(f"{p}/clients", guarded(list_clients), methods=["GET"]),
        Route(f"{p}/clients", guarded(put_client), methods=["POST", "PUT"]),
        Route(f"{p}/clients/{{id}}", guarded(delete_client), methods=["DELETE"]),
    ]


async def _as_metadata(router: Router, issuer: str) -> dict:
    found = await fetch_as_metadata(router.http, issuer)
    if found is None:
        return {"issuer": issuer, "error": "no authorization server metadata found"}
    url, meta = found
    return {
        "issuer": issuer,
        "metadata_url": url,
        "authorization_endpoint": meta.get("authorization_endpoint"),
        "token_endpoint": meta.get("token_endpoint"),
        "registration_endpoint": meta.get("registration_endpoint"),
        "client_id_metadata_document_supported": meta.get(
            "client_id_metadata_document_supported", False
        ),
        "code_challenge_methods_supported": meta.get("code_challenge_methods_supported"),
        "scopes_supported": meta.get("scopes_supported"),
    }

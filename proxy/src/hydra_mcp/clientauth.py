"""hydra-mcp as an OAuth 2.1 authorization server for its own clients (the AI apps).

Why: claude.ai and Claude Desktop custom connectors cannot send a static header. They speak
the MCP authorization spec: they read the protected resource metadata (RFC 9728), the
authorization server metadata (RFC 8414), register themselves (RFC 7591, DCR), send the user
to /authorize with PKCE (S256), and exchange the code at /token. So hydra-mcp plays that role
toward its clients, while it stays an OAuth *client* of each upstream (broker mode). Two
separate trust relationships, never mixed:

    claude.ai --(hydra access token)--> hydra-mcp /mcp --(upstream token of the chosen
                                                         account)--> Gmail, Atlassian...

The consent step is where Lambi's rule "one login per client app" lands: approving a login
binds that app to one hydra-mcp *client* (an existing one, or a new one). Its grants (which
accounts, read or write) stay managed in the admin page and apply immediately to every token.

Tokens are opaque random strings (`hmcp_at_…`, `hmcp_rt_…`); only their SHA-256 is stored.
Access tokens last one hour. Refresh tokens last 30 days and rotate on every use; presenting
an already-rotated refresh token revokes the whole grant (OAuth 2.1 reuse detection).

Who may approve: whoever holds the admin token. The consent page asks for it, so an
attacker who reaches the public URL can register an app but cannot finish a login.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from hydra_mcp.models import Client
from hydra_mcp.store import NotFound, Store

log = logging.getLogger(__name__)

ACCESS_PREFIX = "hmcp_at_"
REFRESH_PREFIX = "hmcp_rt_"
ACCESS_TTL_S = 3600
REFRESH_TTL_S = 30 * 24 * 3600
CODE_TTL_S = 120
PENDING_TTL_S = 600
MAX_APPS = 500  # open registration: cap it, unused registrations are pruned after a day
MAX_FAILED_APPROVALS = 10  # per 10 minutes, then the consent form refuses for a while
SCOPE = "mcp"


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _b64url_sha256(value: str) -> str:
    import base64

    digest = hashlib.sha256(value.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _redirect_ok(uri: str) -> bool:
    """RFC 8252 / OAuth 2.1: https anywhere, http only for loopback, or a private app scheme."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or not parts.scheme:
        return False
    if parts.scheme == "https":
        return bool(parts.hostname)
    if parts.scheme == "http":
        return parts.hostname in ("127.0.0.1", "localhost", "::1")
    # e.g. cursor://anysphere... (native apps). javascript:/data: are not URLs an AS redirects to.
    return parts.scheme not in ("javascript", "data", "file", "vbscript") and "." in parts.scheme


def _redirect_matches(registered: list[str], given: str) -> bool:
    """Exact match, except the port of a loopback http redirect (RFC 8252 section 7.3)."""
    if given in registered:
        return True
    g = urlsplit(given)
    if g.scheme != "http" or g.hostname not in ("127.0.0.1", "localhost", "::1"):
        return False
    for r in registered:
        p = urlsplit(r)
        if (p.scheme, p.hostname, p.path, p.query) == (g.scheme, g.hostname, g.path, g.query):
            return True
    return False


def _with_query(uri: str, params: dict) -> str:
    parts = urlsplit(uri)
    query = parts.query + ("&" if parts.query else "") + urlencode(params)
    return urlunsplit(parts._replace(query=query))


async def _form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded body (what OAuth token requests and HTML forms send),
    parsed without the python-multipart dependency. A JSON body is accepted too."""
    raw = await request.body()
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    return dict(parse_qsl(raw.decode("utf-8", errors="replace"), keep_blank_values=True))


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status,
        headers={"Cache-Control": "no-store"},
    )


@dataclass
class Origins:
    """The proxy can be reached under two names: its local public URL (apps on this machine) and
    an external HTTPS URL (a tunnel, for claude.ai). Metadata answers with the name the request
    came in on, so the issuer always matches where the client fetched it."""

    local: str
    external: str = ""

    def for_request(self, request: Request) -> str:
        if self.external:
            ext = urlsplit(self.external)
            host = request.headers.get("host", "")
            if host == ext.netloc or host.split(":")[0] == ext.hostname:
                return self.external
        return self.local

    def resources(self) -> set[str]:
        return {f"{o}/mcp" for o in (self.local, self.external) if o}


class ClientAuth:
    def __init__(self, store: Store, origins: Origins, admin_token: str):
        self.store = store
        self.origins = origins
        self.admin_token = admin_token
        self._failures: list[float] = []

    # -- token check for /mcp ---------------------------------------------------------------------
    async def client_for_access_token(self, token: str) -> Client | None:
        if not token.startswith(ACCESS_PREFIX):
            return None
        row = await self.store.oauth_grant_by_access(sha(token), time.time())
        if row is None:
            return None
        try:
            return await self.store.get_client(row["client_id"])
        except NotFound:
            return None

    def challenge(self, request: Request) -> str:
        origin = self.origins.for_request(request)
        return (
            f'Bearer resource_metadata="{origin}/.well-known/oauth-protected-resource/mcp", '
            f'scope="{SCOPE}"'
        )

    # -- metadata ---------------------------------------------------------------------------------
    async def protected_resource(self, request: Request) -> Response:
        origin = self.origins.for_request(request)
        return JSONResponse(
            {
                "resource": f"{origin}/mcp",
                "authorization_servers": [origin],
                "scopes_supported": [SCOPE],
                "bearer_methods_supported": ["header"],
                "resource_name": "hydra-mcp",
            },
            headers={"Cache-Control": "max-age=300"},
        )

    async def server_metadata(self, request: Request) -> Response:
        origin = self.origins.for_request(request)
        return JSONResponse(
            {
                "issuer": origin,
                "authorization_endpoint": f"{origin}/oauth/authorize",
                "token_endpoint": f"{origin}/oauth/token",
                "registration_endpoint": f"{origin}/oauth/register",
                "revocation_endpoint": f"{origin}/oauth/revoke",
                "scopes_supported": [SCOPE],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "authorization_response_iss_parameter_supported": True,
            },
            headers={"Cache-Control": "max-age=300"},
        )

    # -- dynamic client registration (RFC 7591) ------------------------------------------------
    async def register(self, request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return _oauth_error("invalid_client_metadata", "body must be JSON")
        if not isinstance(body, dict):
            return _oauth_error("invalid_client_metadata", "body must be a JSON object")
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
            return _oauth_error("invalid_redirect_uri", "redirect_uris is required")
        bad = [u for u in uris if not _redirect_ok(u)]
        if bad:
            return _oauth_error("invalid_redirect_uri", f"not allowed: {', '.join(bad)[:200]}")
        grant_types = body.get("grant_types") or ["authorization_code"]
        if "authorization_code" not in grant_types:
            return _oauth_error("invalid_client_metadata", "authorization_code is required")
        now = time.time()
        await self.store.prune_oauth_apps(now - 24 * 3600)
        if await self.store.count_oauth_apps() >= MAX_APPS:
            return _oauth_error("invalid_client_metadata", "too many registrations", 429)
        name = str(body.get("client_name") or "MCP app")[:80]
        client_id = "app_" + secrets.token_urlsafe(16)
        await self.store.put_oauth_app(client_id, name, uris, now)
        log.info("registered OAuth app %s (%s)", client_id, name)
        return JSONResponse(
            {
                "client_id": client_id,
                "client_id_issued_at": int(now),
                "client_name": name,
                "redirect_uris": uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": SCOPE,
            },
            201,
            headers={"Cache-Control": "no-store"},
        )

    # -- authorization endpoint + consent ------------------------------------------------------
    async def authorize(self, request: Request) -> Response:
        if request.method == "POST":
            return await self._decide(request)
        q = request.query_params
        app = await self.store.get_oauth_app(q.get("client_id", ""))
        redirect_uri = q.get("redirect_uri", "")
        # Until client_id and redirect_uri are known good, errors are shown, never redirected
        # (an open redirector otherwise).
        if app is None:
            return _consent_error("Unknown application", "This app is not registered here.")
        if not redirect_uri and len(app["redirect_uris"]) == 1:
            redirect_uri = app["redirect_uris"][0]
        if not _redirect_matches(app["redirect_uris"], redirect_uri):
            return _consent_error("Invalid redirect", "The redirect URI was not registered.")

        def fail(error: str, description: str) -> Response:
            params = {"error": error, "error_description": description}
            if q.get("state"):
                params["state"] = q["state"]
            params["iss"] = self.origins.for_request(request)
            return RedirectResponse(_with_query(redirect_uri, params), status_code=302)

        if q.get("response_type") != "code":
            return fail("unsupported_response_type", "only response_type=code")
        if not q.get("code_challenge") or q.get("code_challenge_method") != "S256":
            return fail("invalid_request", "PKCE with code_challenge_method=S256 is required")
        resource = q.get("resource")
        if resource and resource.rstrip("/") not in self.origins.resources():
            return fail("invalid_target", "unknown resource")
        request_id = secrets.token_urlsafe(24)
        now = time.time()
        await self.store.put_oauth_pending(
            request_id,
            {
                "app_id": app["client_id"],
                "redirect_uri": redirect_uri,
                "state": q.get("state"),
                "challenge": q["code_challenge"],
                "resource": resource,
                "origin": self.origins.for_request(request),
            },
            now,
            now - PENDING_TTL_S,
        )
        clients = await self.store.list_clients()
        return _consent_page(app, redirect_uri, request_id, clients)

    async def _decide(self, request: Request) -> Response:
        form = await _form(request)
        now = time.time()
        pending = await self.store.pop_oauth_pending(str(form.get("request_id", "")), now)
        if pending is None:
            return _consent_error(
                "Expired", "This login request expired. Start again from the app."
            )
        redirect_uri = pending["redirect_uri"]

        def back(params: dict) -> Response:
            if pending.get("state"):
                params["state"] = pending["state"]
            params["iss"] = pending["origin"]
            return RedirectResponse(_with_query(redirect_uri, params), status_code=303)

        if form.get("action") != "approve":
            return back({"error": "access_denied", "error_description": "the user declined"})
        self._failures = [t for t in self._failures if t > now - 600]
        if len(self._failures) >= MAX_FAILED_APPROVALS:
            return _consent_error("Too many attempts", "Wait ten minutes, then start again.")
        given = str(form.get("admin_token", "")).strip()
        if not given or not hmac.compare_digest(given, self.admin_token):
            self._failures.append(now)
            # A new pending request, so the person can retry without restarting the app.
            app = await self.store.get_oauth_app(pending["app_id"])
            if app is None:
                return _consent_error("Unknown application", "This app is not registered here.")
            request_id = secrets.token_urlsafe(24)
            await self.store.put_oauth_pending(request_id, pending, now, now - PENDING_TTL_S)
            return _consent_page(
                app,
                redirect_uri,
                request_id,
                await self.store.list_clients(),
                error="Wrong admin token.",
                status=401,
            )
        client = await self._client_from_form(form, pending["app_id"])
        code = secrets.token_urlsafe(32)
        await self.store.put_oauth_code(
            sha(code),
            {**pending, "client_id": client.id},
            now + CODE_TTL_S,
        )
        log.info("app %s approved as client %s", pending["app_id"], client.id)
        return back({"code": code})

    async def _client_from_form(self, form, app_id: str) -> Client:
        choice = str(form.get("client", ""))
        if choice and choice != "__new__":
            try:
                return await self.store.get_client(choice)
            except NotFound:
                pass
        app = await self.store.get_oauth_app(app_id)
        name = (str(form.get("new_name", "")).strip() or (app or {}).get("name") or "App")[:60]
        base = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")[:28]
        base = "-".join(filter(None, base.split("-"))) or "app"
        taken = {c.id for c in await self.store.list_clients()}
        cid, i = base, 2
        while cid in taken:
            cid, i = f"{base}-{i}", i + 1
        return await self.store.put_client(Client(id=cid, name=name))

    # -- token endpoint ------------------------------------------------------------------------
    async def token(self, request: Request) -> Response:
        form = await _form(request)
        grant_type = form.get("grant_type")
        now = time.time()
        if grant_type == "authorization_code":
            row = await self.store.pop_oauth_code(sha(str(form.get("code", ""))), now)
            if row is None:
                return _oauth_error("invalid_grant", "unknown, used or expired code")
            if form.get("client_id") and form.get("client_id") != row["app_id"]:
                return _oauth_error("invalid_grant", "code was issued to another client")
            if form.get("redirect_uri") and form.get("redirect_uri") != row["redirect_uri"]:
                return _oauth_error("invalid_grant", "redirect_uri does not match")
            verifier = str(form.get("code_verifier", ""))
            if not verifier or not hmac.compare_digest(_b64url_sha256(verifier), row["challenge"]):
                return _oauth_error("invalid_grant", "PKCE verification failed")
            grant_id = "g_" + secrets.token_urlsafe(12)
            access, refresh = self._new_pair()
            await self.store.create_oauth_grant(
                grant_id,
                app_id=row["app_id"],
                client_id=row["client_id"],
                access_hash=sha(access),
                access_expires=now + ACCESS_TTL_S,
                refresh_hash=sha(refresh),
                refresh_expires=now + REFRESH_TTL_S,
                now=now,
            )
            return self._token_response(access, refresh)
        if grant_type == "refresh_token":
            presented = sha(str(form.get("refresh_token", "")))
            row = await self.store.oauth_grant_by_refresh(presented)
            if row is None:
                reused = await self.store.oauth_grant_by_previous_refresh(presented)
                if reused is not None:
                    # A rotated refresh token came back: someone kept a copy. Kill the grant.
                    log.warning("refresh token reuse on grant %s: revoked", reused["id"])
                    await self.store.delete_oauth_grant(reused["id"])
                return _oauth_error("invalid_grant", "unknown or revoked refresh token")
            if row["refresh_expires"] < now:
                await self.store.delete_oauth_grant(row["id"])
                return _oauth_error("invalid_grant", "refresh token expired")
            if form.get("client_id") and form.get("client_id") != row["app_id"]:
                return _oauth_error("invalid_grant", "refresh token of another client")
            access, refresh = self._new_pair()
            await self.store.rotate_oauth_grant(
                row["id"],
                access_hash=sha(access),
                access_expires=now + ACCESS_TTL_S,
                refresh_hash=sha(refresh),
                refresh_expires=now + REFRESH_TTL_S,
                now=now,
            )
            return self._token_response(access, refresh)
        return _oauth_error("unsupported_grant_type", "authorization_code or refresh_token")

    async def revoke(self, request: Request) -> Response:
        """RFC 7009: always 200, whatever the token."""
        form = await _form(request)
        token = str(form.get("token", ""))
        h = sha(token)
        row = await self.store.oauth_grant_by_refresh(h) or await self.store.oauth_grant_by_access(
            h, time.time()
        )
        if row is not None:
            await self.store.delete_oauth_grant(row["id"])
        return Response(status_code=200)

    @staticmethod
    def _new_pair() -> tuple[str, str]:
        return ACCESS_PREFIX + secrets.token_urlsafe(32), REFRESH_PREFIX + secrets.token_urlsafe(32)

    @staticmethod
    def _token_response(access: str, refresh: str) -> JSONResponse:
        return JSONResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": ACCESS_TTL_S,
                "refresh_token": refresh,
                "scope": SCOPE,
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    def routes(self) -> list[Route]:
        return [
            Route("/.well-known/oauth-protected-resource", self.protected_resource),
            Route("/.well-known/oauth-protected-resource/mcp", self.protected_resource),
            Route("/.well-known/oauth-authorization-server", self.server_metadata),
            # Some clients only try the OpenID path; the same document answers there.
            Route("/.well-known/openid-configuration", self.server_metadata),
            Route("/oauth/register", self.register, methods=["POST"]),
            Route("/oauth/authorize", self.authorize, methods=["GET", "POST"]),
            Route("/oauth/token", self.token, methods=["POST"]),
            Route("/oauth/revoke", self.revoke, methods=["POST"]),
        ]


# -- consent page (server-rendered: no admin page assets needed on the public URL) ------------
_HEADERS = {
    "X-Frame-Options": "DENY",
    # No form-action: browsers apply it to the redirect after the POST, and native apps
    # redirect to their own schemes (cursor://...).
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
    "frame-ancestors 'none'",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}
_STYLE = """body{font:15px/1.5 system-ui,sans-serif;max-width:520px;margin:48px auto;padding:0 16px;
color:#1f2330;background:#f6f7f9}@media(prefers-color-scheme:dark){body{color:#e8eaf0;
background:#14161b}.box{background:#1d2027!important;border-color:#2c313b!important}
input,select{background:#14161b!important;color:#e8eaf0!important;border-color:#2c313b!important}}
.box{background:#fff;border:1px solid #e2e5ea;border-radius:14px;padding:22px}
h1{font-size:20px;margin:0 0 6px}label{display:grid;gap:6px;margin:14px 0;font-weight:500}
input,select{font:inherit;padding:8px 10px;border-radius:9px;border:1px solid #d5d9e0}
.muted{color:#6b7280;font-size:13px}.err{color:#b91c1c;font-weight:600}
.row{display:flex;gap:10px;margin-top:18px}button{font:inherit;padding:9px 16px;border-radius:9px;
border:1px solid #d5d9e0;background:transparent;color:inherit;cursor:pointer}
button.primary{background:#4f46e5;border-color:#4f46e5;color:#fff;font-weight:600}
code{font-size:13px}"""


def _consent_error(title: str, text: str) -> HTMLResponse:
    body = (
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>hydra-mcp</title><style>{_STYLE}</style><div class=box><h1>{html.escape(title)}"
        f"</h1><p>{html.escape(text)}</p></div>"
    )
    return HTMLResponse(body, 400, headers=_HEADERS)


def _consent_page(
    app: dict,
    redirect_uri: str,
    request_id: str,
    clients: list[Client],
    *,
    error: str = "",
    status: int = 200,
) -> HTMLResponse:
    e = html.escape
    host = urlsplit(redirect_uri).hostname or redirect_uri
    name = app["name"]
    lower = name.lower()
    match = next((c for c in clients if c.name.lower() == lower), None)
    options = [
        f"<option value='__new__'{'' if match else ' selected'}>New client: {e(name)}</option>"
    ]
    for c in clients:
        sel = " selected" if match and c.id == match.id else ""
        n = len(c.grants)
        options.append(
            f"<option value='{e(c.id)}'{sel}>{e(c.name)} ({n} account{'s' if n != 1 else ''})"
            "</option>"
        )
    body = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>hydra-mcp: allow {e(name)}?</title><style>{_STYLE}</style>
<div class=box>
<h1>Allow <b>{e(name)}</b> to use hydra-mcp?</h1>
<p class=muted>After approval you are sent back to <code>{e(host)}</code>. The app will see only
the accounts and tools granted to the client you pick below, and you can change or revoke that
in the admin page at any time.</p>
{f"<p class=err>{e(error)}</p>" if error else ""}
<form method=post action="/oauth/authorize">
<input type=hidden name=request_id value="{e(request_id)}">
<label>Use the access of
<select name=client>{"".join(options)}</select></label>
<p class=muted>A new client starts with no account: give it accounts in the admin page,
Clients.</p>
<label>Admin token
<input name=admin_token type=password autocomplete=current-password required autofocus>
</label>
<p class=muted>Proves this is you. Find it with <code>hydra-mcp admin-token</code> on the
machine running hydra-mcp.</p>
<div class=row><button class=primary name=action value=approve>Allow</button>
<button name=action value=deny formnovalidate>Deny</button></div>
</form></div>"""
    return HTMLResponse(body, status, headers=_HEADERS)

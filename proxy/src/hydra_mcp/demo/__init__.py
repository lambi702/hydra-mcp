"""Demo mode: a fake MCP provider served by the proxy itself, to try hydra-mcp in one minute.

`hydra-mcp demo` starts the proxy with this provider mounted under `/demo`. It is a small issue
tracker ("Demo Tracker") with three workspaces (acme, globex, initech), and it behaves like a
real remote MCP server, so the proxy talks to it through exactly the code paths it uses for
Atlassian or Linear:

    proxy                                   demo provider (same process)
    -----                                   ----------------------------
    GET  PRM, AS metadata  --------------->  /.well-known/oauth-protected-resource/demo/mcp
                                             /.well-known/oauth-authorization-server/demo
    POST dynamic client registration ----->  /demo/register
    browser: authorize (pick a workspace) ->  /demo/authorize   (the "login page")
    POST code + PKCE verifier ------------>  /demo/token        (checks S256, issues tokens)
    POST JSON-RPC with Bearer token ------>  /demo/mcp          (401 without a valid token)

Nothing about the proxy is special-cased: the provider is only *another upstream* whose URL
happens to be on the proxy's own origin. The browser reaches it over HTTP like any login page;
the proxy's own server-side calls to it are routed in process (`LoopbackTransport`), so demo
mode also works when the proxy cannot reach its own public URL (a container, a tunnel).

Everything lives in memory and in a throwaway data directory: nothing here is persisted, and
the demo routes exist only when demo mode is on.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from hydra_mcp.models import Client, Grant, GrantMode, Upstream

if TYPE_CHECKING:
    from hydra_mcp.app import Services

PREFIX = "/demo"
MCP_PATH = f"{PREFIX}/mcp"
PRM_PATH = f"/.well-known/oauth-protected-resource{MCP_PATH}"
AS_META_PATH = f"/.well-known/oauth-authorization-server{PREFIX}"
SCOPES = ["issues.read", "issues.write"]
TOKEN_TTL_S = 3600
CODE_TTL_S = 300

UPSTREAM_ID = "demo"
UPSTREAM_NAME = "Demo Tracker"
DEMO_CLIENT_ID = "claude-code-demo"


# -- the fake tracker's data -------------------------------------------------------------------
@dataclass
class Workspace:
    slug: str
    company: str
    user: str
    email: str
    prefix: str
    issues: list[dict] = field(default_factory=list)


def _issues(prefix: str, rows: list[tuple[str, str, str]]) -> list[dict]:
    return [
        {"key": f"{prefix}-{i}", "title": title, "status": status, "assignee": who, "comments": []}
        for i, (title, status, who) in enumerate(rows, start=101)
    ]


def default_workspaces() -> dict[str, Workspace]:
    """Three tenants with distinct data, so it is obvious which account a call went to."""
    ws = [
        Workspace(
            "acme",
            "Acme Corp",
            "Alice Martin",
            "alice@acme.example",
            "ACME",
            _issues(
                "ACME",
                [
                    ("Checkout fails with two coupons", "open", "alice"),
                    ("Migrate invoices to the new PDF engine", "in progress", "alice"),
                    ("Dark mode for the customer portal", "open", "sam"),
                    ("Rotate the payment provider API key", "done", "alice"),
                ],
            ),
        ),
        Workspace(
            "globex",
            "Globex",
            "Bob Dupont",
            "bob@globex.example",
            "GLX",
            _issues(
                "GLX",
                [
                    ("Quarterly report export times out", "open", "bob"),
                    ("SSO login loops on Safari", "in progress", "nina"),
                    ("Add CSV import for contacts", "open", "bob"),
                ],
            ),
        ),
        Workspace(
            "initech",
            "Initech",
            "Priya Shah",
            "priya@initech.example",
            "INI",
            _issues(
                "INI",
                [
                    ("Weekly status report template missing", "open", "priya"),
                    ("Printer on floor 3 jams on duplex", "open", "omar"),
                ],
            ),
        ),
    ]
    return {w.slug: w for w in ws}


TOOLS = [
    {
        "name": "whoami",
        "description": "Who this token belongs to: the user and the workspace.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "search_issues",
        "description": "Search issues in the workspace by text and/or status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to look for in titles"},
                "status": {"type": "string", "enum": ["open", "in progress", "done"]},
            },
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_issue",
        "description": "Read one issue by key, e.g. ACME-101.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "create_issue",
        "description": "Create an issue in the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "assignee": {"type": "string"}},
            "required": ["title"],
        },
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "add_comment",
        "description": "Add a comment to an issue.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "text": {"type": "string"}},
            "required": ["key", "text"],
        },
        "annotations": {"readOnlyHint": False},
    },
]


# -- the provider ----------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _s256(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


def _unsigned_jwt(claims: dict) -> str:
    """An id_token the proxy reads only to label the account (it never trusts it for auth)."""
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return f"{header}.{_b64url(json.dumps(claims).encode())}."


class DemoProvider:
    """OAuth 2.1 authorization server + MCP server for the fake tracker, all in memory."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.workspaces = default_workspaces()
        self.clients: dict[str, list[str]] = {}  # client_id -> redirect_uris
        self.codes: dict[str, dict] = {}
        self.access: dict[str, tuple[str, float]] = {}  # token -> (workspace, expires_at)
        self.refresh: dict[str, str] = {}  # refresh token -> workspace

    # URLs
    @property
    def issuer(self) -> str:
        return self.base_url + PREFIX

    @property
    def mcp_url(self) -> str:
        return self.base_url + MCP_PATH

    def owns(self, url: httpx.URL) -> bool:
        """Is this server-side request for the demo provider? (see LoopbackTransport)"""
        base = urlsplit(self.base_url)
        if (url.scheme, url.netloc.decode()) != (base.scheme, base.netloc):
            return False
        return url.path.startswith(PREFIX + "/") or url.path in (PRM_PATH, AS_META_PATH)

    def routes(self) -> list[Route]:
        return [
            Route(PRM_PATH, self.prm, methods=["GET"]),
            Route(AS_META_PATH, self.as_metadata, methods=["GET"]),
            Route(f"{PREFIX}/register", self.register, methods=["POST"]),
            Route(f"{PREFIX}/authorize", self.authorize, methods=["GET", "POST"]),
            Route(f"{PREFIX}/token", self.token, methods=["POST"]),
            Route(MCP_PATH, self.mcp, methods=["GET", "POST", "DELETE"]),
        ]

    def asgi_app(self) -> Starlette:
        return Starlette(routes=self.routes())

    # discovery
    async def prm(self, request: Request) -> Response:
        return JSONResponse(
            {
                "resource": self.mcp_url,
                "authorization_servers": [self.issuer],
                "scopes_supported": SCOPES,
                "resource_name": UPSTREAM_NAME,
            }
        )

    async def as_metadata(self, request: Request) -> Response:
        return JSONResponse(
            {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "registration_endpoint": f"{self.issuer}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": SCOPES,
            }
        )

    async def register(self, request: Request) -> Response:
        body = await request.json()
        uris = body.get("redirect_uris") or []
        if not uris or not all(isinstance(u, str) for u in uris):
            return JSONResponse({"error": "invalid_redirect_uri"}, 400)
        client_id = "demo-client-" + secrets.token_hex(6)
        self.clients[client_id] = uris
        return JSONResponse(
            {
                "client_id": client_id,
                "client_name": body.get("client_name", ""),
                "redirect_uris": uris,
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
            201,
        )

    # authorization: a "login page" where you pick the workspace you are signing in to
    def _check_authorize(self, p: dict[str, str]) -> str | None:
        if p.get("response_type") != "code":
            return "response_type must be 'code'"
        if p.get("client_id") not in self.clients:
            return "unknown client_id (register first)"
        if p.get("redirect_uri") not in self.clients[p["client_id"]]:
            return "redirect_uri was not registered for this client"
        if p.get("code_challenge_method") != "S256" or not p.get("code_challenge"):
            return "PKCE with S256 is required"
        return None

    def approve(self, params: dict[str, str], workspace: str) -> str:
        """Issue an authorization code for `workspace`; return the redirect URL with it."""
        error = self._check_authorize(params)
        if error:
            raise ValueError(error)
        if workspace not in self.workspaces:
            raise ValueError(f"unknown workspace {workspace!r}")
        code = secrets.token_urlsafe(24)
        self.codes[code] = {
            "client_id": params["client_id"],
            "redirect_uri": params["redirect_uri"],
            "challenge": params["code_challenge"],
            "workspace": workspace,
            "expires_at": time.time() + CODE_TTL_S,
        }
        query = {"code": code, "iss": self.issuer}
        if params.get("state"):
            query["state"] = params["state"]
        sep = "&" if "?" in params["redirect_uri"] else "?"
        return f"{params['redirect_uri']}{sep}{urlencode(query)}"

    async def authorize(self, request: Request) -> Response:
        if request.method == "POST":
            form = await _form(request)
            workspace = str(form.pop("workspace", ""))
            if form.pop("decision", "") != "allow":
                url = str(form.get("redirect_uri", ""))
                if form.get("client_id") in self.clients and url in self.clients[form["client_id"]]:
                    q = {"error": "access_denied", "state": form.get("state", "")}
                    return RedirectResponse(f"{url}?{urlencode(q)}", 303)
                return HTMLResponse("Cancelled.", 400)
            try:
                return RedirectResponse(
                    self.approve({k: str(v) for k, v in form.items()}, workspace), 303
                )
            except ValueError as exc:
                return _login_page_error(str(exc))
        params = dict(request.query_params)
        error = self._check_authorize(params)
        if error:
            return _login_page_error(error)
        return HTMLResponse(_login_page(params, self.workspaces))

    # tokens
    def _issue(self, workspace: str) -> dict:
        ws = self.workspaces[workspace]
        access = "demo-at-" + secrets.token_urlsafe(24)
        refresh = "demo-rt-" + secrets.token_urlsafe(24)
        self.access[access] = (workspace, time.time() + TOKEN_TTL_S)
        self.refresh[refresh] = workspace
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": TOKEN_TTL_S,
            "refresh_token": refresh,
            "scope": " ".join(SCOPES),
            "id_token": _unsigned_jwt(
                {"iss": self.issuer, "sub": f"{workspace}:{ws.user}", "email": ws.email}
            ),
        }

    async def token(self, request: Request) -> Response:
        form = await _form(request)
        grant = form.get("grant_type")
        if grant == "authorization_code":
            row = self.codes.pop(str(form.get("code", "")), None)  # single use
            if row is None or row["expires_at"] < time.time():
                return _oauth_error("invalid_grant", "unknown or expired code")
            if form.get("client_id") != row["client_id"]:
                return _oauth_error("invalid_client", "code was issued to another client")
            if form.get("redirect_uri") != row["redirect_uri"]:
                return _oauth_error("invalid_grant", "redirect_uri mismatch")
            if _s256(str(form.get("code_verifier", ""))) != row["challenge"]:
                return _oauth_error("invalid_grant", "PKCE verification failed")
            return JSONResponse(self._issue(row["workspace"]))
        if grant == "refresh_token":
            workspace = self.refresh.pop(str(form.get("refresh_token", "")), None)  # rotated
            if workspace is None:
                return _oauth_error("invalid_grant", "unknown refresh token")
            return JSONResponse(self._issue(workspace))
        return _oauth_error("unsupported_grant_type", str(grant))

    def _workspace_for(self, request: Request) -> Workspace | None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        found = self.access.get(token)
        if found is None or found[1] < time.time():
            return None
        return self.workspaces[found[0]]

    # the MCP server (Streamable HTTP, JSON responses, no session)
    async def mcp(self, request: Request) -> Response:
        ws = self._workspace_for(request)
        if ws is None:
            return Response(
                status_code=401,
                headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{self.base_url}{PRM_PATH}", '
                    f'scope="{" ".join(SCOPES)}"'
                },
            )
        if request.method != "POST":
            return Response(status_code=405, headers={"Allow": "POST"})
        msg = await request.json()
        if "id" not in msg:
            return Response(status_code=202)
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-11-25"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "demo-tracker", "version": "1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = _call_tool(ws, params.get("name", ""), params.get("arguments") or {})
        else:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": method}}
            )
        return JSONResponse({"jsonrpc": "2.0", "id": msg["id"], "result": result})


def _call_tool(ws: Workspace, name: str, args: dict) -> dict:
    def ok(data: dict | list) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    def err(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}], "isError": True}

    by_key = {i["key"]: i for i in ws.issues}
    if name == "whoami":
        return ok({"user": ws.user, "email": ws.email, "workspace": ws.company})
    if name == "search_issues":
        q = str(args.get("query", "")).lower()
        status = args.get("status")
        hits = [
            {k: i[k] for k in ("key", "title", "status", "assignee")}
            for i in ws.issues
            if q in i["title"].lower() and (not status or i["status"] == status)
        ]
        return ok({"workspace": ws.company, "issues": hits})
    if name == "get_issue":
        issue = by_key.get(str(args.get("key", "")).upper())
        return ok(issue) if issue else err(f"No issue {args.get('key')} in {ws.company}.")
    if name == "create_issue":
        title = str(args.get("title", "")).strip()
        if not title:
            return err("title is required")
        key = f"{ws.prefix}-{101 + len(ws.issues)}"
        issue = {
            "key": key,
            "title": title,
            "status": "open",
            "assignee": str(args.get("assignee") or ws.user.split()[0].lower()),
            "comments": [],
        }
        ws.issues.append(issue)
        return ok({"created": key, "workspace": ws.company})
    if name == "add_comment":
        issue = by_key.get(str(args.get("key", "")).upper())
        if issue is None:
            return err(f"No issue {args.get('key')} in {ws.company}.")
        issue["comments"].append({"author": ws.user, "text": str(args.get("text", ""))})
        return ok({"commented": issue["key"], "workspace": ws.company})
    return err(f"unknown tool {name}")


async def _form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded body (no python-multipart dependency for a demo)."""
    body = (await request.body()).decode()
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


def _oauth_error(code: str, description: str) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": description}, 400)


_PAGE_STYLE = """
body{font-family:system-ui,-apple-system,sans-serif;background:#f4f4f6;color:#1c1c22;margin:0}
main{max-width:420px;margin:48px auto;padding:28px;background:#fff;border-radius:14px;
box-shadow:0 1px 3px #0002}
h1{font-size:20px;margin:0 0 4px}p{color:#55555f;font-size:14px;line-height:1.5}
.tag{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.04em;color:#7a4b00;
background:#fff1d6;border-radius:6px;padding:2px 6px;margin-bottom:14px}
button{display:flex;width:100%;align-items:center;gap:12px;text-align:left;padding:12px 14px;
margin:8px 0;border:1px solid #dcdce3;border-radius:10px;background:#fff;cursor:pointer;
font:inherit}
button:hover{border-color:#6b5cff;background:#f7f6ff}
.av{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;color:#fff;
font-weight:700;flex:none}.who{font-size:13px;color:#6b6b75}
.cancel{border:none;background:none;color:#6b6b75;justify-content:center;font-size:13px}
@media (prefers-color-scheme:dark){body{background:#151518;color:#ececf1}
main{background:#1e1e23;box-shadow:none}p,.who,.cancel{color:#a0a0ab}
button{background:#1e1e23;border-color:#34343c;color:inherit}button:hover{background:#26243a}
.tag{background:#3a2a07;color:#ffcf73}}
"""
_COLORS = {"acme": "#d9480f", "globex": "#1971c2", "initech": "#2b8a3e"}


def _login_page(params: dict[str, str], workspaces: dict[str, Workspace]) -> str:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in params.items()
    )
    buttons = "".join(
        f'<button name="workspace" value="{w.slug}" data-workspace="{w.slug}">'
        f'<span class="av" style="background:{_COLORS.get(w.slug, "#555")}">{w.company[0]}</span>'
        f"<span><strong>{html.escape(w.company)}</strong><br>"
        f'<span class="who">{html.escape(w.user)} · {html.escape(w.email)}</span></span></button>'
        for w in workspaces.values()
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · Demo Tracker</title><style>{_PAGE_STYLE}</style>
<main><span class="tag">DEMO PROVIDER</span>
<h1>Sign in to Demo Tracker</h1>
<p>This page stands in for a real provider's login (Atlassian, Google, GitHub…).
Pick the workspace to grant <strong>hydra-mcp</strong> access to.</p>
<form method="post">{hidden}<input type="hidden" name="decision" value="allow">{buttons}</form>
<form method="post">{hidden}<button class="cancel" name="decision" value="deny">Cancel</button>
</form></main></html>"""


def _login_page_error(text: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><title>Demo Tracker</title>"
        f"<style>{_PAGE_STYLE}</style><main><h1>Invalid sign-in request</h1>"
        f"<p>{html.escape(text)}</p></main>",
        400,
    )


# -- wiring into the proxy -------------------------------------------------------------------
class LoopbackTransport(httpx.AsyncBaseTransport):
    """Sends the proxy's own requests to the demo provider in process; everything else goes out.

    Without it the proxy would call its own public URL over the network, which fails whenever
    that URL is only reachable from the browser (Docker port mapping, a tunnel).
    """

    def __init__(self, provider: DemoProvider, inner: httpx.AsyncBaseTransport | None = None):
        self.provider = provider
        self.local = httpx.ASGITransport(app=provider.asgi_app())
        self.inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.provider.owns(request.url):
            return await self.local.handle_async_request(request)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


@dataclass
class DemoSeed:
    client_key: str
    accounts: list[str]


async def seed(services: Services, provider: DemoProvider) -> DemoSeed:
    """Connect two workspaces through the real OAuth flow, and create a client for them.

    The login is "clicked" in code (provider.approve) but everything else is the production path:
    discovery, dynamic registration, PKCE, the token exchange and the encrypted vault.
    """
    from hydra_mcp.broker.endpoint import KEY_PREFIX, hash_key

    store, oauth = services.store, services.oauth
    upstream = await store.put_upstream(
        Upstream(id=UPSTREAM_ID, name=UPSTREAM_NAME, url=provider.mcp_url)
    )
    accounts = []
    for workspace in ("acme", "globex"):
        authorize_url = await oauth.start_link(None, upstream)
        params = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        callback = parse_qs(urlsplit(provider.approve(params, workspace)).query)
        result = await oauth.finish_link(callback["state"][0], callback["code"][0])
        accounts.append(result.account)
    acme, globex = accounts
    await store.put_client(
        Client(
            id=DEMO_CLIENT_ID,
            name="Claude Code (demo)",
            grants=[
                Grant(account_id=acme.id, mode=GrantMode.WRITE),
                Grant(account_id=globex.id, mode=GrantMode.READ),
            ],
        )
    )
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    await store.set_client_key_hash(DEMO_CLIENT_ID, hash_key(key))
    return DemoSeed(client_key=key, accounts=[a.alias for a in accounts])

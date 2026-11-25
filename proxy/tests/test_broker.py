"""Broker mode end to end, in-process: a fake upstream (MCP server + OAuth AS) and the proxy.

The fake is strict where the real world is strict, so the tests prove the proxy really does:
DCR, PKCE S256 (the token endpoint recomputes the challenge), RFC 8707 resource on both the
authorize and token requests, per-account tokens (the MCP server answers as the token's user),
refresh, upstream sessions (unknown session -> 404), and SSE responses.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from hydra_mcp.app import create_app
from hydra_mcp.models import Account, Client, Grant, GrantMode, Upstream
from hydra_mcp.settings import Settings
from hydra_mcp.store import Store

MCP_URL = "https://mail.test/mcp"
ISSUER = "https://auth.test"
ADMIN = "test-admin-token"
H = {"Authorization": f"Bearer {ADMIN}"}


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


class FakeProvider:
    """One upstream service: its MCP server and its authorization server, with inspectable state."""

    def __init__(self) -> None:
        self.dcr = True
        self.id_tokens = True  # Atlassian-like providers send none
        self.expires_in = 3600
        self.clients: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}  # code -> {challenge, user, resource, client_id}
        self.access: dict[str, str] = {}  # access token -> user
        self.refresh: dict[str, str] = {}  # refresh token -> user
        self.sessions: dict[str, str] = {}  # Mcp-Session-Id -> user
        self.refresh_count = 0
        self.slack_shape = False  # answer like Slack: ok flag, user token under authed_user

    # -- the "browser": what the user does at the AS login page ------------------------------
    def approve(self, authorize_url: str, user: str) -> dict[str, str]:
        q = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        assert q["client_id"] in self.clients
        assert q["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(8)
        self.codes[code] = {
            "challenge": q["code_challenge"],
            "user": user,
            "resource": q["resource"],
            "client_id": q["client_id"],
        }
        return {"code": code, "state": q["state"]}

    def _issue(self, user: str) -> dict:
        at, rt = f"at-{secrets.token_hex(4)}", f"rt-{secrets.token_hex(4)}"
        self.access[at] = user
        self.refresh[rt] = user
        tokens = {
            "access_token": at,
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "refresh_token": rt,
        }
        if self.id_tokens:
            tokens["id_token"] = f"{_b64({'alg': 'none'})}.{_b64({'email': user})}."
        if self.slack_shape:
            return {"ok": True, "authed_user": tokens, "team": {"id": "T1", "name": user}}
        return tokens

    # -- endpoints ---------------------------------------------------------------------------
    async def prm(self, request: Request) -> Response:
        return JSONResponse(
            {"resource": MCP_URL, "authorization_servers": [ISSUER], "scopes_supported": ["mail"]}
        )

    async def as_meta(self, request: Request) -> Response:
        meta = {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["mail", "offline_access"],
        }
        if self.dcr:
            meta["registration_endpoint"] = f"{ISSUER}/register"
        return JSONResponse(meta)

    async def register(self, request: Request) -> Response:
        body = await request.json()
        client_id = f"dcr-{len(self.clients) + 1}"
        self.clients[client_id] = body
        return JSONResponse({"client_id": client_id, **body}, 201)

    async def token(self, request: Request) -> Response:
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        if form.get("resource") != MCP_URL:
            return JSONResponse({"error": "invalid_target"}, 400)
        if form["grant_type"] == "authorization_code":
            grant = self.codes.pop(form["code"], None)
            if grant is None or grant["client_id"] != form.get("client_id"):
                return JSONResponse({"error": "invalid_grant"}, 400)
            digest = hashlib.sha256(form["code_verifier"].encode()).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != grant["challenge"]:
                return JSONResponse({"error": "invalid_grant", "error_description": "PKCE"}, 400)
            return JSONResponse(self._issue(grant["user"]))
        if form["grant_type"] == "refresh_token":
            user = self.refresh.pop(form["refresh_token"], None)
            if user is None:
                return JSONResponse({"error": "invalid_grant"}, 400)
            self.refresh_count += 1
            return JSONResponse(self._issue(user))
        return JSONResponse({"error": "unsupported_grant_type"}, 400)

    async def mcp(self, request: Request) -> Response:
        auth = request.headers.get("authorization", "").removeprefix("Bearer ")
        user = self.access.get(auth)
        if user is None:
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        msg = await request.json()
        method = msg.get("method")
        if method == "initialize":
            sid = secrets.token_hex(4)
            self.sessions[sid] = user
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
            return JSONResponse(
                {"jsonrpc": "2.0", "id": msg["id"], "result": result},
                headers={"Mcp-Session-Id": sid},
            )
        sid = request.headers.get("mcp-session-id")
        if sid not in self.sessions:
            return Response(status_code=404)
        assert self.sessions[sid] == user, "a session must never be reused across accounts"
        if "id" not in msg:
            return Response(status_code=202)
        if method == "tools/list":
            tools = [
                {
                    "name": "search",
                    "description": "Search mail",
                    "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
                    "annotations": {"readOnlyHint": True},
                },
                {"name": "send", "description": "Send mail", "inputSchema": {"type": "object"}},
            ]
            return JSONResponse({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}})
        if method == "tools/call":
            params = msg["params"]
            text = f"{params['name']} as {user} with {json.dumps(params['arguments'])}"
            reply = {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {"content": [{"type": "text", "text": text}]},
            }
            progress = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}

            async def events():
                yield f"event: message\ndata: {json.dumps(progress)}\n\n".encode()
                yield f"event: message\ndata: {json.dumps(reply)}\n\n".encode()

            return StreamingResponse(events(), media_type="text/event-stream")
        return JSONResponse({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601}})

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/mcp", self.mcp, methods=["POST"]),
                Route("/.well-known/oauth-protected-resource/mcp", self.prm),
                Route("/.well-known/oauth-authorization-server", self.as_meta),
                Route("/register", self.register, methods=["POST"]),
                Route("/token", self.token, methods=["POST"]),
            ]
        )


@pytest.fixture
async def env(tmp_path):
    provider = FakeProvider()
    settings = Settings(
        public_url="http://proxy.test", data_dir=tmp_path, admin_token=ADMIN, admin_dist=None
    )
    store = Store(":memory:")
    await store.open()
    await store.put_upstream(Upstream(id="mail", name="Mail", url=MCP_URL))
    await store.put_account(Account(id="mail-work", upstream_id="mail", alias="work"))
    await store.put_account(Account(id="mail-perso", upstream_id="mail", alias="perso"))
    await store.put_client(
        Client(
            id="cursor",
            name="Cursor",
            grants=[
                Grant(account_id="mail-work", tools="*", mode=GrantMode.WRITE),
                Grant(account_id="mail-perso", tools="*", mode=GrantMode.READ),
            ],
        )
    )
    upstream_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=provider.app()))
    app = create_app(settings, store=store, http=upstream_http)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://proxy.test"
    ) as proxy:
        yield proxy, provider
    await upstream_http.aclose()
    await store.close()


async def connect(proxy: httpx.AsyncClient, provider: FakeProvider, account: str, user: str):
    r = await proxy.post(f"/admin/api/accounts/{account}/link", headers=H)
    assert r.status_code == 200, r.text
    callback = provider.approve(r.json()["authorize_url"], user)
    return await proxy.get("/oauth/callback", params=callback)


async def client_key(proxy: httpx.AsyncClient) -> dict[str, str]:
    r = await proxy.post("/admin/api/clients/cursor/key", headers=H)
    assert r.status_code == 201
    assert r.json()["endpoint"] == "http://proxy.test/mcp"
    return {"Authorization": f"Bearer {r.json()['key']}"}


async def rpc(proxy, headers, method, params=None, msg_id=1):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    r = await proxy.post("/mcp", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def test_authorize_url_carries_pkce_resource_and_scopes(env):
    proxy, provider = env
    r = await proxy.post("/admin/api/accounts/mail-work/link", headers=H)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.json()["authorize_url"]).query).items()}
    assert q["resource"] == MCP_URL
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["scope"] == "mail offline_access"
    assert q["redirect_uri"] == "http://proxy.test/oauth/callback"
    # DCR happened once, as a public client with our callback.
    (reg,) = provider.clients.values()
    assert reg["redirect_uris"] == ["http://proxy.test/oauth/callback"]
    assert reg["token_endpoint_auth_method"] == "none"
    # A second link reuses the registered client.
    await proxy.post("/admin/api/accounts/mail-perso/link", headers=H)
    assert len(provider.clients) == 1


async def test_connect_stores_identity_and_state_is_single_use(env):
    proxy, provider = env
    r = await connect(proxy, provider, "mail-work", "alice@work.test")
    assert r.status_code == 303
    assert r.headers["location"] == "http://proxy.test/admin/?connected=mail-work&new=0"
    status = (await proxy.get("/admin/api/accounts-status", headers=H)).json()
    assert status["mail-work"]["identity"] == "alice@work.test"
    assert "mail-perso" not in status

    # Replaying a callback (same state) is refused.
    r = await proxy.post("/admin/api/accounts/mail-perso/link", headers=H)
    cb = provider.approve(r.json()["authorize_url"], "bob@home.test")
    assert (await proxy.get("/oauth/callback", params=cb)).status_code == 303
    replay = await proxy.get("/oauth/callback", params=cb)
    assert replay.status_code == 400 and "invalid or expired" in replay.text


async def test_callback_with_tampered_challenge_fails_pkce(env):
    proxy, provider = env
    r = await proxy.post("/admin/api/accounts/mail-work/link", headers=H)
    cb = provider.approve(r.json()["authorize_url"], "alice@work.test")
    provider.codes[cb["code"]]["challenge"] = "x" * 43  # an attacker's code, not ours
    bad = await proxy.get("/oauth/callback", params=cb)
    assert bad.status_code == 400 and "PKCE" in bad.text


async def test_mcp_requires_a_client_key_and_a_loopback_origin(env):
    proxy, _ = env
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    r = await proxy.post("/mcp", json=ping)
    assert r.status_code == 401 and "WWW-Authenticate" in r.headers
    r = await proxy.post("/mcp", json=ping, headers={"Authorization": "Bearer hmcp_wrong"})
    assert r.status_code == 401
    headers = await client_key(proxy)
    evil = {**headers, "Origin": "https://evil.example"}
    assert (await proxy.post("/mcp", json=ping, headers=evil)).status_code == 403
    assert (await proxy.post("/mcp", json=ping, headers=headers)).status_code == 200
    # Revoking the key locks the client out.
    await proxy.delete("/admin/api/clients/cursor/key", headers=H)
    assert (await proxy.post("/mcp", json=ping, headers=headers)).status_code == 401


async def test_tools_are_aggregated_with_an_account_argument_per_grant(env):
    proxy, provider = env
    headers = await client_key(proxy)
    # Nothing connected yet: no tools, and no error.
    assert (await rpc(proxy, headers, "tools/list"))["tools"] == []

    await connect(proxy, provider, "mail-work", "alice@work.test")
    await connect(proxy, provider, "mail-perso", "bob@home.test")
    init = await rpc(proxy, headers, "initialize", {"protocolVersion": "2025-06-18"})
    assert init["protocolVersion"] == "2025-06-18"

    tools = {t["name"]: t for t in (await rpc(proxy, headers, "tools/list"))["tools"]}
    assert sorted(tools) == ["mail__search", "mail__send"]
    search = tools["mail__search"]["inputSchema"]
    assert search["properties"]["account"]["enum"] == ["perso", "work"]
    assert search["required"][0] == "account"
    assert "q" in search["properties"]
    # perso is granted read-only, and send is not annotated read-only: only work may send.
    assert tools["mail__send"]["inputSchema"]["properties"]["account"]["enum"] == ["work"]
    assert "alice@work.test" in tools["mail__send"]["description"]


async def test_calls_are_routed_with_the_chosen_accounts_token(env):
    proxy, provider = env
    headers = await client_key(proxy)
    await connect(proxy, provider, "mail-work", "alice@work.test")
    await connect(proxy, provider, "mail-perso", "bob@home.test")

    for alias, user in (("work", "alice@work.test"), ("perso", "bob@home.test")):
        res = await rpc(
            proxy,
            headers,
            "tools/call",
            {"name": "mail__search", "arguments": {"account": alias, "q": "invoice"}},
        )
        assert not res.get("isError"), res
        # The account argument is stripped before the upstream sees it.
        assert res["content"][0]["text"] == f'search as {user} with {{"q": "invoice"}}'

    # Read-only grant: the call is refused even though the client asked by name.
    res = await rpc(
        proxy, headers, "tools/call", {"name": "mail__send", "arguments": {"account": "perso"}}
    )
    assert res["isError"] and "must be one of: work" in res["content"][0]["text"]
    # Unknown alias and unknown tool are errors too, never a guess.
    res = await rpc(proxy, headers, "tools/call", {"name": "mail__search", "arguments": {}})
    assert res["isError"]
    res = await rpc(proxy, headers, "tools/call", {"name": "mail__drop", "arguments": {}})
    assert res["isError"] and "not granted" in res["content"][0]["text"]


async def test_expired_session_and_expiring_token_are_handled(env):
    proxy, provider = env
    provider.expires_in = 30  # inside the 60 s refresh margin: every use refreshes
    headers = await client_key(proxy)
    await connect(proxy, provider, "mail-work", "alice@work.test")
    call = {"name": "mail__search", "arguments": {"account": "work"}}

    res = await rpc(proxy, headers, "tools/call", call)
    assert "alice@work.test" in res["content"][0]["text"]
    assert provider.refresh_count >= 1

    provider.sessions.clear()  # upstream restarted: our session id now gets 404
    res = await rpc(proxy, headers, "tools/call", call)
    assert not res.get("isError"), res


async def test_unlink_and_upstream_revocation(env):
    proxy, provider = env
    headers = await client_key(proxy)
    await connect(proxy, provider, "mail-work", "alice@work.test")
    call = {"name": "mail__search", "arguments": {"account": "work"}}
    assert not (await rpc(proxy, headers, "tools/call", call)).get("isError")

    provider.access.clear()  # revoked at the provider
    res = await rpc(proxy, headers, "tools/call", call)
    assert res["isError"] and "Reconnect" in res["content"][0]["text"]

    assert (await proxy.delete("/admin/api/accounts/mail-work/link", headers=H)).status_code == 204
    assert (await rpc(proxy, headers, "tools/list"))["tools"] == []


async def test_provider_without_dcr_needs_a_manual_client(env):
    proxy, provider = env
    provider.dcr = False
    r = await proxy.post("/admin/api/accounts/mail-work/link", headers=H)
    assert r.status_code == 409 and r.json()["needs_manual_client"] is True
    assert "http://proxy.test/oauth/callback" in r.json()["error"]

    provider.clients["manual-id"] = {}
    r = await proxy.put(
        "/admin/api/upstreams/mail/oauth",
        headers=H,
        json={"client_id": "manual-id", "client_secret": "s3cret"},
    )
    assert r.status_code == 200
    info = r.json()
    assert info["registration"] == "manual" and info["has_secret"] is True
    assert "s3cret" not in r.text
    r = await connect(proxy, provider, "mail-work", "alice@work.test")
    assert r.status_code == 303, r.text


async def test_needs_manual_client_comes_with_a_setup_guide(env):
    proxy, provider = env
    provider.dcr = False
    r = await proxy.post("/admin/api/accounts/mail-work/link", headers=H)
    body = r.json()
    assert body["upstream_id"] == "mail"
    guide = body["guide"]
    assert guide["redirect_uri"] == "http://proxy.test/oauth/callback"
    values = [f["value"] for step in guide["steps"] for f in step.get("fields", [])]
    assert guide["redirect_uri"] in values
    info = (await proxy.get("/admin/api/upstreams/mail/oauth", headers=H)).json()
    assert info["registered"] is False and info["guide"] == guide


def test_google_guide_links_the_right_apis():
    from hydra_mcp.broker.setup import catalog_entry, setup_guide

    gmail = Upstream(id="gmail", name="Gmail", url="https://gmailmcp.googleapis.com/mcp/v1")
    assert catalog_entry(gmail).id == "gmail"
    guide = setup_guide(gmail, "http://127.0.0.1:8765/oauth/callback")
    assert guide["provider"] == "Google" and guide["client_type"].startswith("Web application")
    text = " ".join(s["text"] for s in guide["steps"])
    assert "AI-powered agent" in text and "gmail.readonly" in text
    links = [s.get("link") or "" for s in guide["steps"]]
    assert any(
        link.endswith("enableapi?apiid=gmail.googleapis.com,gmailmcp.googleapis.com")
        for link in links
    )
    cal = Upstream(id="cal", name="Cal", url="https://calendarmcp.googleapis.com/mcp/v1")
    cal_links = " ".join(s.get("link") or "" for s in setup_guide(cal, "x")["steps"])
    assert "calendar-json.googleapis.com" in cal_links


async def connect_new(proxy, provider, user: str, **body) -> httpx.Response:
    r = await proxy.post("/admin/api/connect", headers=H, json=body)
    assert r.status_code == 200, r.text
    return await proxy.get(
        "/oauth/callback", params=provider.approve(r.json()["authorize_url"], user)
    )


async def test_connect_creates_the_account_only_after_login(env):
    proxy, provider = env
    accounts = lambda: proxy.get("/admin/api/accounts", headers=H)  # noqa: E731
    before = {a["id"] for a in (await accounts()).json()}

    # Started, never finished (user closed the tab): nothing appears.
    r = await proxy.post("/admin/api/connect", headers=H, json={"upstream_id": "mail"})
    assert r.status_code == 200 and r.json()["upstream_id"] == "mail"
    assert {a["id"] for a in (await accounts()).json()} == before

    # A login at a company domain: named after the domain, and the admin page asks to rename.
    r = await connect_new(proxy, provider, "carol@acme.test", upstream_id="mail")
    assert r.status_code == 303
    assert r.headers["location"] == "http://proxy.test/admin/?connected=mail-acme&new=1"
    new = {a["id"]: a for a in (await accounts()).json()}["mail-acme"]
    assert new["alias"] == "acme" and new["identity"] == "carol@acme.test"
    status = (await proxy.get("/admin/api/accounts-status", headers=H)).json()
    assert status["mail-acme"]["identity"] == "carol@acme.test"

    # The same person again: a reconnect of that account, not a duplicate.
    r = await connect_new(proxy, provider, "carol@acme.test", upstream_id="mail")
    assert r.headers["location"] == "http://proxy.test/admin/?connected=mail-acme&new=0"
    assert len((await accounts()).json()) == len(before) + 1


async def test_connect_by_url_reuses_the_upstream(env):
    proxy, provider = env
    r = await connect_new(proxy, provider, "dan@gmail.com", name="My Mail", url=MCP_URL + "/")
    assert r.headers["location"].endswith("new=1")
    ups = (await proxy.get("/admin/api/upstreams", headers=H)).json()
    assert [u["id"] for u in ups] == ["mail"], "same URL must not create a second server"
    accounts = (await proxy.get("/admin/api/accounts", headers=H)).json()
    assert {"mail-dan"} <= {a["id"] for a in accounts}
    # New server by URL: a slug from its name.
    r = await proxy.post(
        "/admin/api/connect", headers=H, json={"name": "Other Mail", "url": "https://mail.test/x"}
    )
    ids = {u["id"] for u in (await proxy.get("/admin/api/upstreams", headers=H)).json()}
    assert "other-mail" in ids


def test_suggest_alias():
    from hydra_mcp.broker.oauth import suggest_alias

    assert suggest_alias("bob@acme.com", 1) == "acme"
    assert suggest_alias("Jane.D@gmail.com", 1) == "jane-d"
    assert suggest_alias("", 3) == "account3"


async def test_identity_probe_names_accounts_without_id_token(env, monkeypatch):
    """Atlassian-like: no id_token; the upstream's own tool tells which site this login is."""
    from hydra_mcp.broker import identity

    proxy, provider = env
    provider.id_tokens = False
    # Our fake's tools/call answers "<tool> as <user> with {}": read the user's domain as "site".
    monkeypatch.setitem(
        identity.PROBES,
        "mail.test",
        ("whoami", lambda r: r["content"][0]["text"].split(" as ")[1].split("@")[1].split()[0]),
    )
    r = await connect_new(proxy, provider, "erin@site-one.test", upstream_id="mail")
    assert r.headers["location"] == "http://proxy.test/admin/?connected=mail-site-one&new=1"
    # Same site again: a reconnect, not a duplicate.
    r = await connect_new(proxy, provider, "frank@site-one.test", upstream_id="mail")
    assert r.headers["location"] == "http://proxy.test/admin/?connected=mail-site-one&new=0"
    # Backfill for an account connected before probes existed.
    acc = {a["id"]: a for a in (await proxy.get("/admin/api/accounts", headers=H)).json()}
    await proxy.put("/admin/api/accounts", headers=H, json={**acc["mail-site-one"], "identity": ""})
    r = await proxy.post("/admin/api/accounts/mail-site-one/identity", headers=H)
    assert r.json() == {"identity": "site-one.test", "changed": True}


def test_atlassian_site_reader():
    from hydra_mcp.broker.identity import _atlassian_sites
    from hydra_mcp.broker.oauth import suggest_alias

    text = json.dumps(
        {"data": {"resources": [{"cloudId": "x", "url": "https://globex.atlassian.net"}]}}
    )
    assert _atlassian_sites({"content": [{"type": "text", "text": text}]}) == "globex.atlassian.net"
    assert suggest_alias("globex.atlassian.net", 1) == "globex"


def test_github_guide_fills_in_the_callback_and_offers_a_token():
    from hydra_mcp.broker.setup import setup_guide

    gh = Upstream(id="github", name="GitHub", url="https://api.githubcopilot.com/mcp/")
    guide = setup_guide(gh, "http://127.0.0.1:8765/oauth/callback")
    assert guide["provider"] == "GitHub" and guide["client_type"] == "OAuth App"
    assert guide["steps"][0]["link"] == "https://github.com/settings/applications/new"
    fields = {f["label"]: f["value"] for s in guide["steps"] for f in s.get("fields", [])}
    assert fields["Redirect URI"] == "http://127.0.0.1:8765/oauth/callback"
    assert fields["Homepage URL"] == "http://127.0.0.1:8765"
    assert guide["token"]["create_url"].startswith("https://github.com/settings/")


def test_every_library_entry_has_a_guide():
    from hydra_mcp.catalog import AuthKind, load_catalog

    for c in load_catalog().connectors:
        assert c.guide and c.guide.summary and c.guide.links, c.id
        assert c.guide.accounts, f"{c.id}: say how several accounts are told apart"
        if c.auth == AuthKind.OAUTH_PREREGISTERED and c.vendor != "Google":
            assert c.guide.client, f"{c.id}: needs its own OAuth client steps"


def test_github_login_reader():
    from hydra_mcp.broker.identity import _github_login

    text = json.dumps({"login": "octocat", "id": 1})
    assert _github_login({"content": [{"type": "text", "text": text}]}) == "octocat"
    assert _github_login({"content": []}) == ""


async def test_connect_with_a_pasted_token(env, monkeypatch):
    from hydra_mcp.broker import identity

    proxy, provider = env
    provider.access["pat-123"] = "gina@pat.test"  # a token made at the provider, no OAuth
    monkeypatch.setitem(
        identity.PROBES,
        "mail.test",
        ("whoami", lambda r: r["content"][0]["text"].split(" as ")[1].split()[0]),
    )
    bad = await proxy.post(
        "/admin/api/connect-token", headers=H, json={"upstream_id": "mail", "token": "nope"}
    )
    assert bad.status_code == 400 and "refused this token" in bad.json()["error"]
    accounts = {a["id"] for a in (await proxy.get("/admin/api/accounts", headers=H)).json()}
    assert "mail-pat" not in accounts, "a rejected token must not create an account"

    r = await proxy.post(
        "/admin/api/connect-token",
        headers=H,
        json={"upstream_id": "mail", "token": "Bearer pat-123"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["account"]["identity"] == "gina@pat.test"
    account_id = body["account"]["id"]
    status = (await proxy.get("/admin/api/accounts-status", headers=H)).json()
    assert status[account_id]["expires_at"] is None

    # The token is used for calls through the aggregated endpoint.
    await proxy.put(
        "/admin/api/clients",
        headers=H,
        json={
            "id": "cursor",
            "name": "Cursor",
            "grants": [{"account_id": account_id, "tools": "*", "mode": "write"}],
        },
    )
    headers = await client_key(proxy)
    await rpc(
        proxy,
        headers,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    )
    out = await rpc(
        proxy,
        headers,
        "tools/call",
        {"name": "mail__search", "arguments": {"account": "pat", "q": "x"}},
    )
    assert "as gina@pat.test" in out["content"][0]["text"]

    # Replacing the token of that account (e.g. it expired).
    provider.access["pat-456"] = "gina@pat.test"
    r = await proxy.post(
        "/admin/api/connect-token",
        headers=H,
        json={"account_id": account_id, "token": "pat-456"},
    )
    assert r.json()["created"] is False and r.json()["account"]["id"] == account_id


def test_connector_docs_are_up_to_date():
    from pathlib import Path

    from hydra_mcp.catalog.docs import render

    doc = Path(__file__).parents[2] / "docs" / "connectors.md"
    assert doc.read_text(encoding="utf-8") == render(), (
        "run: python -m hydra_mcp.catalog.docs ../docs/connectors.md"
    )


SLACK_URL = "https://mcp.slack.com/mcp"


async def test_slack_flow_localhost_callback_commas_and_workspace_identity(env):
    proxy, provider = env
    provider.dcr = False
    provider.id_tokens = False
    provider.slack_shape = True
    r = await proxy.post("/admin/api/connect", headers=H, json={"connector_id": "slack"})
    assert r.status_code == 409 and r.json()["needs_manual_client"]
    guide = r.json()["guide"]
    # Not a loopback public URL here, so the callback is unchanged (see callback_for tests).
    assert guide["redirect_uri"] == "http://proxy.test/oauth/callback"
    assert "http://proxy.test/oauth/callback" in json.dumps(guide["steps"])  # in the manifest
    upstream_id = r.json()["upstream_id"]
    provider.clients["slack-app"] = {}
    r = await proxy.put(
        f"/admin/api/upstreams/{upstream_id}/oauth", headers=H, json={"client_id": "slack-app"}
    )
    assert r.status_code == 200, r.text
    r = await proxy.post("/admin/api/connect", headers=H, json={"connector_id": "slack"})
    url = r.json()["authorize_url"]
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert "," in q["scope"] and " " not in q["scope"]
    callback = provider.approve(url, "Acme Corp")
    r = await proxy.get("/oauth/callback", params=callback)
    assert r.status_code == 303, r.text
    accounts = (await proxy.get("/admin/api/accounts", headers=H)).json()
    slack = [a for a in accounts if a["upstream_id"] == upstream_id]
    assert slack and slack[0]["identity"] == "Acme Corp" and slack[0]["alias"] == "acme-corp"


async def test_another_workspace_gets_its_own_server_row(env):
    proxy, provider = env
    provider.dcr = False
    body = {"connector_id": "slack", "new_upstream": True}
    first = (await proxy.post("/admin/api/connect", headers=H, json=body)).json()["upstream_id"]
    # a cancelled attempt (no account yet) is reused rather than piling up rows
    again = (await proxy.post("/admin/api/connect", headers=H, json=body)).json()["upstream_id"]
    assert first == again == "slack"
    r = await proxy.put(
        "/admin/api/accounts",
        headers=H,
        json={"id": "slack-acme", "upstream_id": "slack", "alias": "acme"},
    )
    assert r.status_code == 200
    second = (await proxy.post("/admin/api/connect", headers=H, json=body)).json()["upstream_id"]
    assert second == "slack-2"
    plain = {"connector_id": "slack"}
    assert (await proxy.post("/admin/api/connect", headers=H, json=plain)).json()[
        "upstream_id"
    ] == "slack"


def test_callback_for_slack_uses_localhost_only_for_loopback_http():
    from hydra_mcp.broker.setup import callback_for

    slack = Upstream(id="slack", name="Slack", url=SLACK_URL)
    other = Upstream(id="lin", name="Linear", url="https://mcp.linear.app/mcp")
    assert (
        callback_for(slack, "http://127.0.0.1:8765/oauth/callback")
        == "http://localhost:8765/oauth/callback"
    )
    assert (
        callback_for(other, "http://127.0.0.1:8765/oauth/callback")
        == "http://127.0.0.1:8765/oauth/callback"
    )
    https = "https://hydra.example.com/oauth/callback"
    assert callback_for(slack, https) == https


def test_token_response_normalization():
    from hydra_mcp.broker.oauth import OAuthError, normalize_token_response

    with pytest.raises(OAuthError, match="invalid_code"):
        normalize_token_response({"ok": False, "error": "invalid_code"})
    out = normalize_token_response(
        {"ok": True, "authed_user": {"access_token": "xoxp-1", "scope": "a"}, "team": {}}
    )
    assert out["access_token"] == "xoxp-1"
    flat = {"access_token": "x", "token_type": "Bearer"}
    assert normalize_token_response(flat) == flat

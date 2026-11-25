"""hydra-mcp as an OAuth server for its own clients (claude.ai, Claude Desktop), the exposure
guard for tunnels, and the stdio bridge."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from hydra_mcp.app import create_app
from hydra_mcp.bridge import Bridge
from hydra_mcp.models import Account, Client, Grant, Upstream
from hydra_mcp.settings import Settings
from hydra_mcp.store import Store

ADMIN = "test-admin-token"
H = {"Authorization": f"Bearer {ADMIN}"}
LOCAL = "http://127.0.0.1:8765"
EXTERNAL = "https://hydra.example.net"
CLAUDE_CB = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
async def env(tmp_path):
    settings = Settings(
        public_url=LOCAL,
        external_url=EXTERNAL,
        data_dir=tmp_path,
        admin_token=ADMIN,
        admin_dist=None,
        stdio_enabled=False,
    )
    store = Store(":memory:")
    await store.open()
    await store.put_upstream(Upstream(id="mail", name="Mail", url="https://mail.test/mcp"))
    await store.put_account(Account(id="mail-work", upstream_id="mail", alias="work"))
    await store.put_client(
        Client(id="claude", name="Claude", grants=[Grant(account_id="mail-work")])
    )
    app = create_app(settings, store=store, http=httpx.AsyncClient())
    local = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=LOCAL)
    external = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=EXTERNAL)
    yield local, external, store
    await local.aclose()
    await external.aclose()
    await store.close()


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def register(http: httpx.AsyncClient, uri: str = CLAUDE_CB, name: str = "Claude") -> str:
    r = await http.post("/oauth/register", json={"client_name": name, "redirect_uris": [uri]})
    assert r.status_code == 201, r.text
    assert r.json()["token_endpoint_auth_method"] == "none"
    return r.json()["client_id"]


async def login(http, client_id, *, choice="claude", token=ADMIN, uri=CLAUDE_CB):
    verifier, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": uri,
        "state": "st-1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": f"{EXTERNAL}/mcp",
    }
    page = await http.get("/oauth/authorize", params=params)
    assert page.status_code == 200, page.text
    assert page.headers["x-frame-options"] == "DENY"
    request_id = page.text.split('name=request_id value="')[1].split('"')[0]
    r = await http.post(
        "/oauth/authorize",
        data={
            "request_id": request_id,
            "client": choice,
            "admin_token": token,
            "action": "approve",
        },
    )
    return r, verifier


async def full_login(http, **kw) -> dict:
    client_id = await register(http)
    r, verifier = await login(http, client_id, **kw)
    assert r.status_code == 303
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    assert q["state"] == "st-1" and q["iss"] == EXTERNAL
    t = await http.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": q["code"],
            "client_id": client_id,
            "redirect_uri": CLAUDE_CB,
            "code_verifier": verifier,
        },
    )
    assert t.status_code == 200, t.text
    return {**t.json(), "client_id": client_id, "code": q["code"], "verifier": verifier}


async def mcp(http, token, method="initialize"):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}
    return await http.post("/mcp", json=body, headers={"Authorization": f"Bearer {token}"})


async def test_unauthenticated_mcp_points_to_the_resource_metadata(env):
    _, external, _ = env
    r = await external.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401
    www = r.headers["www-authenticate"]
    assert f'resource_metadata="{EXTERNAL}/.well-known/oauth-protected-resource/mcp"' in www
    prm = (await external.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert prm["resource"] == f"{EXTERNAL}/mcp" and prm["authorization_servers"] == [EXTERNAL]
    meta = (await external.get("/.well-known/oauth-authorization-server")).json()
    assert meta["issuer"] == EXTERNAL
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["registration_endpoint"] == f"{EXTERNAL}/oauth/register"


async def test_metadata_follows_the_host_the_client_used(env):
    local, _, _ = env
    meta = (await local.get("/.well-known/oauth-authorization-server")).json()
    assert meta["issuer"] == LOCAL


async def test_full_login_then_mcp_with_the_clients_grants(env):
    _, external, _ = env
    tokens = await full_login(external)
    assert tokens["access_token"].startswith("hmcp_at_")
    assert tokens["expires_in"] == 3600 and tokens["refresh_token"].startswith("hmcp_rt_")
    r = await mcp(external, tokens["access_token"])
    assert r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == "hydra-mcp"
    # the code is single use
    again = await external.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": tokens["code"],
            "code_verifier": tokens["verifier"],
        },
    )
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


async def test_pkce_is_enforced(env):
    _, external, _ = env
    client_id = await register(external)
    r, _ = await login(external, client_id)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    t = await external.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "code_verifier": "wrong"},
    )
    assert t.status_code == 400 and "PKCE" in t.json()["error_description"]
    # and an authorize request without PKCE is refused back to the app
    r = await external.get(
        "/oauth/authorize",
        params={"response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CB},
    )
    assert r.status_code == 302 and "error=invalid_request" in r.headers["location"]


async def test_refresh_rotates_and_reuse_revokes_the_grant(env):
    _, external, _ = env
    first = await full_login(external)
    r = await external.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]},
    )
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert (await mcp(external, second["access_token"])).status_code == 200
    # the previous access token still works until it expires (in-flight calls)
    assert (await mcp(external, first["access_token"])).status_code == 200
    # replaying the rotated refresh token: stolen copy, the whole grant goes
    r = await external.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]},
    )
    assert r.status_code == 400
    assert (await mcp(external, second["access_token"])).status_code == 401
    r = await external.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": second["refresh_token"]},
    )
    assert r.status_code == 400


async def test_wrong_admin_token_cannot_approve(env):
    _, external, _ = env
    client_id = await register(external)
    r, _ = await login(external, client_id, token="guess")
    assert r.status_code == 401 and "Wrong admin token" in r.text
    assert "location" not in r.headers


async def test_deny_returns_access_denied(env):
    _, external, _ = env
    client_id = await register(external)
    verifier, challenge = pkce()
    page = await external.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLAUDE_CB,
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    request_id = page.text.split('name=request_id value="')[1].split('"')[0]
    r = await external.post("/oauth/authorize", data={"request_id": request_id, "action": "deny"})
    assert r.status_code == 303 and "error=access_denied" in r.headers["location"]


async def test_approving_as_a_new_client_creates_it_without_access(env):
    local, external, store = env
    tokens = await full_login(external, choice="__new__")
    clients = {c.id: c for c in await store.list_clients()}
    new = [c for c in clients.values() if c.id != "claude"]
    assert len(new) == 1 and new[0].name == "Claude" and new[0].grants == []
    r = await mcp(external, tokens["access_token"], "tools/list")
    assert r.json()["result"]["tools"] == []
    logins = (await local.get("/admin/api/app-logins", headers=H)).json()
    assert logins[0]["client_id"] == new[0].id and logins[0]["app_name"] == "Claude"
    assert (
        await local.delete(f"/admin/api/app-logins/{logins[0]['id']}", headers=H)
    ).status_code == 204
    assert (await mcp(external, tokens["access_token"])).status_code == 401


async def test_redirect_validation(env):
    _, external, _ = env
    for bad in ("http://evil.example/cb", "javascript:alert(1)", "https://x.example/cb#frag"):
        r = await external.post("/oauth/register", json={"redirect_uris": [bad]})
        assert r.status_code == 400, bad
    loopback = await register(external, "http://127.0.0.1:3118/callback", "Claude Code")
    # unknown redirect: an error page, never a redirect (no open redirector)
    r = await external.get(
        "/oauth/authorize",
        params={"client_id": loopback, "redirect_uri": "https://evil.example/cb"},
    )
    assert r.status_code == 400 and "location" not in r.headers
    # loopback port may differ (RFC 8252)
    _, challenge = pkce()
    r = await external.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": loopback,
            "redirect_uri": "http://127.0.0.1:55555/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 200


async def test_tunnel_requests_only_reach_public_paths(env):
    local, external, _ = env
    assert (await external.get("/admin/api/status", headers=H)).status_code == 404
    assert (await external.get("/a/mail-work/mcp")).status_code == 404
    assert (await external.get("/oauth/callback?code=x&state=y")).status_code == 404
    forwarded = {**H, "X-Forwarded-For": "203.0.113.9"}
    assert (await local.get("/admin/api/status", headers=forwarded)).status_code == 404
    status = await local.get("/admin/api/status", headers=H)
    assert status.status_code == 200
    assert status.json()["external_endpoint"] == f"{EXTERNAL}/mcp"
    assert (await external.get("/healthz")).status_code == 200


async def test_static_keys_still_work(env):
    local, _, _ = env
    key = (await local.post("/admin/api/clients/claude/key", headers=H)).json()["key"]
    assert (await mcp(local, key)).status_code == 200


async def test_bridge_relays_stdio_lines_to_mcp(env):
    local, _, _ = env
    key = (await local.post("/admin/api/clients/claude/key", headers=H)).json()["key"]
    out = io.BytesIO()
    bridge = Bridge(f"{LOCAL}/mcp", key, out=out, http=local)
    reader = asyncio.StreamReader()
    for msg in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ):
        reader.feed_data(json.dumps(msg).encode() + b"\n")
    reader.feed_data(b"not json\n")
    reader.feed_eof()
    await bridge.run(reader)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    by_id = {m.get("id"): m for m in lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "hydra-mcp"
    assert "tools" in by_id[2]["result"]
    assert by_id[None]["error"]["code"] == -32700
    assert len(lines) == 3  # the notification got no answer


async def test_bridge_reports_a_bad_key(env):
    local, _, _ = env
    out = io.BytesIO()
    reader = asyncio.StreamReader()
    reader.feed_data(b'{"jsonrpc":"2.0","id":7,"method":"ping"}\n')
    reader.feed_eof()
    await Bridge(f"{LOCAL}/mcp", "hmcp_wrong", out=out, http=local).run(reader)
    msg = json.loads(out.getvalue())
    assert msg["id"] == 7 and "client key" in msg["error"]["message"]

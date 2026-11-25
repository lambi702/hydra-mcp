"""Demo mode: the fake provider, the seeding through the real OAuth flow, and the browser login."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from hydra_mcp.app import create_app
from hydra_mcp.cli import find_admin_dist
from hydra_mcp.demo import DemoProvider, DemoSeed, _s256, seed
from hydra_mcp.settings import Settings
from hydra_mcp.store import Store

BASE = "http://proxy.test"
ADMIN = "demo-admin"
H = {"Authorization": f"Bearer {ADMIN}"}


@pytest.fixture
async def demo(tmp_path):
    """The proxy in demo mode, started (lifespan run, so the seed ran) and wired in process."""
    settings = Settings(public_url=BASE, data_dir=tmp_path, admin_token=ADMIN, admin_dist=None)
    provider = DemoProvider(BASE)
    seeded: list[DemoSeed] = []

    async def on_startup(services):
        seeded.append(await seed(services, provider))

    app = create_app(settings, store=Store(":memory:"), demo=provider, on_startup=on_startup)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            yield client, provider, seeded[0]


async def _rpc(client: httpx.AsyncClient, key: str, method: str, params: dict | None = None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    resp = await client.post("/mcp", json=body, headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


async def test_seed_connects_two_accounts_through_oauth(demo):
    client, provider, result = demo
    assert result.accounts == ["acme", "globex"]
    accounts = (await client.get("/admin/api/accounts", headers=H)).json()
    assert {(a["alias"], a["identity"]) for a in accounts} == {
        ("acme", "alice@acme.example"),
        ("globex", "bob@globex.example"),
    }
    # tokens came from the demo AS (one per workspace), and the proxy registered itself by DCR
    assert len(provider.access) == 2 and len(provider.clients) == 1
    status = (await client.get("/admin/api/accounts-status", headers=H)).json()
    assert set(status) == {"demo-acme", "demo-globex"}


async def test_demo_client_sees_grants_and_each_account_its_own_data(demo):
    client, _, result = demo
    tools = {t["name"]: t for t in (await _rpc(client, result.client_key, "tools/list"))["tools"]}
    enum = lambda name: tools[name]["inputSchema"]["properties"]["account"]["enum"]  # noqa: E731
    assert enum("demo__search_issues") == ["acme", "globex"]
    assert enum("demo__create_issue") == ["acme"]  # globex is granted read only

    def text(result: dict) -> str:
        return result["content"][0]["text"]

    acme = await _rpc(
        client,
        result.client_key,
        "tools/call",
        {"name": "demo__search_issues", "arguments": {"account": "acme"}},
    )
    globex = await _rpc(
        client,
        result.client_key,
        "tools/call",
        {"name": "demo__search_issues", "arguments": {"account": "globex", "status": "open"}},
    )
    assert "ACME-101" in text(acme) and "GLX" not in text(acme)
    assert "GLX-101" in text(globex) and "GLX-102" not in text(globex)  # in progress, filtered

    refused = await _rpc(
        client,
        result.client_key,
        "tools/call",
        {"name": "demo__create_issue", "arguments": {"account": "globex", "title": "x"}},
    )
    assert refused["isError"]
    created = await _rpc(
        client,
        result.client_key,
        "tools/call",
        {"name": "demo__create_issue", "arguments": {"account": "acme", "title": "From the AI"}},
    )
    assert "ACME-105" in text(created)


async def test_browser_login_adds_a_third_account(demo):
    client, _, _ = demo
    resp = await client.post("/admin/api/connect", json={"upstream_id": "demo"}, headers=H)
    authorize_url = resp.json()["authorize_url"]
    assert authorize_url.startswith(f"{BASE}/demo/authorize?")

    page = await client.get(authorize_url)
    assert page.status_code == 200 and "Initech" in page.text

    form = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
    back = await client.post(
        "/demo/authorize", data={**form, "decision": "allow", "workspace": "initech"}
    )
    assert back.status_code == 303
    callback = back.headers["location"]
    assert callback.startswith(f"{BASE}/oauth/callback?")

    done = await client.get(callback)
    assert done.status_code == 303
    assert done.headers["location"] == "/admin/?connected=demo-initech&new=1"


async def test_cancel_on_login_page_returns_access_denied(demo):
    client, _, _ = demo
    resp = await client.post("/admin/api/connect", json={"upstream_id": "demo"}, headers=H)
    form = {k: v[0] for k, v in parse_qs(urlsplit(resp.json()["authorize_url"]).query).items()}
    back = await client.post("/demo/authorize", data={**form, "decision": "deny"})
    assert "error=access_denied" in back.headers["location"]
    page = await client.get(back.headers["location"])
    assert "Connection cancelled" in page.text


async def test_provider_is_strict_about_pkce_and_tokens(demo):
    client, provider, _ = demo
    assert (await client.post("/demo/mcp", json={"jsonrpc": "2.0", "id": 1})).status_code == 401
    client_id = next(iter(provider.clients))
    redirect = provider.clients[client_id][0]
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "code_challenge": _s256("right-verifier"),
        "code_challenge_method": "S256",
        "state": "s",
    }
    code = parse_qs(urlsplit(provider.approve(params, "acme")).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "client_id": client_id}
    wrong = await client.post(
        "/demo/token", data={**form, "redirect_uri": redirect, "code_verifier": "wrong"}
    )
    assert wrong.status_code == 400 and wrong.json()["error"] == "invalid_grant"
    # codes are single use: even the right verifier fails now
    again = await client.post(
        "/demo/token", data={**form, "redirect_uri": redirect, "code_verifier": "right-verifier"}
    )
    assert again.status_code == 400
    with pytest.raises(ValueError, match="PKCE"):
        provider.approve({**params, "code_challenge_method": "plain"}, "acme")


async def test_demo_routes_do_not_exist_outside_demo_mode(proxy):
    assert (await proxy.get("/demo/authorize")).status_code == 404
    assert (await proxy.get("/.well-known/oauth-authorization-server/demo")).status_code == 404


def test_loopback_only_claims_the_demo_paths():
    provider = DemoProvider("http://127.0.0.1:8765")
    owns = lambda url: provider.owns(httpx.URL(url))  # noqa: E731
    assert owns("http://127.0.0.1:8765/demo/mcp")
    assert owns("http://127.0.0.1:8765/.well-known/oauth-authorization-server/demo")
    assert not owns("http://127.0.0.1:8765/mcp")
    assert not owns("http://127.0.0.1:9999/demo/mcp")
    assert not owns("https://mcp.atlassian.com/demo/mcp")


def test_admin_dist_lookup(tmp_path, monkeypatch):
    explicit = tmp_path / "custom"
    assert find_admin_dist(Settings(admin_dist=explicit)) == explicit
    checkout = tmp_path / "checkout"
    monkeypatch.setattr("hydra_mcp.cli.CHECKOUT_ADMIN_DIST", checkout)
    monkeypatch.setattr("hydra_mcp.cli.packaged_admin_dist", lambda: tmp_path / "pkg")
    assert find_admin_dist(Settings()) == tmp_path / "pkg"  # no checkout build: packaged copy
    checkout.mkdir()
    (checkout / "index.html").write_text("<!doctype html>")
    assert find_admin_dist(Settings()) == checkout  # a fresh `make build` wins in a checkout

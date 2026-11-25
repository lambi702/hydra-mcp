"""Local (stdio) upstreams: one process per account, secrets per account, crash recovery."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from hydra_mcp.app import create_app
from hydra_mcp.broker.stdio import StdioPool, child_env
from hydra_mcp.broker.upstream import UpstreamError
from hydra_mcp.models import Client, Grant, GrantMode, Transport, Upstream
from hydra_mcp.settings import Settings
from hydra_mcp.store import Store

ADMIN = "test-admin-token"
H = {"Authorization": f"Bearer {ADMIN}"}
SERVER = str(Path(__file__).parent / "fixtures" / "stdio_server.py")


def spec(**env) -> dict:
    return {
        "name": "Notes",
        "command": sys.executable,
        "args": ["-I", SERVER],
        "env": {"SHARED": "yes", **env},
    }


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_MCP_SECRET", "must-not-leak")
    settings = Settings(
        public_url="http://proxy.test", data_dir=tmp_path, admin_token=ADMIN, admin_dist=None
    )
    store = Store(":memory:")
    await store.open()
    app = create_app(settings, store=store, http=httpx.AsyncClient())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://proxy.test"
    ) as proxy:
        yield proxy, store, app.state.services
    await app.state.services.stdio.close()
    await store.close()


async def add(proxy, alias: str, token: str, **extra) -> httpx.Response:
    body = {**spec(), "alias": alias, "account_env": {"FAKE_TOKEN": token}, **extra}
    return await proxy.post("/admin/api/connect-stdio", headers=H, json=body)


async def mcp(proxy, key: str, method: str, params: dict | None = None) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    r = await proxy.post("/mcp", headers={"Authorization": f"Bearer {key}"}, json=body)
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def grant_all(proxy, store, *accounts: str) -> str:
    await store.put_client(
        Client(
            id="desk",
            name="Desktop",
            grants=[Grant(account_id=a, mode=GrantMode.WRITE) for a in accounts],
        )
    )
    r = await proxy.post("/admin/api/clients/desk/key", headers=H)
    return r.json()["key"]


async def test_two_accounts_of_one_local_server_run_as_two_processes(env):
    proxy, store, services = env
    r1 = await add(proxy, "work", "tok-work")
    assert r1.status_code == 200, r1.text
    assert r1.json()["created"] and r1.json()["tools"] == 2
    assert r1.json()["server"]["name"] == "fake-stdio"
    r2 = await add(proxy, "perso", "tok-perso")
    assert r2.status_code == 200, r2.text
    # Same command + args: one upstream, two accounts.
    assert r1.json()["upstream_id"] == r2.json()["upstream_id"] == "notes"
    upstream = await store.get_upstream("notes")
    assert upstream.transport is Transport.STDIO and upstream.url is None
    assert upstream.env == {"SHARED": "yes"}

    key = await grant_all(proxy, store, "notes-work", "notes-perso")
    tools = (await mcp(proxy, key, "tools/list"))["tools"]
    whoami = next(t for t in tools if t["name"] == "notes__whoami")
    assert whoami["inputSchema"]["properties"]["account"]["enum"] == ["perso", "work"]

    out = {}
    for alias in ("work", "perso"):
        res = await mcp(
            proxy, key, "tools/call", {"name": "notes__whoami", "arguments": {"account": alias}}
        )
        out[alias] = res["content"][0]["text"]
    assert "token=tok-work" in out["work"] and "token=tok-perso" in out["perso"]
    pid = {a: t.split("pid=")[1].split()[0] for a, t in out.items()}
    assert pid["work"] != pid["perso"]
    assert "shared=yes" in out["work"]
    assert out["work"].endswith("leak=")  # the proxy's own environment is not passed on
    assert set(services.stdio.running()) == {"notes-work", "notes-perso"}


async def test_secrets_are_encrypted_and_never_returned(env):
    proxy, store, _ = env
    assert (await add(proxy, "work", "tok-secret-123")).status_code == 200
    row = await store.get_token_row("notes-work")
    assert b"tok-secret-123" not in row["blob"]
    r = await proxy.get("/admin/api/upstreams", headers=H)
    assert "tok-secret-123" not in r.text
    status = await proxy.get("/admin/api/accounts-status", headers=H)
    assert "notes-work" in status.json() and "tok-secret-123" not in status.text


async def test_a_server_that_does_not_start_saves_nothing(env):
    proxy, store, _ = env
    r = await add(proxy, "work", "")  # FAKE_TOKEN empty -> the server exits with code 3
    assert r.status_code == 400
    assert "FAKE_TOKEN is not set" in r.json()["error"]
    assert await store.list_upstreams() == [] and await store.list_accounts() == []

    r = await proxy.post(
        "/admin/api/connect-stdio",
        headers=H,
        json={"name": "Nope", "command": "/no/such/binary", "alias": "x"},
    )
    assert r.status_code == 400 and "cannot start" in r.json()["error"]


async def test_crash_is_reported_with_stderr_and_the_next_call_restarts(env):
    proxy, store, services = env
    r = await add(proxy, "work", "tok", env={"SHARED": "yes", "FAKE_CRASH_ON": "write_note"})
    # env in the body replaces the default spec env
    assert r.status_code == 200, r.text
    key = await grant_all(proxy, store, "notes-work")
    res = await mcp(
        proxy, key, "tools/call", {"name": "notes__write_note", "arguments": {"account": "work"}}
    )
    assert res["isError"] and "boom: simulated crash" in res["content"][0]["text"]
    assert "code 7" in res["content"][0]["text"]
    res = await mcp(
        proxy, key, "tools/call", {"name": "notes__whoami", "arguments": {"account": "work"}}
    )
    assert not res.get("isError") and "token=tok" in res["content"][0]["text"]


async def test_replacing_settings_restarts_the_process(env):
    proxy, store, services = env
    await add(proxy, "work", "old")
    key = await grant_all(proxy, store, "notes-work")
    call = {"name": "notes__whoami", "arguments": {"account": "work"}}
    assert "token=old" in (await mcp(proxy, key, "tools/call", call))["content"][0]["text"]
    r = await proxy.post(
        "/admin/api/connect-stdio",
        headers=H,
        json={"account_id": "notes-work", "account_env": {"FAKE_TOKEN": "new"}},
    )
    assert r.status_code == 200 and not r.json()["created"]
    assert "token=new" in (await mcp(proxy, key, "tools/call", call))["content"][0]["text"]


async def test_isolated_home_per_account(env, tmp_path):
    proxy, store, _ = env
    assert (await add(proxy, "work", "a", isolate_home=True)).status_code == 200
    assert (await add(proxy, "perso", "b")).status_code == 200
    key = await grant_all(proxy, store, "notes-work", "notes-perso")
    texts = {}
    for alias in ("work", "perso"):
        call = {"name": "notes__whoami", "arguments": {"account": alias}}
        texts[alias] = (await mcp(proxy, key, "tools/call", call))["content"][0]["text"]
    assert f"home={tmp_path / 'stdio' / 'notes-work'}" in texts["work"]
    assert f"home={tmp_path / 'stdio' / 'notes-perso'}" in texts["perso"]


async def test_duplicate_alias_is_refused(env):
    proxy, _, _ = env
    assert (await add(proxy, "work", "a")).status_code == 200
    r = await add(proxy, "work", "b")
    assert r.status_code == 409


async def test_router_mode_refuses_stdio_accounts(env):
    proxy, _, _ = env
    await add(proxy, "work", "a")
    r = await proxy.post("/a/notes-work/mcp", json={})
    assert r.status_code == 404


async def test_banner_on_stdout_is_tolerated(tmp_path):
    pool = StdioPool(tmp_path, timeout_s=10)
    up = Upstream(
        id="n",
        name="N",
        transport="stdio",
        command=sys.executable,
        args=["-I", SERVER],
        env={"FAKE_BANNER": "Server ready!"},
    )
    try:
        res = await pool.request("k", up, {"FAKE_TOKEN": "t"}, "tools/list")
        assert len(res["tools"]) == 2
    finally:
        await pool.close()


async def test_disabled_stdio(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_token=ADMIN, stdio_enabled=False)
    store = Store(":memory:")
    await store.open()
    app = create_app(settings, store=store, http=httpx.AsyncClient())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://proxy.test"
    ) as proxy:
        r = await add(proxy, "work", "a")
        assert r.status_code == 403
    await store.close()


def test_model_validation():
    with pytest.raises(ValueError):
        Upstream(id="x", name="X", transport="stdio")
    with pytest.raises(ValueError):
        Upstream(id="x", name="X")  # http without url
    with pytest.raises(ValueError):
        Upstream(id="x", name="X", transport="stdio", command="a", env={"BAD NAME": "1"})


def test_child_env_keeps_path_and_drops_the_rest(monkeypatch):
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    up = Upstream(id="x", name="X", transport="stdio", command="a", env={"A": "1"})
    env = child_env(up, {"B": "2"}, None)
    assert env["PATH"] == "/bin" and env["A"] == "1" and env["B"] == "2"
    assert "AWS_SECRET_ACCESS_KEY" not in env


async def test_unknown_command_error_message(tmp_path):
    pool = StdioPool(tmp_path)
    up = Upstream(id="x", name="X", transport="stdio", command="definitely-not-installed-xyz")
    with pytest.raises(UpstreamError, match="cannot start"):
        await pool.request("k", up, {}, "tools/list")

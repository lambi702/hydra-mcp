from hydra_mcp.models import Client, Grant, GrantMode
from tests.conftest import ADMIN

H = {"Authorization": f"Bearer {ADMIN}"}


async def test_admin_requires_token(proxy):
    assert (await proxy.get("/admin/api/status")).status_code == 401
    assert (
        await proxy.get("/admin/api/status", headers={"Authorization": "Bearer no"})
    ).status_code == 401


async def test_status_lists_enabled_endpoints(proxy):
    r = await proxy.get("/admin/api/status", headers=H)
    assert r.json()["endpoints"] == {"gmail-work": "http://proxy.test/a/gmail-work/mcp"}


async def test_account_crud_and_validation(proxy):
    r = await proxy.post(
        "/admin/api/accounts",
        headers=H,
        json={"id": "gmail-perso", "upstream_id": "gmail", "alias": "perso", "identity": "me@x"},
    )
    assert r.status_code == 200
    ids = [a["id"] for a in (await proxy.get("/admin/api/accounts", headers=H)).json()]
    assert "gmail-perso" in ids
    bad = await proxy.post(
        "/admin/api/accounts",
        headers=H,
        json={"id": "Bad Id", "upstream_id": "gmail", "alias": "x"},
    )
    assert bad.status_code == 422
    dup_alias = await proxy.post(
        "/admin/api/accounts",
        headers=H,
        json={"id": "other", "upstream_id": "gmail", "alias": "perso"},
    )
    assert dup_alias.status_code == 409
    assert (await proxy.delete("/admin/api/accounts/gmail-perso", headers=H)).status_code == 204


async def test_client_profile_roundtrip(proxy):
    body = {
        "id": "claude-desktop",
        "name": "Claude Desktop",
        "grants": [{"account_id": "gmail-work", "tools": "search_*", "mode": "read"}],
    }
    assert (await proxy.post("/admin/api/clients", headers=H, json=body)).status_code == 200
    (c,) = (await proxy.get("/admin/api/clients", headers=H)).json()
    assert c["grants"] == body["grants"]


async def test_probe_reports_where_users_log_in(proxy):
    r = await proxy.post("/admin/api/upstreams/gmail/probe", headers=H)
    data = r.json()
    assert data["ok"] is True
    (as_,) = data["authorization_servers"]
    assert as_["authorization_endpoint"] == "https://as.upstream.test/authorize"
    assert as_["client_id_metadata_document_supported"] is True


def test_grant_semantics():
    c = Client(
        id="c",
        name="c",
        grants=[
            Grant(account_id="gmail-work", tools="search_*", mode=GrantMode.READ),
            Grant(account_id="gmail-perso", mode=GrantMode.WRITE),
        ],
    )
    assert c.allows("gmail-work", "search_threads", read_only=True)
    assert not c.allows("gmail-work", "search_threads", read_only=False)  # read grant only
    assert not c.allows("gmail-work", "send_message", read_only=False)  # pattern mismatch
    assert c.allows("gmail-perso", "send_message", read_only=False)
    assert not c.allows("atlassian-a", "search", read_only=True)  # not granted at all


async def test_catalog_lists_vendor_connectors(proxy):
    data = (await proxy.get("/admin/api/catalog", headers=H)).json()
    by_id = {c["id"]: c for c in data["connectors"]}
    assert by_id["gmail"]["url"] == "https://gmailmcp.googleapis.com/mcp/v1"
    assert by_id["gmail"]["auth"] == "oauth_preregistered"
    assert by_id["linear"]["installed_as"] is None


async def test_install_connector_creates_upstream(proxy):
    r = await proxy.post("/admin/api/catalog/linear/install", headers=H)
    assert r.status_code == 201
    body = r.json()
    assert {k: body[k] for k in ("id", "name", "url", "transport")} == {
        "id": "linear",
        "name": "Linear",
        "url": "https://mcp.linear.app/mcp",
        "transport": "http",
    }
    data = (await proxy.get("/admin/api/catalog", headers=H)).json()
    assert {c["id"]: c for c in data["connectors"]}["linear"]["installed_as"] == "linear"
    r2 = await proxy.post("/admin/api/catalog/notion/install", headers=H, json={"id": "notion-2"})
    assert r2.json()["id"] == "notion-2"
    assert (await proxy.post("/admin/api/catalog/nope/install", headers=H)).status_code == 404


def test_catalog_entries_are_valid_and_unique():
    from hydra_mcp.catalog import load_catalog

    cat = load_catalog()
    ids = [c.id for c in cat.connectors]
    assert len(ids) == len(set(ids))
    assert all(str(c.url).startswith("https://") for c in cat.connectors)

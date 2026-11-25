"""SQLite persistence for upstreams, accounts, clients and grants.

Deliberately small: one file, no ORM. Secrets (upstream tokens, OAuth client secrets) are only
ever written here already encrypted by the vault; client keys are stored as SHA-256 hashes.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from hydra_mcp.models import Account, Client, Grant, Upstream

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS upstreams (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id          TEXT PRIMARY KEY,
    upstream_id TEXT NOT NULL REFERENCES upstreams(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    identity    TEXT NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    UNIQUE (upstream_id, alias)
);
CREATE TABLE IF NOT EXISTS clients (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grants (
    client_id  TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    tools      TEXT NOT NULL DEFAULT '*',
    mode       TEXT NOT NULL DEFAULT 'write',
    PRIMARY KEY (client_id, account_id, tools)
);
-- Broker mode: the proxy's own OAuth client registration at each upstream AS.
CREATE TABLE IF NOT EXISTS upstream_oauth (
    upstream_id   TEXT PRIMARY KEY REFERENCES upstreams(id) ON DELETE CASCADE,
    issuer        TEXT NOT NULL,
    client_id     TEXT NOT NULL,
    secret_enc    BLOB,
    auth_method   TEXT NOT NULL DEFAULT 'none',
    registration  TEXT NOT NULL  -- 'dcr' | 'manual'
);
-- Broker mode: one encrypted token bundle per account.
CREATE TABLE IF NOT EXISTS account_tokens (
    account_id  TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    blob        BLOB NOT NULL,
    expires_at  REAL,
    identity    TEXT NOT NULL DEFAULT '',
    updated_at  REAL NOT NULL
);
-- In-flight "connect" flows (state is single use, short lived). account_id is NULL for a new
-- connection: the account is created only once the login succeeded, so a cancelled or failed
-- login leaves nothing behind in the account list.
-- hydra-mcp as an OAuth server for its own clients (claude.ai, Claude Desktop...).
CREATE TABLE IF NOT EXISTS oauth_apps (
    client_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    redirect_uris TEXT NOT NULL,  -- JSON list
    created_at    REAL NOT NULL
);
-- Short-lived, single-use rows: consent requests ('pending') and authorization codes ('code').
CREATE TABLE IF NOT EXISTS oauth_transient (
    id         TEXT PRIMARY KEY,  -- request id, or SHA-256 of the code
    kind       TEXT NOT NULL,
    data       TEXT NOT NULL,
    expires_at REAL NOT NULL
);
-- One row per approved login of an app: the hydra client it acts as, and its current tokens
-- (SHA-256 only). The previous pair is kept for in-flight calls and reuse detection.
CREATE TABLE IF NOT EXISTS oauth_grants (
    id                 TEXT PRIMARY KEY,
    app_id             TEXT NOT NULL REFERENCES oauth_apps(client_id) ON DELETE CASCADE,
    client_id          TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    access_hash        TEXT NOT NULL,
    access_expires     REAL NOT NULL,
    prev_access_hash   TEXT,
    prev_access_expires REAL,
    refresh_hash       TEXT NOT NULL,
    refresh_expires    REAL NOT NULL,
    prev_refresh_hash  TEXT,
    created_at         REAL NOT NULL,
    last_used_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS oauth_grants_access ON oauth_grants(access_hash);
CREATE INDEX IF NOT EXISTS oauth_grants_refresh ON oauth_grants(refresh_hash);
CREATE TABLE IF NOT EXISTS link_flows (
    state       TEXT PRIMARY KEY,
    upstream_id TEXT NOT NULL REFERENCES upstreams(id) ON DELETE CASCADE,
    account_id  TEXT REFERENCES accounts(id) ON DELETE CASCADE,
    verifier    TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""

MIGRATIONS = [
    # (table, column, DDL) -- additive only, applied when the column is missing
    ("clients", "key_hash", "ALTER TABLE clients ADD COLUMN key_hash TEXT"),
]


class NotFound(LookupError):
    pass


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = await self._db.execute_fetchall(f"PRAGMA table_info({table})")
            if column not in {c["name"] for c in cols}:
                await self._db.execute(ddl)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store is not open")
        return self._db

    # -- upstreams -------------------------------------------------------------------------
    async def list_upstreams(self) -> list[Upstream]:
        rows = await self.db.execute_fetchall("SELECT id, name, url FROM upstreams ORDER BY id")
        return [Upstream(**dict(r)) for r in rows]

    async def put_upstream(self, u: Upstream) -> Upstream:
        await self.db.execute(
            "INSERT INTO upstreams (id, name, url) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, url = excluded.url",
            (u.id, u.name, str(u.url)),
        )
        await self.db.commit()
        return u

    async def delete_upstream(self, upstream_id: str) -> None:
        await self._delete("upstreams", upstream_id)

    # -- accounts --------------------------------------------------------------------------
    async def list_accounts(self) -> list[Account]:
        rows = await self.db.execute_fetchall(
            "SELECT id, upstream_id, alias, identity, enabled FROM accounts ORDER BY id"
        )
        return [Account(**{**dict(r), "enabled": bool(r["enabled"])}) for r in rows]

    async def get_account(self, account_id: str) -> tuple[Account, Upstream]:
        rows = await self.db.execute_fetchall(
            "SELECT a.id, a.upstream_id, a.alias, a.identity, a.enabled, "
            "u.name AS u_name, u.url AS u_url "
            "FROM accounts a JOIN upstreams u ON u.id = a.upstream_id WHERE a.id = ?",
            (account_id,),
        )
        if not rows:
            raise NotFound(account_id)
        r = dict(rows[0])
        upstream = Upstream(id=r["upstream_id"], name=r.pop("u_name"), url=r.pop("u_url"))
        return Account(**{**r, "enabled": bool(r["enabled"])}), upstream

    async def put_account(self, a: Account) -> Account:
        await self.db.execute(
            "INSERT INTO accounts (id, upstream_id, alias, identity, enabled) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "upstream_id = excluded.upstream_id, alias = excluded.alias, "
            "identity = excluded.identity, enabled = excluded.enabled",
            (a.id, a.upstream_id, a.alias, a.identity, int(a.enabled)),
        )
        await self.db.commit()
        return a

    async def delete_account(self, account_id: str) -> None:
        await self._delete("accounts", account_id)

    # -- clients and grants ----------------------------------------------------------------
    async def list_clients(self) -> list[Client]:
        clients = {
            r["id"]: Client(id=r["id"], name=r["name"])
            for r in await self.db.execute_fetchall("SELECT id, name FROM clients ORDER BY id")
        }
        for r in await self.db.execute_fetchall(
            "SELECT client_id, account_id, tools, mode FROM grants ORDER BY account_id, tools"
        ):
            clients[r["client_id"]].grants.append(
                Grant(account_id=r["account_id"], tools=r["tools"], mode=r["mode"])
            )
        return list(clients.values())

    async def get_client(self, client_id: str) -> Client:
        for c in await self.list_clients():
            if c.id == client_id:
                return c
        raise NotFound(client_id)

    async def put_client(self, c: Client) -> Client:
        """Upsert a client and replace its grants atomically."""
        await self.db.execute(
            "INSERT INTO clients (id, name) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (c.id, c.name),
        )
        await self.db.execute("DELETE FROM grants WHERE client_id = ?", (c.id,))
        await self.db.executemany(
            "INSERT INTO grants (client_id, account_id, tools, mode) VALUES (?, ?, ?, ?)",
            [(c.id, g.account_id, g.tools, g.mode.value) for g in c.grants],
        )
        await self.db.commit()
        return c

    async def delete_client(self, client_id: str) -> None:
        await self._delete("clients", client_id)

    async def set_client_key_hash(self, client_id: str, key_hash: str | None) -> None:
        cur = await self.db.execute(
            "UPDATE clients SET key_hash = ? WHERE id = ?", (key_hash, client_id)
        )
        await self.db.commit()
        if cur.rowcount == 0:
            raise NotFound(client_id)

    async def client_by_key_hash(self, key_hash: str) -> Client | None:
        rows = await self.db.execute_fetchall(
            "SELECT id FROM clients WHERE key_hash = ?", (key_hash,)
        )
        return await self.get_client(rows[0]["id"]) if rows else None

    async def clients_with_key(self) -> set[str]:
        rows = await self.db.execute_fetchall("SELECT id FROM clients WHERE key_hash IS NOT NULL")
        return {r["id"] for r in rows}

    # -- broker: upstream OAuth clients ------------------------------------------------------
    async def get_upstream_oauth(self, upstream_id: str) -> dict | None:
        rows = await self.db.execute_fetchall(
            "SELECT * FROM upstream_oauth WHERE upstream_id = ?", (upstream_id,)
        )
        return dict(rows[0]) if rows else None

    async def put_upstream_oauth(
        self,
        upstream_id: str,
        *,
        issuer: str,
        client_id: str,
        secret_enc: bytes | None,
        auth_method: str,
        registration: str,
    ) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO upstream_oauth "
            "(upstream_id, issuer, client_id, secret_enc, auth_method, registration) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (upstream_id, issuer, client_id, secret_enc, auth_method, registration),
        )
        await self.db.commit()

    async def delete_upstream_oauth(self, upstream_id: str) -> None:
        await self.db.execute("DELETE FROM upstream_oauth WHERE upstream_id = ?", (upstream_id,))
        await self.db.commit()

    # -- broker: account tokens ---------------------------------------------------------------
    async def get_token_row(self, account_id: str) -> dict | None:
        rows = await self.db.execute_fetchall(
            "SELECT * FROM account_tokens WHERE account_id = ?", (account_id,)
        )
        return dict(rows[0]) if rows else None

    async def put_token_row(
        self, account_id: str, blob: bytes, expires_at: float | None, identity: str, now: float
    ) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO account_tokens "
            "(account_id, blob, expires_at, identity, updated_at) VALUES (?, ?, ?, ?, ?)",
            (account_id, blob, expires_at, identity, now),
        )
        await self.db.commit()

    async def delete_token_row(self, account_id: str) -> None:
        await self.db.execute("DELETE FROM account_tokens WHERE account_id = ?", (account_id,))
        await self.db.commit()

    async def token_status(self) -> dict[str, dict]:
        rows = await self.db.execute_fetchall(
            "SELECT account_id, expires_at, identity, updated_at FROM account_tokens"
        )
        return {r["account_id"]: dict(r) for r in rows}

    # -- broker: link states ------------------------------------------------------------------
    async def put_link_flow(
        self, state: str, upstream_id: str, account_id: str | None, verifier: str, now: float
    ) -> None:
        await self.db.execute("DELETE FROM link_flows WHERE created_at < ?", (now - 600,))
        await self.db.execute(
            "INSERT INTO link_flows (state, upstream_id, account_id, verifier, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (state, upstream_id, account_id, verifier, now),
        )
        await self.db.commit()

    async def pop_link_flow(self, state: str, now: float) -> dict | None:
        """Single use: the row is deleted whether or not it is still valid."""
        rows = await self.db.execute_fetchall("SELECT * FROM link_flows WHERE state = ?", (state,))
        await self.db.execute("DELETE FROM link_flows WHERE state = ?", (state,))
        await self.db.commit()
        if not rows or rows[0]["created_at"] < now - 600:
            return None
        return dict(rows[0])

    async def get_upstream(self, upstream_id: str) -> Upstream:
        rows = await self.db.execute_fetchall(
            "SELECT id, name, url FROM upstreams WHERE id = ?", (upstream_id,)
        )
        if not rows:
            raise NotFound(upstream_id)
        return Upstream(**dict(rows[0]))

    # -- OAuth server for clients ---------------------------------------------------------------
    async def put_oauth_app(self, client_id: str, name: str, uris: list[str], now: float) -> None:
        await self.db.execute(
            "INSERT INTO oauth_apps (client_id, name, redirect_uris, created_at) VALUES (?,?,?,?)",
            (client_id, name, json.dumps(uris), now),
        )
        await self.db.commit()

    async def get_oauth_app(self, client_id: str) -> dict | None:
        rows = await self.db.execute_fetchall(
            "SELECT * FROM oauth_apps WHERE client_id = ?", (client_id,)
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["redirect_uris"] = json.loads(row["redirect_uris"])
        return row

    async def count_oauth_apps(self) -> int:
        rows = await self.db.execute_fetchall("SELECT COUNT(*) AS n FROM oauth_apps")
        return int(rows[0]["n"])

    async def prune_oauth_apps(self, created_before: float) -> None:
        """Registrations that never led to an approved login, older than the cutoff."""
        await self.db.execute(
            "DELETE FROM oauth_apps WHERE created_at < ? AND client_id NOT IN "
            "(SELECT app_id FROM oauth_grants)",
            (created_before,),
        )
        await self.db.commit()

    async def put_oauth_pending(self, request_id: str, data: dict, now: float, cutoff: float):
        await self.db.execute("DELETE FROM oauth_transient WHERE expires_at < ?", (now,))
        await self.db.execute(
            "INSERT INTO oauth_transient (id, kind, data, expires_at) VALUES (?, 'pending', ?, ?)",
            (request_id, json.dumps(data), now + (now - cutoff)),
        )
        await self.db.commit()

    async def put_oauth_code(self, code_hash: str, data: dict, expires_at: float) -> None:
        await self.db.execute(
            "INSERT INTO oauth_transient (id, kind, data, expires_at) VALUES (?, 'code', ?, ?)",
            (code_hash, json.dumps(data), expires_at),
        )
        await self.db.commit()

    async def _pop_transient(self, row_id: str, kind: str, now: float) -> dict | None:
        rows = await self.db.execute_fetchall(
            "SELECT data, expires_at FROM oauth_transient WHERE id = ? AND kind = ?",
            (row_id, kind),
        )
        await self.db.execute(
            "DELETE FROM oauth_transient WHERE id = ? AND kind = ?", (row_id, kind)
        )
        await self.db.commit()
        if not rows or rows[0]["expires_at"] < now:
            return None
        return json.loads(rows[0]["data"])

    async def pop_oauth_pending(self, request_id: str, now: float) -> dict | None:
        return await self._pop_transient(request_id, "pending", now)

    async def pop_oauth_code(self, code_hash: str, now: float) -> dict | None:
        return await self._pop_transient(code_hash, "code", now)

    async def create_oauth_grant(
        self,
        grant_id: str,
        *,
        app_id: str,
        client_id: str,
        access_hash: str,
        access_expires: float,
        refresh_hash: str,
        refresh_expires: float,
        now: float,
    ) -> None:
        await self.db.execute(
            "INSERT INTO oauth_grants (id, app_id, client_id, access_hash, access_expires, "
            "refresh_hash, refresh_expires, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                grant_id,
                app_id,
                client_id,
                access_hash,
                access_expires,
                refresh_hash,
                refresh_expires,
                now,
                now,
            ),
        )
        await self.db.commit()

    async def rotate_oauth_grant(
        self,
        grant_id: str,
        *,
        access_hash: str,
        access_expires: float,
        refresh_hash: str,
        refresh_expires: float,
        now: float,
    ) -> None:
        await self.db.execute(
            "UPDATE oauth_grants SET prev_access_hash = access_hash, "
            "prev_access_expires = access_expires, prev_refresh_hash = refresh_hash, "
            "access_hash = ?, access_expires = ?, refresh_hash = ?, refresh_expires = ?, "
            "last_used_at = ? WHERE id = ?",
            (access_hash, access_expires, refresh_hash, refresh_expires, now, grant_id),
        )
        await self.db.commit()

    async def oauth_grant_by_access(self, access_hash: str, now: float) -> dict | None:
        rows = await self.db.execute_fetchall(
            "SELECT * FROM oauth_grants WHERE (access_hash = ? AND access_expires > ?) "
            "OR (prev_access_hash = ? AND prev_access_expires > ?)",
            (access_hash, now, access_hash, now),
        )
        return dict(rows[0]) if rows else None

    async def oauth_grant_by_refresh(self, refresh_hash: str) -> dict | None:
        rows = await self.db.execute_fetchall(
            "SELECT * FROM oauth_grants WHERE refresh_hash = ?", (refresh_hash,)
        )
        return dict(rows[0]) if rows else None

    async def oauth_grant_by_previous_refresh(self, refresh_hash: str) -> dict | None:
        rows = await self.db.execute_fetchall(
            "SELECT * FROM oauth_grants WHERE prev_refresh_hash = ?", (refresh_hash,)
        )
        return dict(rows[0]) if rows else None

    async def delete_oauth_grant(self, grant_id: str) -> None:
        await self.db.execute("DELETE FROM oauth_grants WHERE id = ?", (grant_id,))
        await self.db.commit()

    async def list_oauth_grants(self) -> list[dict]:
        rows = await self.db.execute_fetchall(
            "SELECT g.id, g.client_id, g.app_id, a.name AS app_name, a.redirect_uris, "
            "g.created_at, g.last_used_at, g.refresh_expires "
            "FROM oauth_grants g JOIN oauth_apps a ON a.client_id = g.app_id "
            "ORDER BY g.created_at"
        )
        out = []
        for r in rows:
            d = dict(r)
            d["redirect_uris"] = json.loads(d["redirect_uris"])
            out.append(d)
        return out

    async def _delete(self, table: str, row_id: str) -> None:
        cur = await self.db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))  # noqa: S608
        await self.db.commit()
        if cur.rowcount == 0:
            raise NotFound(row_id)

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
    # stdio upstreams: url is '' for them; command/args/env describe the local program.
    (
        "upstreams",
        "transport",
        "ALTER TABLE upstreams ADD COLUMN transport TEXT NOT NULL DEFAULT 'http'",
    ),
    ("upstreams", "command", "ALTER TABLE upstreams ADD COLUMN command TEXT NOT NULL DEFAULT ''"),
    ("upstreams", "args", "ALTER TABLE upstreams ADD COLUMN args TEXT NOT NULL DEFAULT '[]'"),
    ("upstreams", "env", "ALTER TABLE upstreams ADD COLUMN env TEXT NOT NULL DEFAULT '{}'"),
    (
        "upstreams",
        "isolate_home",
        "ALTER TABLE upstreams ADD COLUMN isolate_home INTEGER NOT NULL DEFAULT 0",
    ),
]

UPSTREAM_COLS = "id, name, url, transport, command, args, env, isolate_home"


def _upstream(row: dict) -> Upstream:
    return Upstream(
        id=row["id"],
        name=row["name"],
        url=row["url"] or None,
        transport=row["transport"],
        command=row["command"],
        args=json.loads(row["args"]),
        env=json.loads(row["env"]),
        isolate_home=bool(row["isolate_home"]),
    )


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
        rows = await self.db.execute_fetchall(
            f"SELECT {UPSTREAM_COLS} FROM upstreams ORDER BY id"  # noqa: S608
        )
        return [_upstream(dict(r)) for r in rows]

    async def put_upstream(self, u: Upstream) -> Upstream:
        await self.db.execute(
            f"INSERT INTO upstreams ({UPSTREAM_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "  # noqa: S608
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, url = excluded.url, "
            "transport = excluded.transport, command = excluded.command, args = excluded.args, "
            "env = excluded.env, isolate_home = excluded.isolate_home",
            (
                u.id,
                u.name,
                str(u.url) if u.url else "",
                u.transport.value,
                u.command,
                json.dumps(u.args),
                json.dumps(u.env),
                int(u.isolate_home),
            ),
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
            "SELECT id, upstream_id, alias, identity, enabled FROM accounts WHERE id = ?",
            (account_id,),
        )
        if not rows:
            raise NotFound(account_id)
        r = dict(rows[0])
        upstream = await self.get_upstream(r["upstream_id"])
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
            f"SELECT {UPSTREAM_COLS} FROM upstreams WHERE id = ?",  # noqa: S608
            (upstream_id,),
        )
        if not rows:
            raise NotFound(upstream_id)
        return _upstream(dict(rows[0]))

    async def _delete(self, table: str, row_id: str) -> None:
        cur = await self.db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))  # noqa: S608
        await self.db.commit()
        if cur.rowcount == 0:
            raise NotFound(row_id)

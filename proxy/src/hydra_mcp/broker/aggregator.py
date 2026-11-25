"""Aggregates the tools of every account a client is granted into one tool list.

Naming: `{upstream}__{tool}`, one tool per upstream tool (not per account), with an injected
required `account` argument whose enum lists the aliases this client may use for that tool.
`tools/list` is filtered by the client's grants AND every `tools/call` is re-checked, because
a client can call a name it was never shown.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import time
from dataclasses import dataclass

from hydra_mcp.broker.oauth import NotLinked, OAuthBroker, OAuthError
from hydra_mcp.broker.stdio import StdioPool
from hydra_mcp.broker.upstream import UpstreamAuthError, UpstreamClient, UpstreamError
from hydra_mcp.models import Account, Client, Upstream
from hydra_mcp.store import Store

log = logging.getLogger(__name__)

SEP = "__"
MAX_NAME = 64  # common model-API limit for tool names
TOOLS_TTL_S = 300


@dataclass
class _Entry:
    upstream: Upstream
    tool: dict  # upstream tool definition
    accounts: list[Account]  # granted accounts that expose this tool


def tool_name(upstream_id: str, name: str) -> str:
    full = f"{upstream_id}{SEP}{name}"
    if len(full) <= MAX_NAME:
        return full
    digest = hashlib.sha256(full.encode()).hexdigest()[:8]
    return f"{full[: MAX_NAME - 9]}_{digest}"


def _read_only(tool: dict) -> bool:
    return bool((tool.get("annotations") or {}).get("readOnlyHint"))


def _account_param(schema: dict) -> str:
    props = (schema or {}).get("properties") or {}
    return "account" if "account" not in props else "mcp_account"


class Aggregator:
    def __init__(
        self,
        store: Store,
        oauth: OAuthBroker,
        upstream: UpstreamClient,
        stdio: StdioPool | None = None,
    ):
        self.store = store
        self.oauth = oauth
        self.upstream = upstream
        self.stdio = stdio
        self._tools_cache: dict[str, tuple[float, list[dict]]] = {}

    async def invalidate(self, account_id: str | None = None) -> None:
        if account_id is None:
            self._tools_cache.clear()
        else:
            self._tools_cache.pop(account_id, None)
            self.upstream.forget(account_id)
            if self.stdio is not None:
                await self.stdio.forget(account_id)

    async def _call(self, account: Account, upstream: Upstream, method: str, params: dict | None):
        if upstream.is_stdio:
            if self.stdio is None:
                raise UpstreamError("local (stdio) servers are disabled on this proxy")
            env = await self.oauth.stdio_env(account)
            return await self.stdio.request(account.id, upstream, env, method, params)
        token = await self.oauth.access_token(account, upstream)
        try:
            return await self.upstream.request(account.id, str(upstream.url), token, method, params)
        except UpstreamAuthError:
            # The token may have been revoked upstream: drop the session; the user must reconnect.
            self.upstream.forget(account.id)
            raise

    async def _account_tools(self, account: Account, upstream: Upstream) -> list[dict]:
        hit = self._tools_cache.get(account.id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        tools: list[dict] = []
        cursor = None
        while True:
            params = {"cursor": cursor} if cursor else None
            result = await self._call(account, upstream, "tools/list", params)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        self._tools_cache[account.id] = (time.monotonic() + TOOLS_TTL_S, tools)
        return tools

    async def _granted(self, client: Client) -> list[tuple[Account, Upstream]]:
        linked = await self.store.token_status()
        out = []
        for account_id in sorted(client.visible_accounts()):
            try:
                account, upstream = await self.store.get_account(account_id)
            except LookupError:
                continue
            if account.enabled and account_id in linked:
                out.append((account, upstream))
        return out

    async def _catalog(self, client: Client) -> tuple[dict[str, _Entry], list[str]]:
        granted = await self._granted(client)
        results = await asyncio.gather(
            *(self._account_tools(a, u) for a, u in granted), return_exceptions=True
        )
        entries: dict[str, _Entry] = {}
        problems: list[str] = []
        for (account, upstream), tools in zip(granted, results, strict=True):
            if isinstance(tools, BaseException):
                problems.append(f"{account.id}: {tools}")
                log.warning("tools/list failed for %s: %s", account.id, tools)
                continue
            for tool in tools:
                if not client.allows(account.id, tool["name"], read_only=_read_only(tool)):
                    continue
                name = tool_name(upstream.id, tool["name"])
                entry = entries.setdefault(name, _Entry(upstream=upstream, tool=tool, accounts=[]))
                entry.accounts.append(account)
        return entries, problems

    async def list_tools(self, client: Client) -> list[dict]:
        entries, _ = await self._catalog(client)
        out = []
        for name in sorted(entries):
            e = entries[name]
            schema = copy.deepcopy(
                e.tool.get("inputSchema") or {"type": "object", "properties": {}}
            )
            schema.setdefault("type", "object")
            param = _account_param(schema)
            labels = ", ".join(
                f"{a.alias} = {a.identity}" if a.identity else a.alias for a in e.accounts
            )
            schema.setdefault("properties", {})[param] = {
                "type": "string",
                "enum": [a.alias for a in e.accounts],
                "description": f"Which {e.upstream.name} account to use: {labels}",
            }
            schema["required"] = [param, *[r for r in schema.get("required", []) if r != param]]
            tool = {k: v for k, v in e.tool.items() if k not in ("name", "inputSchema")}
            tool["name"] = name
            tool["inputSchema"] = schema
            tool["description"] = f"[{e.upstream.name}; accounts: {labels}] " + (
                e.tool.get("description") or ""
            )
            out.append(tool)
        return out

    async def call_tool(self, client: Client, name: str, arguments: dict) -> dict:
        entries, problems = await self._catalog(client)
        entry = entries.get(name)
        if entry is None:
            hint = f" Unavailable accounts: {'; '.join(problems)}" if problems else ""
            return _error(f"Unknown tool or not granted to this client: {name}.{hint}")
        args = dict(arguments or {})
        param = _account_param(entry.tool.get("inputSchema") or {})
        alias = args.pop(param, None)
        account = next((a for a in entry.accounts if a.alias == alias), None)
        if account is None:
            choices = ", ".join(a.alias for a in entry.accounts)
            return _error(f"Argument '{param}' must be one of: {choices}.")
        # Re-check on every call, independently of what the list showed.
        if not client.allows(account.id, entry.tool["name"], read_only=_read_only(entry.tool)):
            return _error(f"This client may not call {name} on account '{alias}'.")
        try:
            return await self._call(
                account,
                entry.upstream,
                "tools/call",
                {"name": entry.tool["name"], "arguments": args},
            )
        except NotLinked as exc:
            return _error(f"{exc}. Reconnect it in the hydra-mcp admin page.")
        except UpstreamAuthError:
            return _error(
                f"{entry.upstream.name} rejected the token of account '{alias}'. "
                "Reconnect it in the hydra-mcp admin page."
            )
        except (UpstreamError, OAuthError) as exc:
            return _error(f"{entry.upstream.name} ({alias}): {exc}")


def _error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}

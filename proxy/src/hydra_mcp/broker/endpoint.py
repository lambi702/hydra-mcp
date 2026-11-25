"""The aggregated MCP endpoint `/mcp` that clients connect to in broker mode.

Client authentication, two ways, both ending in one hydra-mcp client and its grants:
- a per-client key `Authorization: Bearer hmcp_...` created in the admin page (only its
  SHA-256 is stored), for apps that accept a header: Claude Code, Cursor, VS Code;
- an OAuth access token `hmcp_at_...` issued by the proxy's own authorization server
  (clientauth.py), for apps that only do the MCP OAuth flow: claude.ai, Claude Desktop.

Responses are plain JSON (`application/json`), which Streamable HTTP allows; the endpoint keeps
no session, so any request can be served on its own.
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from hydra_mcp import __version__
from hydra_mcp.broker.aggregator import Aggregator
from hydra_mcp.clientauth import ClientAuth
from hydra_mcp.store import Store

log = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
KEY_PREFIX = "hmcp_"
INSTRUCTIONS = (
    "hydra-mcp exposes several accounts of the same services. Every tool takes an 'account' "
    "argument; pick the account that matches the user's intent and never guess for actions "
    "that send, modify or delete."
)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _rpc_error(msg_id, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}, status
    )


class BrokerEndpoint:
    def __init__(self, store: Store, aggregator: Aggregator, auth: ClientAuth):
        self.store = store
        self.aggregator = aggregator
        self.auth = auth
        external = auth.origins.external
        self._allowed_origin_hosts = {"127.0.0.1", "localhost", "::1"}
        if external:
            self._allowed_origin_hosts.add(urlsplit(external).hostname or "")

    async def handle(self, request: Request) -> Response:
        # DNS-rebinding guard: browsers send Origin; only accept loopback origins (and the
        # external URL's own origin). Server-side clients (claude.ai) send no Origin.
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in self._allowed_origin_hosts:
            return JSONResponse({"error": "origin not allowed"}, 403)
        if request.method != "POST":
            return Response(status_code=405, headers={"Allow": "POST"})

        auth = request.headers.get("authorization", "")
        key = auth.removeprefix("Bearer ").strip()
        if key.startswith(KEY_PREFIX) and not key.startswith(("hmcp_at_", "hmcp_rt_")):
            client = await self.store.client_by_key_hash(hash_key(key))
        else:
            client = await self.auth.client_for_access_token(key)
        if client is None:
            # MCP authorization spec: 401 + a pointer to the protected resource metadata, from
            # which OAuth-capable apps discover the proxy's authorization server.
            return JSONResponse(
                {
                    "error": "invalid_token",
                    "error_description": "missing or unknown client key or access token; "
                    "create a key in the hydra-mcp admin page, or sign in with OAuth",
                },
                401,
                headers={"WWW-Authenticate": self.auth.challenge(request)},
            )

        try:
            msg = await request.json()
        except ValueError:
            return _rpc_error(None, -32700, "parse error", 400)
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _rpc_error(None, -32600, "invalid request (batches are not supported)", 400)

        method = msg.get("method")
        msg_id = msg.get("id")
        if msg_id is None:  # notification or response: acknowledged, nothing to do
            return Response(status_code=202)
        params = msg.get("params") or {}

        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {
                "protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "hydra-mcp", "version": __version__},
                "instructions": INSTRUCTIONS,
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": await self.aggregator.list_tools(client)}
        elif method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str):
                return _rpc_error(msg_id, -32602, "params.name is required")
            result = await self.aggregator.call_tool(client, name, params.get("arguments") or {})
        elif method in ("resources/list", "prompts/list", "resources/templates/list"):
            key_name = {"resources/list": "resources", "prompts/list": "prompts"}.get(
                method, "resourceTemplates"
            )
            result = {key_name: []}
        else:
            return _rpc_error(msg_id, -32601, f"method not found: {method}")
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": result})

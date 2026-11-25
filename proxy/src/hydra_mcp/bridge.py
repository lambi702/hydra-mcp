"""`hydra-mcp bridge`: a stdio MCP server that forwards to a running hydra-mcp's /mcp.

For apps that start local servers as commands but cannot send an HTTP header: Claude Desktop's
`claude_desktop_config.json`, and any other stdio-only client. The app starts this command, the
command relays each JSON-RPC line to http://127.0.0.1:8765/mcp with the client key, and writes
the answer back as one line. No tunnel: everything stays on this machine.

    app --stdin/stdout--> hydra-mcp bridge --HTTP + client key--> hydra-mcp serve --> upstreams

Requests are relayed concurrently (a slow tool call does not block a quick one); stdout writes
are serialized so two answers never interleave. Notifications get no answer, as on stdio.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

from hydra_mcp import __version__

DEFAULT_URL = "http://127.0.0.1:8765/mcp"


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class Bridge:
    def __init__(
        self,
        url: str,
        key: str,
        *,
        out=None,
        timeout_s: float = 300.0,
        http: httpx.AsyncClient | None = None,
    ):
        self.url = url
        self.key = key
        self.out = out or sys.stdout.buffer
        self.lock = asyncio.Lock()
        self.http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            headers={"User-Agent": f"hydra-mcp-bridge/{__version__}"},
        )

    async def write(self, msg: dict) -> None:
        line = json.dumps(msg, separators=(",", ":")).encode() + b"\n"
        async with self.lock:
            self.out.write(line)
            self.out.flush()

    async def relay(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self.write(_error(None, -32700, "parse error"))
            return
        msg_id = msg.get("id") if isinstance(msg, dict) else None
        try:
            resp = await self.http.post(
                self.url,
                json=msg,
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "Accept": "application/json, text/event-stream",
                },
            )
        except httpx.HTTPError as exc:
            if msg_id is not None:
                await self.write(
                    _error(
                        msg_id,
                        -32000,
                        f"hydra-mcp is not reachable at {self.url} ({type(exc).__name__}). "
                        "Is `hydra-mcp serve` running?",
                    )
                )
            return
        if msg_id is None or resp.status_code == 202:
            return
        if resp.status_code == 401:
            await self.write(
                _error(msg_id, -32001, "hydra-mcp refused the client key (HYDRA_MCP_KEY)")
            )
            return
        try:
            await self.write(resp.json())
        except ValueError:
            await self.write(_error(msg_id, -32000, f"hydra-mcp answered {resp.status_code}"))

    async def run(self, reader: asyncio.StreamReader) -> None:
        tasks: set[asyncio.Task] = set()
        try:
            while line := await reader.readline():
                if not line.strip():
                    continue
                task = asyncio.create_task(self.relay(line))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self.http.aclose()


async def _stdin_reader() -> asyncio.StreamReader:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=32 * 1024 * 1024)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    return reader


def main(url: str | None, key: str | None) -> int:
    key = key or os.environ.get("HYDRA_MCP_KEY", "")
    if not key:
        print(
            "hydra-mcp bridge: set HYDRA_MCP_KEY to the client key (hmcp_…) from the admin page",
            file=sys.stderr,
        )
        return 2
    url = url or os.environ.get("HYDRA_MCP_URL") or DEFAULT_URL

    async def go() -> None:
        await Bridge(url, key).run(await _stdin_reader())

    asyncio.run(go())
    return 0

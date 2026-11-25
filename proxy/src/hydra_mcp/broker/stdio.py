"""MCP client for local upstream servers over stdio: one child process per account.

Why one process per account: a stdio server reads its credentials once, from its environment
(`GITHUB_PERSONAL_ACCESS_TOKEN=...`) or from a config folder it writes after a browser login
(`~/.config/<server>/token.json`). It has no notion of "which user is calling". So the only way
to give the same server two identities is to run it twice, each copy with its own environment
and, if asked, its own HOME. The credential key stays (user, account), as for HTTP upstreams.

Wire format (MCP stdio transport): newline-delimited JSON-RPC messages on stdin/stdout, UTF-8,
no embedded newlines. stderr is free-form logging; we keep its tail to explain crashes.

Lifecycle of one process:

    spawn -> initialize -> notifications/initialized -> requests ... -> idle for `idle_s`
          -> close stdin, wait, SIGTERM, wait, SIGKILL (the shutdown order the spec recommends)

A process that dies is respawned by the next request. Requests that were in flight when it
died fail with the last lines of its stderr, which is almost always the real reason ("token
invalid", "command not found", a Python traceback).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from hydra_mcp import __version__
from hydra_mcp.broker.upstream import PROTOCOL_VERSION, UpstreamError
from hydra_mcp.models import Upstream

log = logging.getLogger(__name__)

# Variables a child inherits from the proxy's own environment. Same idea as the MCP SDKs'
# default: enough to find executables and a locale, never the proxy's own secrets
# (HYDRA_MCP_ADMIN_TOKEN, cloud credentials...). Anything else is set explicitly per upstream
# or per account.
INHERITED_ENV = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TERM",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SYSTEMROOT",  # Windows: required by many runtimes
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
)
LINE_LIMIT = 32 * 1024 * 1024  # one JSON-RPC message per line; tool results can be large
STDERR_TAIL = 30
STOP_GRACE_S = 2.0


def child_env(upstream: Upstream, account_env: dict[str, str], home: Path | None) -> dict:
    env = {k: os.environ[k] for k in INHERITED_ENV if k in os.environ}
    env.update(upstream.env)
    env.update(account_env)
    if home is not None:
        # Servers that cache a browser login under ~ (or XDG dirs) get one cache per account.
        env.update(
            HOME=str(home),
            USERPROFILE=str(home),
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_DATA_HOME=str(home / ".local" / "share"),
            XDG_CACHE_HOME=str(home / ".cache"),
        )
    return env


@dataclass
class _Proc:
    key: str
    proc: asyncio.subprocess.Process
    pending: dict[int, asyncio.Future] = field(default_factory=dict)
    stderr: deque[str] = field(default_factory=lambda: deque(maxlen=STDERR_TAIL))
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)
    tasks: list[asyncio.Task] = field(default_factory=list)
    server_info: dict = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return self.proc.returncode is None

    def why(self) -> str:
        tail = " | ".join(line for line in self.stderr if line.strip())[-600:]
        code = self.proc.returncode
        state = f"exited with code {code}" if code is not None else "is running"
        return f"the local server {state}" + (f"; its last output: {tail}" if tail else "")


class StdioPool:
    """Keeps at most one running process per account key, spawned on first use."""

    def __init__(self, data_dir: Path, *, timeout_s: float = 300.0, idle_s: float = 900.0):
        self.data_dir = data_dir
        self.timeout_s = timeout_s
        self.idle_s = idle_s
        self._procs: dict[str, _Proc] = {}
        self._spawn_locks: dict[str, asyncio.Lock] = {}
        self._ids = itertools.count(1)

    def home_for(self, key: str) -> Path:
        return self.data_dir / "stdio" / key

    # -- public API ------------------------------------------------------------------------------
    async def request(
        self,
        key: str,
        upstream: Upstream,
        account_env: dict[str, str],
        method: str,
        params: dict | None = None,
    ) -> dict:
        await self._reap_idle(except_key=key)
        p = await self._get(key, upstream, account_env)
        p.last_used = time.monotonic()
        return await self._rpc(p, method, params)

    async def forget(self, key: str) -> None:
        """Stop the account's process (its env changed, or the account was removed)."""
        p = self._procs.pop(key, None)
        if p is not None:
            await self._stop(p)

    async def close(self) -> None:
        procs, self._procs = list(self._procs.values()), {}
        await asyncio.gather(*(self._stop(p) for p in procs), return_exceptions=True)

    async def probe(self, upstream: Upstream, account_env: dict[str, str], key: str) -> dict:
        """Start a throwaway copy, list its tools, stop it. Used before saving an account, so a
        wrong command or token never becomes a 'connected' account."""
        p = await self._spawn(f"probe-{key}", upstream, account_env, home_key=key)
        try:
            tools = await self._rpc(p, "tools/list", None)
            return {"server_info": p.server_info, "tools": len(tools.get("tools", []))}
        finally:
            await self._stop(p)

    def running(self) -> dict[str, dict]:
        now = time.monotonic()
        return {
            k: {"pid": p.proc.pid, "idle_s": round(now - p.last_used), "server": p.server_info}
            for k, p in self._procs.items()
            if p.alive
        }

    # -- internals -------------------------------------------------------------------------------
    async def _get(self, key: str, upstream: Upstream, account_env: dict[str, str]) -> _Proc:
        p = self._procs.get(key)
        if p is not None and p.alive:
            return p
        lock = self._spawn_locks.setdefault(key, asyncio.Lock())
        async with lock:
            p = self._procs.get(key)
            if p is not None and p.alive:
                return p
            if p is not None:
                log.info("stdio %s: %s; restarting", key, p.why())
                await self._stop(p)
            p = await self._spawn(key, upstream, account_env, home_key=key)
            self._procs[key] = p
            return p

    async def _spawn(
        self, key: str, upstream: Upstream, account_env: dict[str, str], *, home_key: str
    ) -> _Proc:
        if not upstream.command:
            raise UpstreamError(f"{upstream.name}: no command configured")
        home = None
        if upstream.isolate_home:
            home = self.home_for(home_key)
            home.mkdir(mode=0o700, parents=True, exist_ok=True)
        cwd = home or self.data_dir
        cwd.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                upstream.command,
                *upstream.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=child_env(upstream, account_env, home),
                cwd=str(cwd),
                limit=LINE_LIMIT,
                start_new_session=os.name != "nt",  # Ctrl-C on the proxy is not sent twice
            )
        except (FileNotFoundError, PermissionError) as exc:
            raise UpstreamError(
                f"{upstream.name}: cannot start '{upstream.command}': {exc.strerror or exc}. "
                "Is it installed, and on the PATH of the hydra-mcp process?"
            ) from exc
        p = _Proc(key=key, proc=proc)
        p.tasks = [
            asyncio.create_task(self._read_stdout(p), name=f"stdio-out-{key}"),
            asyncio.create_task(self._read_stderr(p), name=f"stdio-err-{key}"),
        ]
        log.info("stdio %s: started %s (pid %s)", key, upstream.command, proc.pid)
        try:
            result = await self._rpc(
                p,
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "hydra-mcp", "version": __version__},
                },
            )
            p.server_info = result.get("serverInfo", {})
            await self._send(p, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            await self._stop(p)
            raise
        return p

    async def _rpc(self, p: _Proc, method: str, params: dict | None) -> dict:
        if not p.alive:
            raise UpstreamError(p.why())
        msg_id = next(self._ids)
        msg: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        p.pending[msg_id] = fut
        try:
            await self._send(p, msg)
            reply = await asyncio.wait_for(fut, self.timeout_s)
        except TimeoutError:
            # Tell the server to stop working on it (spec: notifications/cancelled).
            with contextlib.suppress(Exception):
                await self._send(
                    p,
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/cancelled",
                        "params": {"requestId": msg_id, "reason": "timeout"},
                    },
                )
            raise UpstreamError(f"no answer to {method} within {self.timeout_s:.0f}s") from None
        finally:
            p.pending.pop(msg_id, None)
        if "error" in reply:
            err = reply["error"] or {}
            raise UpstreamError(f"upstream error {err.get('code')}: {err.get('message')}")
        return reply.get("result", {})

    async def _send(self, p: _Proc, msg: dict) -> None:
        # json.dumps escapes newlines inside strings, so one message is always one line.
        line = json.dumps(msg, separators=(",", ":")).encode() + b"\n"
        async with p.write_lock:
            if p.proc.stdin is None or p.proc.stdin.is_closing():
                raise UpstreamError(p.why())
            try:
                p.proc.stdin.write(line)
                await p.proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise UpstreamError(p.why()) from exc

    async def _read_stdout(self, p: _Proc) -> None:
        assert p.proc.stdout is not None
        try:
            while True:
                try:
                    raw = await p.proc.stdout.readline()
                except ValueError:  # one line above LINE_LIMIT: the stream is out of sync
                    p.stderr.append("hydra-mcp: a message was larger than the line limit")
                    break
                if not raw:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    # Servers that print banners on stdout break the protocol; keep it as a
                    # hint for the error message instead of crashing.
                    p.stderr.append(f"(stdout) {raw[:200].decode(errors='replace').strip()}")
                    continue
                if isinstance(msg, dict):
                    await self._dispatch(p, msg)
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(p.proc.wait(), STOP_GRACE_S)
            for fut in p.pending.values():
                if not fut.done():
                    fut.set_exception(UpstreamError(p.why()))

    async def _dispatch(self, p: _Proc, msg: dict) -> None:
        if "method" not in msg:  # a response
            fut = p.pending.get(msg.get("id"))  # type: ignore[arg-type]
            if fut is not None and not fut.done():
                fut.set_result(msg)
            return
        if "id" not in msg:  # a notification (logging, progress, list_changed): not relayed
            return
        # A request from the server. We declared no client capabilities, so only ping applies.
        if msg["method"] == "ping":
            reply: dict = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
        else:
            reply = {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "error": {"code": -32601, "message": f"not supported: {msg['method']}"},
            }
        with contextlib.suppress(UpstreamError):
            await self._send(p, reply)

    async def _read_stderr(self, p: _Proc) -> None:
        assert p.proc.stderr is not None
        while True:
            try:
                raw = await p.proc.stderr.readline()
            except ValueError:
                continue
            if not raw:
                return
            line = raw.decode(errors="replace").rstrip()
            p.stderr.append(line)
            log.debug("stdio %s: %s", p.key, line)

    async def _stop(self, p: _Proc) -> None:
        proc = p.proc
        if proc.returncode is None:
            if proc.stdin is not None:
                with contextlib.suppress(Exception):
                    proc.stdin.close()
            try:
                await asyncio.wait_for(proc.wait(), STOP_GRACE_S)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), STOP_GRACE_S)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    await proc.wait()
        for task in p.tasks:
            task.cancel()
        await asyncio.gather(*p.tasks, return_exceptions=True)
        log.info("stdio %s: stopped (code %s)", p.key, proc.returncode)

    async def _reap_idle(self, except_key: str) -> None:
        now = time.monotonic()
        idle = [
            k
            for k, p in self._procs.items()
            if k != except_key and (not p.alive or now - p.last_used > self.idle_s)
        ]
        for k in idle:
            await self.forget(k)

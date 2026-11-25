"""Domain model.

Upstream  -- an MCP server (one URL), e.g. Gmail MCP or Atlassian MCP.
Account   -- one identity at one upstream ("gmail/work", "gmail/perso").
             The credential key of the whole proxy is (user, account), never (user, upstream).
Client    -- one login of one MCP client app at the proxy (Claude Desktop, Claude Code...).
Grant     -- what a client may use: an account, a tool pattern, and read/write mode.
"""

from __future__ import annotations

import fnmatch
import re
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def _slug(v: str) -> str:
    if not SLUG_RE.match(v):
        raise ValueError("must be 1-32 chars of a-z, 0-9 and '-', starting with a letter or digit")
    return v


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class Transport(StrEnum):
    HTTP = "http"  # Streamable HTTP: a remote server at `url`
    STDIO = "stdio"  # a local program the proxy starts, one process per account


class Upstream(BaseModel):
    id: str = Field(description="slug, e.g. 'gmail'")
    name: str
    transport: Transport = Transport.HTTP
    url: HttpUrl | None = Field(
        default=None, description="canonical MCP endpoint of the upstream server (http)"
    )
    # stdio only. The command is run directly (no shell): no quoting, no `~`, no `$VAR`.
    command: str = ""
    args: list[str] = Field(default_factory=list)
    # Non-secret settings shared by every account of this server. Secrets go per account,
    # encrypted in the vault.
    env: dict[str, str] = Field(default_factory=dict)
    # Give each account its own HOME / XDG folders, for servers that cache a login there.
    isolate_home: bool = False

    _check_id = field_validator("id")(_slug)

    @field_validator("env")
    @classmethod
    def _check_env(cls, v: dict[str, str]) -> dict[str, str]:
        bad = [k for k in v if not ENV_NAME_RE.match(k)]
        if bad:
            raise ValueError(f"invalid environment variable names: {', '.join(bad)}")
        return v

    @model_validator(mode="after")
    def _check_transport(self) -> Upstream:
        if self.transport is Transport.HTTP and self.url is None:
            raise ValueError("an http upstream needs a url")
        if self.transport is Transport.STDIO and not self.command.strip():
            raise ValueError("a stdio upstream needs a command")
        return self

    @property
    def is_stdio(self) -> bool:
        return self.transport is Transport.STDIO


class Account(BaseModel):
    id: str = Field(description="slug, unique across the proxy, e.g. 'gmail-work'")
    upstream_id: str
    alias: str = Field(description="what the model sees, e.g. 'work'")
    identity: str = Field(default="", description="human hint, e.g. alice@corp.example")
    enabled: bool = True

    _check_id = field_validator("id")(_slug)


class GrantMode(StrEnum):
    READ = "read"  # only tools annotated readOnlyHint=true
    WRITE = "write"  # everything (read + write)


class Grant(BaseModel):
    account_id: str
    tools: str = Field(default="*", description="fnmatch pattern on the upstream tool name")
    mode: GrantMode = GrantMode.WRITE


class Client(BaseModel):
    id: str
    name: str
    grants: list[Grant] = Field(default_factory=list)

    _check_id = field_validator("id")(_slug)

    def visible_accounts(self) -> set[str]:
        return {g.account_id for g in self.grants}

    def allows(self, account_id: str, tool: str, *, read_only: bool) -> bool:
        """Authorization check, run on every call (list filtering alone is not security)."""
        for g in self.grants:
            if g.account_id != account_id or not fnmatch.fnmatchcase(tool, g.tools):
                continue
            if g.mode is GrantMode.WRITE or read_only:
                return True
        return False

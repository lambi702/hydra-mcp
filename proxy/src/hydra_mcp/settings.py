"""Runtime settings, read from environment variables prefixed with HYDRA_MCP_ (or a .env file)."""

from __future__ import annotations

import secrets
from functools import cached_property
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HYDRA_MCP_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8765
    # URL clients use to reach the proxy. It becomes the OAuth `resource` of every account route,
    # so it must be exactly what you paste into your MCP client.
    public_url: str = "http://127.0.0.1:8765"
    # Optional HTTPS URL of this proxy on the internet (a tunnel), for apps that connect from
    # their own servers: claude.ai, Claude Desktop custom connectors, mobile. Only the MCP
    # endpoint and the OAuth login of apps are served under it; the admin page, the admin
    # API, upstream callbacks and router mode stay local-only.
    external_url: str = ""
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".hydra-mcp")
    # Leave empty to generate one on first start (stored in data_dir/admin_token).
    admin_token: str = ""
    # Built admin page (admin/dist). Served at /admin when it exists.
    admin_dist: Path | None = None
    upstream_timeout_s: float = 300.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hydra-mcp.sqlite3"

    @property
    def base_url(self) -> str:
        return self.public_url.rstrip("/")

    @property
    def external_base_url(self) -> str:
        return self.external_url.rstrip("/")

    @cached_property
    def resolved_admin_token(self) -> str:
        if self.admin_token:
            return self.admin_token
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.data_dir / "admin_token"
        if path.exists():
            return path.read_text().strip()
        token = secrets.token_urlsafe(32)
        path.write_text(token)
        path.chmod(0o600)
        return token

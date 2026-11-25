"""Connector library: well-known remote MCP servers for one-click upstream setup.

The data lives in connectors.json (sourced from vendor docs, see `docs` per entry and
`checked_at`). Entries are suggestions: installing one only creates an Upstream row.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import cache
from importlib import resources

from pydantic import BaseModel, HttpUrl


class AuthKind(StrEnum):
    OAUTH_DCR = "oauth_dcr"  # client registers itself (DCR / Client ID Metadata Document)
    OAUTH = "oauth"  # OAuth; registration method not documented by the vendor
    OAUTH_PREREGISTERED = "oauth_preregistered"  # you must create an OAuth client first
    BEARER = "bearer"  # API key / personal token in Authorization header


class Link(BaseModel):
    label: str
    url: HttpUrl


class Field(BaseModel):
    label: str
    value: str  # may hold {redirect_uri} / {base_url}, filled in by the setup guide


class Step(BaseModel):
    title: str
    text: str
    link: HttpUrl | None = None
    fields: list[Field] = []


class TokenOption(BaseModel):
    """The provider also accepts a static token as `Authorization: Bearer <token>`."""

    name: str
    create_url: HttpUrl
    how: str


class ClientSetup(BaseModel):
    """How to create the OAuth client by hand, for providers without dynamic registration."""

    provider: str
    client_type: str
    steps: list[Step]


class Guide(BaseModel):
    summary: str
    before: list[str] = []  # prerequisites, read before the first login
    accounts: str = ""  # how several accounts of this provider are told apart
    gotchas: list[str] = []
    token: TokenOption | None = None
    client: ClientSetup | None = None
    links: list[Link] = []


class Connector(BaseModel):
    id: str
    name: str
    vendor: str
    category: str
    url: HttpUrl
    auth: AuthKind
    status: str  # "ga" | "preview"
    scopes: list[str] = []
    notes: str = ""
    docs: HttpUrl
    guide: Guide | None = None
    # The provider ties an OAuth client to one workspace (Slack internal apps): each workspace
    # needs its own client, hence its own upstream row. The admin page then offers
    # "+ Another workspace", which creates a new upstream instead of reusing this one.
    one_client_per_workspace: bool = False
    # Callback host the provider accepts for a plain-http local proxy. Slack only allows http
    # redirects to `localhost` (as "desktop" redirects of PKCE apps), not to 127.0.0.1.
    redirect_host: str | None = None
    # How the provider wants the `scope` parameter joined (Slack: commas).
    scope_separator: str = " "


class Catalog(BaseModel):
    checked_at: str
    connectors: list[Connector]

    def get(self, connector_id: str) -> Connector | None:
        return next((c for c in self.connectors if c.id == connector_id), None)


@cache
def load_catalog() -> Catalog:
    raw = resources.files(__package__).joinpath("connectors.json").read_text(encoding="utf-8")
    return Catalog.model_validate(json.loads(raw))
